import os
import time

import openai
import whisper
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError

from Agents.Logger_Agent import log_or_print, get_current

# Canonical ElevenLabs docs example voice. Confirmed free-tier accessible
# with a key that only has text_to_speech permission.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

# OpenAI tts-1 fallback config — used when ElevenLabs is out of credits.
# tts-1 is ~$15/1M chars and ships 6 natural-sounding voices.
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "nova")


def _eleven_key() -> str:
    return os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELVENLABS_API_KEY") or ""


def _is_quota_error(status, body: str) -> bool:
    if status == 402:
        return True
    if status == 401 and ("quota_exceeded" in body or "quota exceeded" in body.lower()
                          or "insufficient" in body.lower() or "credits" in body.lower()):
        return True
    return False


class VoiceProcessingAgent:
    """
    Speech-to-text via Whisper (local).
    Text-to-speech via the official ElevenLabs Python SDK only — no fallback engines.

    Required env:
        ELEVENLABS_API_KEY  (or ELVENLABS_API_KEY)  — needs only text_to_speech permission
    Optional env:
        ELEVENLABS_VOICE_ID   default: JBFqnCBsd6RMkjVDRZzb (George, free-tier accessible)
        ELEVENLABS_MODEL      default: eleven_multilingual_v2
    """

    def __init__(self, stt_model_size: str = "base", tts_voice_id: str = None,
                 tts_model: str = None):
        self._stt_size = stt_model_size
        self._whisper = None  # lazy load
        self.api_key = _eleven_key()
        if not self.api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY not set. Add it to .env. ElevenLabs is the only TTS provider."
            )
        self.tts_voice_id = tts_voice_id or os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
        self.tts_model = tts_model or os.getenv("ELEVENLABS_MODEL") or DEFAULT_MODEL
        self._client = ElevenLabs(api_key=self.api_key)
        log_or_print("ElevenLabs TTS configured", level="info",
                     voice_id=self.tts_voice_id, model=self.tts_model)

    @property
    def whisper_model(self):
        if self._whisper is None:
            log_or_print(f"Loading whisper model={self._stt_size}", level="info")
            t0 = time.time()
            self._whisper = whisper.load_model(self._stt_size)
            log_or_print("Whisper loaded", level="info", elapsed_s=round(time.time() - t0, 2))
        return self._whisper

    def speech_to_text(self, audio_file_path: str) -> str:
        log = get_current()
        if log: log.step_start("VoiceAgent.stt", audio=audio_file_path)
        try:
            result = self.whisper_model.transcribe(audio_file_path)
            text = result["text"].strip()
            if log: log.step_end("VoiceAgent.stt", text_len=len(text))
            return text
        except Exception as e:
            if log: log.error("VoiceAgent.stt failed", exc_info=True, error=str(e))
            else: print(f"STT Error: {e}")
            return ""

    def _convert(self, text: str, voice_id: str) -> bytes:
        """SDK convert() returns an iterator of audio chunks — join into a single blob."""
        stream = self._client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=self.tts_model,
            output_format=DEFAULT_OUTPUT_FORMAT,
        )
        if isinstance(stream, (bytes, bytearray)):
            return bytes(stream)
        return b"".join(chunk for chunk in stream if chunk)

    def _convert_openai(self, text: str) -> bytes:
        """OpenAI tts-1 fallback. Returns mp3 bytes."""
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OpenAI fallback requires OPENAI_API_KEY in env."
            )
        resp = openai.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="mp3",
        )
        # New SDK: resp.read() / resp.content; older: bytes(resp)
        if hasattr(resp, "read"):
            return resp.read()
        if hasattr(resp, "content"):
            return resp.content
        return bytes(resp)

    def text_to_speech(self, text: str, output_path: str) -> str:
        """Synthesize via ElevenLabs SDK; fall back to OpenAI tts-1 on quota errors."""
        log = get_current()
        if log: log.step_start("VoiceAgent.tts_eleven",
                               text_len=len(text), voice=self.tts_voice_id, out=output_path)

        provider = "elevenlabs"
        try:
            audio_bytes = self._convert(text, self.tts_voice_id)
        except ApiError as e:
            status = getattr(e, "status_code", None)
            body = str(getattr(e, "body", e))[:600]
            if log: log.error("VoiceAgent.tts_eleven api error",
                              status_code=status, body=body, voice=self.tts_voice_id)
            if _is_quota_error(status, body):
                if log: log.step_start("VoiceAgent.tts_openai",
                                       text_len=len(text),
                                       model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                                       reason="elevenlabs_quota_exceeded")
                try:
                    audio_bytes = self._convert_openai(text)
                    provider = "openai"
                    if log: log.step_end("VoiceAgent.tts_openai", bytes=len(audio_bytes))
                except Exception as oe:
                    if log: log.error("VoiceAgent.tts_openai failed",
                                      exc_info=True, error=str(oe))
                    raise RuntimeError(
                        f"ElevenLabs quota exhausted ({status}: {body}) and OpenAI fallback "
                        f"failed: {oe}"
                    ) from oe
            elif status == 401:
                raise RuntimeError(
                    f"ElevenLabs 401: {body}. Regenerate the API key with text_to_speech permission."
                ) from e
            else:
                raise RuntimeError(f"ElevenLabs API error {status}: {body}") from e
        except Exception as e:
            if log: log.error("VoiceAgent.tts_eleven network error",
                              exc_info=True, error=str(e))
            raise

        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        size = os.path.getsize(output_path)
        if log: log.step_end("VoiceAgent.tts_eleven", bytes=size,
                             out=output_path, voice=self.tts_voice_id, provider=provider)
        if size == 0:
            raise RuntimeError(f"{provider} returned empty audio")
        return output_path
