import whisper
import pyttsx3
import tempfile
import os

class VoiceProcessingAgent:
    """
    VoiceProcessingAgent:
    - Converts speech (audio file) to text using OpenAI Whisper (local).
    - Converts text to speech (TTS) using pyttsx3 (local).
    """

    def __init__(self, stt_model_size: str = "base", tts_voice: str = None):
        # Load Whisper STT model. Options: "tiny", "base", "small", "medium", "large"
        self.whisper_model = whisper.load_model(stt_model_size)
        self.tts_engine = pyttsx3.init()
        # Optionally set voice (e.g., male/female/accent)
        if tts_voice:
            self.set_tts_voice(tts_voice)

    def set_tts_voice(self, voice_name: str):
        """Set a specific TTS voice if available on the system."""
        voices = self.tts_engine.getProperty('voices')
        found = False
        for v in voices:
            if voice_name.lower() in v.name.lower():
                self.tts_engine.setProperty('voice', v.id)
                found = True
                break
        if not found:
            print(f"Voice '{voice_name}' not found. Using default voice.")

    def speech_to_text(self, audio_file_path: str) -> str:
        """
        Converts speech (audio file) to text using Whisper.
        - audio_file_path: Path to .wav, .mp3, etc.
        - Returns transcribed text.
        """
        try:
            result = self.whisper_model.transcribe(audio_file_path)
            return result["text"].strip()
        except Exception as e:
            print(f"STT Error: {e}")
            return ""

    def text_to_speech(self, text: str, output_path: str = None) -> str:
        """
        Converts text to speech and saves as an audio file (mp3 by default).
        - text: The string to synthesize.
        - output_path: Optional file path. If None, creates a temp file.
        - Returns path to the saved audio file.
        """
        try:
            if output_path is None:
                fd, output_path = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
            self.tts_engine.save_to_file(text, output_path)
            self.tts_engine.runAndWait()
            return output_path
        except Exception as e:
            print(f"TTS Error: {e}")
            return ""
