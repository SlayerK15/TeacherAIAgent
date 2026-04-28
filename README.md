# TeacherAIAgent

TeacherAIAgent is a multi-agent teaching platform that converts a prompt (or voice query) into structured lessons, storyboarded visuals, and optional narrated video.

## Core capabilities
- Topic discovery and decomposition
- Lesson simplification and teaching generation
- Full transcript/script generation for target duration
- Storyboard planning (scenes, keywords, visual type, timing)
- Graphics collection from free/legal-friendly providers
- Video generation with optional TTS narration
- Clarification Q&A with session memory
- Browser dashboard for end-to-end usage

## Architecture at a glance
- **Backend:** FastAPI (`API/api.py`)
- **Agents:** Modular pipeline in `Agents/`
- **Frontend:** Dashboard UI in `Dashboard/dashboard.html`
- **Outputs:** saved under `output/`

Detailed documentation: **`Docs/Complete_App_Guide.md`**.

---

## API endpoints
- `POST /teach` — full pipeline (prompt/audio -> lesson + video)
- `POST /storyboard` — storyboard JSON generation
- `POST /visual-intelligence` — transcript-driven keyword/asset plan
- `POST /clarify` — follow-up Q&A
- `GET /` — serves dashboard
- `GET /api/health` — health status

---

## Quickstart
```bash
uv sync
```

Set environment variables in `.env`:
- `OPENAI_API_KEY` (required)
- `ELEVENLABS_API_KEY` (for narration)
- `PEXELS_API_KEY` (optional)
- `UNSPLASH_ACCESS_KEY` (optional)

Run server:
```bash
uv run uvicorn API.api:app --reload
```

Open:
- `http://127.0.0.1:8000/`

---

## Frontend included
The built-in dashboard supports:
- text/audio input modes
- animation/silent toggles
- transcript and pipeline dump views
- live logs
- follow-up clarification
- visual intelligence plan preview

---

## Notes
- This repository is intended for educational/research usage.
- See `UPGRADE_NOTES.md` for latest dependency/runtime upgrades.
