# TeacherAIAgent — Agent Deep Dive (Architecture, Responsibilities, Dependencies)

This document explains every major agent in the repository, how each one works internally, how agents hand off to each other, and what dependencies each component uses.

---

## 1. System-wide pipeline overview

At runtime, the app behaves as an agent pipeline orchestrated primarily by FastAPI routes in `API/api.py`.

Primary lesson/video pipeline (`POST /teach`):
1. Input ingestion (`user_prompt` text or uploaded `audio`)
2. `DiscoveryAgent` (topic extraction and tiering)
3. `SimplificationAgent` (convert topics into teachable steps)
4. `TeachingAgent` (generate lesson content per step)
5. `EngagingVideoTranscriptGeneratorAgent` (compose full script)
6. `StoryboardComposer_Agent` (scenes + asset fetch + layout + scene enhancement)
   - internally uses `SceneplannerAgent`, `AssetFetcher_Agent`, `LayoutEngine_Agent`, `VisualIntelligenceLayer_Agent`, `SceneDirector_Agent`
7. `VideoGenerationAgent` (rendering + optional narration)
8. `ContextMemoryAgent` persists artifacts for follow-up routes

Support pipelines:
- `POST /clarify`: `ClarificationAgent` + memory context
- `POST /storyboard`: transcript -> storyboard JSON
- `POST /visual-intelligence`: transcript -> visual plan (semantic chunking + assets)
- `POST /enhance-scenes`: existing scene list -> director-style enriched scene metadata

---

## 2. Core orchestration (`API/api.py`)

### Responsibilities
- Initializes all agents once at process startup.
- Hosts endpoints and transforms incoming form data into agent calls.
- Persists and returns user-facing output references (video URL, response txt, log URL).
- Mounts static dashboard and output folders.

### Key dependencies
- **FastAPI stack**: `fastapi`, `uvicorn`, `python-multipart`
- **OpenAI SDK** for LLM function (`openai_llm`)
- **dotenv** for env config
- Standard libs: `os`, `json`, `glob`, `datetime`, etc.

### Agent registry created in API layer
- `VoiceProcessingAgent`
- `DiscoveryAgent`
- `SimplificationAgent`
- `TeachingAgent`
- `EngagingVideoTranscriptGeneratorAgent`
- `ClarificationAgent`
- `ContextMemoryAgent`
- `VideoGenerationAgent`
- `StoryboardComposer_Agent`
- `VisualIntelligenceLayer_Agent`
- `SceneDirector_Agent`

---

## 3. Agent-by-agent deep dive

## 3.1 `DiscoveryAgent`

### Purpose
Parses a raw user request into structured topic tiers (main/supporting/background), giving downstream agents a hierarchical curriculum frame.

### Inputs
- text prompt (`input_type="text"`) OR transcribed prompt from audio path (`input_type="audio"`)

### Outputs
- Dictionary-like topic tier structure

### Internal dependencies
- `openai_llm` (LLM reasoning)
- `VoiceProcessingAgent` for audio-driven flow

### Why it matters
It defines scope and reduces drift; all later agents depend on this decomposition quality.

---

## 3.2 `SimplificationAgent`

### Purpose
Transforms discovered tiers into concise, teachable steps.

### Inputs
- Topic-tier object from `DiscoveryAgent`

### Outputs
- Simplified plan keyed by topic

### Dependencies
- `openai_llm`

### Why it matters
Prevents over-dense lesson text and makes teaching output easier to narrate and visualize.

---

## 3.3 `TeachingAgent`

### Purpose
Generates fuller instructional content for each simplified step.

### Inputs
- Simplified step plan

### Outputs
- Lesson map (`topic -> lesson text`)

### Dependencies
- `openai_llm`

### Why it matters
Produces domain content later transformed into transcript and scene-level visuals.

---

## 3.4 `EngagingVideoTranscriptGeneratorAgent`

### Purpose
Builds a continuous narration script optimized for target video length.

### Inputs
- Lesson map
- Duration constraints (`video_minutes`)

### Outputs
- Single transcript string suitable for TTS + scene planning

### Dependencies
- `openai_llm`

### Why it matters
Transcript quality drives both visual planning and pacing.

---

## 3.5 `VoiceProcessingAgent`

### Purpose
Provides speech-related capabilities:
- STT for audio input mode
- TTS for narration output in video generation

### Dependencies
- `openai-whisper` (local STT)
- `elevenlabs` SDK (TTS)
- audio stack (`soundfile`, etc.)

### Operational notes
- Handles provider/API errors and key/voice availability constraints.

---

## 3.6 `ContextMemoryAgent`

### Purpose
Stores and retrieves per-session artifacts:
- user input
- topic tiers
- simplified steps
- lessons
- transcript
- clarify history

### Dependencies
- `chromadb`

### Why it matters
Enables contextual clarifications and continuity across endpoint calls.

---

## 3.7 `ClarificationAgent`

### Purpose
Answers follow-up questions grounded in generated lesson context and prior history.

### Inputs
- user question
- selected topic
- memory context + clarifications

### Outputs
- text answer

### Dependencies
- `openai_llm`
- `ContextMemoryAgent` data

---

## 3.8 `SceneplannerAgent`

### Purpose
Converts transcript text into timed scene units (text, duration, keywords, visual intent hints).

### Dependencies
- `openai_llm`

### Why it matters
Defines the scene skeleton consumed by fetch/layout/director agents.

---

## 3.9 `AssetFetcher_Agent` (graphics collector)

### Purpose
Retrieves visuals from free/legal-friendly sources, ranks candidates, deduplicates URLs, and caches local assets.

### Provider strategy
- Keyless providers: Iconify, Openverse
- Optional-key providers: Pexels, Unsplash

### Inputs
- scene keywords
- visual type
- topic context

### Outputs
- ranked asset list with provider metadata and local cache paths when downloaded

### Dependencies
- `httpx` for provider APIs
- provider keys from environment when available
- local file/cache operations

### Why it matters
This is the main legal-safe media retrieval layer used by storyboard/visual intelligence.

---

## 3.10 `LayoutEngine_Agent`

### Purpose
Builds screen layout instructions from scene text + selected assets.

### Outputs
- layout blocks and placement information consumed by rendering pipeline

### Why it matters
Bridges raw assets and final composited frame structure.

---

## 3.11 `VisualIntelligenceLayer_Agent`

### Purpose
Performs transcript-driven semantic visual planning.

### Main functions
- fallback keyword extraction
- semantic extraction (LLM-first, heuristic fallback)
- meaning-aware chunking
- intent-to-visual query construction
- asset ranking and fallback selection

### Inputs
- transcript text
- optional topic

### Outputs
- chunked visual plan entries containing keywords, intent, visual type, queries, and assets

### Dependencies
- `AssetFetcher_Agent`
- optional `openai_llm`

### Why it matters
Improves semantic alignment between narration and visual search compared to pure token frequency.

---

## 3.12 `SceneDirector_Agent`

### Purpose
Enhances scene metadata into director-style storytelling instructions without changing narration text.

### Adds per scene
- `visual_type`
- `background_query`
- `overlay_elements`
- `composition`
- `animation`
- `emphasis_level`
- `variation_strategy`
- `reasoning`

### Modes
- LLM-enhanced structured JSON path
- deterministic fallback path

### Why it matters
Raises visual quality and scene variety beyond basic storyboard metadata.

---

## 3.13 `StoryboardComposer_Agent`

### Purpose
Orchestrates scene planning, asset retrieval, layout generation, and director enhancement into one structured storyboard JSON.

### Internal orchestration
1. plan scenes (`SceneplannerAgent`)
2. apply duration budget cap
3. enrich sparse scene keywords/type (`VisualIntelligenceLayer_Agent`)
4. fetch assets (`AssetFetcher_Agent`)
5. apply layout (`LayoutEngine_Agent`)
6. enhance full scene list (`SceneDirector_Agent`)

### Why it matters
This is the central visual orchestration engine before rendering.

---

## 3.14 `VideoGenerationAgent`

### Purpose
Renders final media outputs from script/storyboard:
- frame composition
- animation/motion assembly
- narration/audio composition
- mp4 export

### Dependencies
- `moviepy`
- image/audio libs (`pillow`, etc.)
- `VoiceProcessingAgent` for narration audio

---

## 3.15 `Logger_Agent`

### Purpose
Session-scoped structured logging for UI tailing and pipeline diagnostics.

### Why it matters
Powers `/log_tail/{session}` and helps detect agent-step failures quickly.

---

## 4. Dependency matrix (high-level)

- LLM reasoning: `openai`
- STT: `openai-whisper`, `torch`, `numpy`
- TTS: `elevenlabs`
- API server: `fastapi`, `uvicorn`, `python-multipart`
- Memory: `chromadb`
- Media retrieval: `httpx`
- Video rendering: `moviepy`, `pillow`, audio/image stack
- Config/runtime: `python-dotenv`

---

## 5. Failure handling model

- Missing provider keys: optional providers are skipped gracefully.
- Asset fetch misses: fallback assets are returned.
- LLM parse failures in visual agents: deterministic fallback paths run.
- Voice/TTS failures: logged and surfaced via API errors.
- Route-level exceptions: wrapped into JSON error responses with log URLs.

---

## 6. How agents work together “in practice”

Example request (`POST /teach`):
1. User asks: “Explain cybersecurity certifications for beginners.”
2. Discovery tiers topics.
3. Simplification creates sequence (why certs, path, prep strategy).
4. Teaching drafts full lesson blocks.
5. Transcript agent generates one continuous script for target minutes.
6. Storyboard composer slices script into scenes, enriches semantics, fetches assets, applies layouts, and applies scene direction enhancement.
7. Video generation renders animation + audio output.
8. Context saves everything for follow-up clarifications.

Result: user receives playable video URL, transcript, logs, and a stateful session that supports Q&A.

---

## 7. Operational tips

- If visuals are weak, inspect `/visual-intelligence` output for queries/intent.
- If rendering fails, inspect session logs via `/log_tail` + output log file.
- Keep environment keys configured for best asset diversity and narration quality.
- For deterministic debugging, run with fallback paths and compare outputs.

---

## 8. Related docs

- `README.md` (quickstart + endpoint summary)
- `Docs/Complete_App_Guide.md` (product-level architecture)
- `UPGRADE_NOTES.md` (dependency/runtime upgrade notes)
