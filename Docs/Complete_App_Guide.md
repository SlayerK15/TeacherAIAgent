# TeacherAIAgent — Complete Architecture & Product Guide

## 1) What this app does
TeacherAIAgent turns a user prompt (or uploaded audio question) into a complete teaching experience:
- topic discovery and decomposition
- simplified lesson steps
- full teaching script/transcript generation
- storyboard creation with visuals
- video generation with optional narration
- follow-up clarification Q&A
- visual-intelligence planning for keyword-driven legal/free graphics retrieval

The app includes:
- **FastAPI backend** (`API/api.py`)
- **Agent modules** (`Agents/*.py`)
- **Web frontend dashboard** (`Dashboard/dashboard.html`)
- **Output artifacts** (video, frames, audio, logs, responses under `output/`)

---

## 2) Architecture

## 2.1 High-level flow
1. Client sends request to backend (`/teach`, `/storyboard`, or `/visual-intelligence`).
2. Backend orchestrates agents for topic analysis, script creation, and visuals.
3. Video pipeline renders frames + narration into MP4.
4. Frontend streams results, logs, and follow-up clarification.

## 2.2 Agent pipeline (primary)
1. **DiscoveryAgent**: parses user intent into topic tiers.
2. **SimplificationAgent**: turns tiers into teachable step lists.
3. **TeachingAgent**: generates detailed lesson content.
4. **EngagingVideoTranscriptGeneratorAgent**: composes a full video script.
5. **StoryboardComposer_Agent**: builds scenes with timings + visual assets + layout.
6. **VideoGenerationAgent**: produces output video/audio assets.
7. **ClarificationAgent**: answers follow-up questions using saved context.
8. **ContextMemoryAgent**: persists session state.

## 2.3 Visual intelligence layer
`VisualIntelligenceLayer_Agent` adds transcript-first visual planning:
- extracts compact visual keywords from transcript chunks
- generates chunk-level visual plans
- calls `AssetFetcher_Agent` (graphics collector) to retrieve relevant assets

Graphics sources are pulled via existing provider logic in `AssetFetcher_Agent`:
- keyless: Iconify, Openverse
- optional keys: Pexels, Unsplash

---

## 3) Frontend

The dashboard (single-page HTML/CSS/JS) provides:
- text or audio lesson input
- duration/session/animation controls
- video playback + download
- transcript and pipeline JSON views
- live log tailing
- follow-up clarification form
- visual-intelligence plan explorer

It is mounted by FastAPI and served at:
- `/` (if dashboard exists)
- `/dashboard` static mount

---

## 4) API Endpoints

## 4.1 `POST /teach`
Generate the full lesson + optional video.

Form fields:
- `user_prompt` (optional if `audio` provided)
- `audio` (optional if `user_prompt` provided)
- `session_id` (default: `default`)
- `video_minutes` (default: 8)
- `animated` (`true/false`)
- `silent` (`true/false`)

Returns:
- topic tiers, simplified steps, lessons, generated script, output paths, logs.

## 4.2 `POST /storyboard`
Generate storyboard JSON.

Form fields:
- `transcript` OR `user_prompt`
- `video_minutes` (optional)

Returns:
- scene list with timing, assets, and layout blocks.

## 4.3 `POST /visual-intelligence`
Generate transcript-driven visual plan.

Form fields:
- `transcript` (required)
- `topic` (optional)

Returns:
- `chunk_count`
- `plan[]` with chunk text, extracted keywords, visual type, assets.

## 4.4 `POST /clarify`
Ask follow-up questions grounded in session context.

Form fields:
- `user_question`
- `topic`
- `session_id`

Returns:
- `answer`

## 4.5 `GET /` and `GET /api/health`
- `/`: dashboard file response (or status JSON fallback)
- `/api/health`: service health JSON

---

## 5) Running locally
1. `uv sync`
2. Set `.env` vars: `OPENAI_API_KEY` (+ optional `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY`, `ELEVENLABS_API_KEY`).
3. `uv run uvicorn API.api:app --reload`
4. Open `http://127.0.0.1:8000/`

---

## 6) Output layout
- `output/video/<session>/...mp4`
- `output/audio/<session>/...`
- `output/frames/<session>/...`
- `output/logs/<session>.log`
- `output/response/<session>.txt`

---

## 7) What it can do today
- teach any topic from text or voice prompt
- create short/long narrated educational videos
- generate storyboard scenes with timed visual assets
- fetch relevant graphics from free/legal-friendly providers
- answer session-aware clarifying questions
- expose debug-friendly visual plan endpoint for product integrations

---

## 8) Suggested next enhancements
- user auth + saved course history
- chapter-level editing and re-render
- stricter license policy controls by endpoint parameter
- analytics dashboard (completion time, topic retention)
- multi-language lesson and subtitle tracks
