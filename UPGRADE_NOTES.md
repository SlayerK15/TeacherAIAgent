# Upgrade Notes — 2026-04-27

Cavemen log. Bump all deps. Drop fallback TTS. Use latest ElevenLabs SDK.

## Package versions (all latest from PyPI)

| Package | Old | New |
|---|---|---|
| openai | >=1.3.3 | >=2.32.0 |
| openai-whisper | (unpinned) | >=20250625 |
| numpy | (unpinned) | >=2.4.4 |
| torch | (unpinned) | >=2.11.0 |
| soundfile | (unpinned) | >=0.13.1 |
| fastapi | (unpinned) | >=0.136.1 |
| uvicorn | (unpinned) | >=0.46.0 |
| chromadb | (unpinned) | >=1.5.8 |
| httpx | (unpinned) | >=0.28.1 |
| moviepy | >=2.0.0 | >=2.2.1 |
| pillow | (unpinned) | >=11.3.0,<12 (capped — moviepy 2.2.1 requires `pillow<12`) |
| python-multipart | (unpinned) | >=0.0.26 |
| python-dotenv | >=1.2.2 | >=1.2.2 |
| tqdm | (unpinned) | >=4.67.3 |
| elevenlabs | >=2.44.0 | >=2.44.0 |
| pyttsx3 | present | **REMOVED** |

`requires-python` bumped from `>=3.10` to `>=3.11` (numpy 2.4.4 needs ≥3.11). Local interpreter is 3.11.9 — already compat.

## File changes

### `pyproject.toml`
- Removed `pyttsx3` dep.
- Pinned all deps to `>=latest`.
- Bumped `requires-python` to `>=3.11`.
- Capped `pillow<12` (moviepy 2.2.1 dep cap).

### `Agents/VoiceProcessing_Agent.py`
- Dropped raw `httpx` calls.
- Switched to official `elevenlabs.client.ElevenLabs` SDK (`text_to_speech.convert(...)`).
- Joins SDK's chunk iterator into bytes via `b"".join(...)`.
- Catches `elevenlabs.core.api_error.ApiError` for status-code-aware error paths (402 voice block, 401 missing perms).
- **Removed `_resolve_owned_voice` and `list_voices`** — key only has `text_to_speech` permission, `voices_read` calls would always 401. Dead code purged.
- **Default voice changed from `21m00Tcm4TlvDq8ikWAM` (Rachel — 402 on free tier) to `JBFqnCBsd6RMkjVDRZzb` (George — canonical docs example, free-tier accessible).**
- No fallback engines (no pyttsx, no gtts, etc).

### `uv.lock`
- Regenerated via `uv lock --upgrade`.
- Removed: `pyttsx3`, `comtypes`, `pypiwin32`, `pywin32`, plus pyobjc-framework-* leaves.

## Real-query smoke tests run

| Test | Result |
|---|---|
| `uv run python -c "from elevenlabs.client import ElevenLabs; ..."` (imports) | OK |
| `uv run python test_storyboard.py` (full transcript→storyboard via OpenAI gpt-4o-mini) | OK — 17 scenes, 88 s total, JSON written to `output/storyboard_earth.json` |
| `ContextMemoryAgent.save/get/append_to_list` (chromadb 1.5.8 with old `Settings(persist_directory=...)` pattern) | OK |
| `uvicorn API.api:app` startup + `GET /` | OK — `{"status":"AI Teacher Agent API running!"}` |
| `POST /storyboard` with transcript + `video_minutes=2` | OK — 3 scenes returned, asset fetch from iconify + pexels worked |
| `VoiceProcessingAgent.text_to_speech("hello", ...)` (real ElevenLabs call, default voice George `JBFqnCBsd6RMkjVDRZzb`) | OK — 38 914 bytes mp3 written |

## Compat notes for openai 2.x
- Module-level `openai.api_key = ...` and `openai.chat.completions.create(...)` calls **still work** in 2.32.0 (verified via real call in `test_storyboard.py`). No code change needed in `main.py`, `API/api.py`, `test_storyboard.py`.

## Compat notes for chromadb 1.5.8
- Old `chromadb.Client(Settings(persist_directory="./chroma_db"))` pattern still functional. Verified via real upsert/get/append round-trip.
- Stricter collection-name validation (must start/end with `[a-zA-Z0-9]`, length 3–512). Project's name `ait_teacher_memory` passes.

## Compat notes for moviepy 2.2.1
- v2 API (`with_duration`, `with_audio`, `concatenate_videoclips`, `CompositeVideoClip`, `ImageClip`, `AudioFileClip`, `VideoFileClip`) imports verified.
- Pillow capped at <12 due to moviepy upper bound.

## Free-tier voice IDs that work with `text_to_speech`-only key
Probed live against the user's API key:

| Voice ID | Name | Free-tier? |
|---|---|---|
| `JBFqnCBsd6RMkjVDRZzb` | George | YES (default) |
| `EXAVITQu4vr4xnSDxMaL` | Bella | YES |
| `pNInz6obpgDQGcFmaJgB` | Adam | YES |
| `21m00Tcm4TlvDq8ikWAM` | Rachel | NO — 402 |
| `TxGEqnHWrfWFTfGW9XjX` | Josh | NO — 402 |

Override via `ELEVENLABS_VOICE_ID` in `.env` if you want a different voice.
