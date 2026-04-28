from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from Agents.Discovery_Agent import DiscoveryAgent
from Agents.Simplification_Agent import SimplificationAgent
from Agents.Teaching_Agent import TeachingAgent
from Agents.TranscriptGenerator_Agent import EngagingVideoTranscriptGeneratorAgent
from Agents.Clarification_Agent import ClarificationAgent
from Agents.ContextMemory_Agent import ContextMemoryAgent
from Agents.VoiceProcessing_Agent import VoiceProcessingAgent
from Agents.VideoGenerationAgent import VideoGenerationAgent
from Agents.StoryboardComposer_Agent import StoryboardComposer_Agent
from Agents.Logger_Agent import LoggerAgent, set_current

import openai
import os
import shutil
import json
import glob
import re
import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

def openai_llm(prompt: str, model: str = "gpt-4o", temperature: float = 0.4,
               max_tokens: int = 4000) -> str:
    # max_tokens=4000 (~3000 words) lets the transcript agent actually hit the
    # word count it asks for. The previous 1200 cap was the root cause of short
    # videos: an 8-min target needed 1400 words but the LLM could only emit ~900.
    response = openai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful AI teaching assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=temperature,
        max_tokens=max_tokens
    )
    content = None
    if hasattr(response, "choices"):
        content = getattr(response.choices[0].message, "content", None)
    if not content and isinstance(response, dict):
        try:
            content = response['choices'][0]['message']['content']
        except Exception:
            pass
    if not content:
        raise RuntimeError(f"No content returned from OpenAI API. Raw: {response}")
    return content.strip()

voice_agent = VoiceProcessingAgent(stt_model_size="base")
discovery_agent = DiscoveryAgent(llm_fn=openai_llm, voice_agent=voice_agent)
simplify_agent = SimplificationAgent(llm_fn=openai_llm)
teaching_agent = TeachingAgent(llm_fn=openai_llm)
transcript_agent = EngagingVideoTranscriptGeneratorAgent(openai_llm)
clarification_agent = ClarificationAgent(llm_fn=openai_llm)
context_memory = ContextMemoryAgent()
video_generation_agent = VideoGenerationAgent(voice_agent)
storyboard_composer = StoryboardComposer_Agent(llm_fn=openai_llm)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/output", StaticFiles(directory="output"), name="output")

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Dashboard")
DASHBOARD_HTML = os.path.join(DASHBOARD_DIR, "dashboard.html")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR), name="dashboard")

def slugify(text, maxlen=32):
    text = re.sub(r'\W+', '_', text)
    return text[:maxlen]

@app.post("/teach")
async def teach(
    user_prompt: str = Form(None),
    audio: UploadFile = File(None),
    session_id: str = Form("default"),
    video_minutes: float = Form(8),    # <-- default 8 min for backward compatibility
    animated: bool = Form(True),       # storyboard mode fetches illustrations
    silent: bool = Form(False),
):
    # Generate timestamp and slug
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if user_prompt:
        slug = slugify(user_prompt)
    elif audio:
        slug = slugify(audio.filename)
    else:
        slug = "unknown"
    session_name = f"{now_str}__{slug}"

    # Output directories for THIS session
    frames_dir = os.path.join("output", "frames", session_name)
    audio_dir = os.path.join("output", "audio", session_name)
    video_dir = os.path.join("output", "video", session_name)
    response_dir = os.path.join("output", "response")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(response_dir, exist_ok=True)

    log = LoggerAgent(session_id=session_name)
    set_current(log)
    log.info("teach request received", prompt=user_prompt, video_minutes=video_minutes,
             has_audio=bool(audio), animated=animated, silent=silent)

    try:
        return await _run_teach_pipeline(
            user_prompt, audio, session_id, video_minutes, session_name,
            frames_dir, audio_dir, video_dir, response_dir, log,
            animated=animated, silent=silent,
        )
    except Exception as e:
        log.error("teach pipeline failed", exc_info=True, error=str(e))
        return JSONResponse(
            {"error": str(e), "session_name": session_name,
             "log_url": f"/output/logs/{session_name}.log"},
            status_code=500,
        )


async def _run_teach_pipeline(user_prompt, audio, session_id, video_minutes, session_name,
                              frames_dir, audio_dir, video_dir, response_dir, log,
                              animated: bool = False, silent: bool = False):
    # Agents run
    if user_prompt:
        context_memory.save(f'{session_id}_user_input', user_prompt)
        log.step_start("DiscoveryAgent", input_type="text")
        topic_tiers = discovery_agent.run(user_prompt, input_type="text")
        log.step_end("DiscoveryAgent", topics=list(topic_tiers.keys()) if isinstance(topic_tiers, dict) else None)
    elif audio:
        temp_path = os.path.join(audio_dir, f"temp_{audio.filename}")
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        context_memory.save(f'{session_id}_user_input', temp_path)
        log.step_start("DiscoveryAgent", input_type="audio")
        topic_tiers = discovery_agent.run(temp_path, input_type="audio")
        log.step_end("DiscoveryAgent")
        os.remove(temp_path)
    else:
        return JSONResponse({"error": "Provide user_prompt or audio"}, status_code=400)

    context_memory.save(f'{session_id}_topic_tiers', topic_tiers)
    log.step_start("SimplificationAgent")
    simplified = simplify_agent.run(topic_tiers)
    log.step_end("SimplificationAgent", topic_count=len(simplified) if hasattr(simplified, "__len__") else None)
    context_memory.save(f'{session_id}_simplified_steps', simplified)
    log.step_start("TeachingAgent")
    lessons = teaching_agent.run(simplified)
    log.step_end("TeachingAgent", lesson_count=len(lessons) if hasattr(lessons, "__len__") else None)
    context_memory.save(f'{session_id}_lessons', lessons)

    # Cap topics to ~1 per minute so short videos go deep on a few rather than skim many.
    max_topics = max(int(round(float(video_minutes))), 1)
    if isinstance(lessons, dict) and len(lessons) > max_topics:
        lessons_for_script = dict(list(lessons.items())[:max_topics])
        log.info("TranscriptAgent topic cap applied",
                 total=len(lessons), kept=len(lessons_for_script), max_topics=max_topics)
    else:
        lessons_for_script = lessons

    # ONE flowing script for the full duration — no per-topic greeting/signoff cuts
    log.step_start("TranscriptAgent", total_minutes=float(video_minutes),
                   num_topics=len(lessons_for_script))
    video_script = transcript_agent.run_full(lessons_for_script,
                                             total_minutes=float(video_minutes))
    log.step_end("TranscriptAgent", script_chars=len(video_script) if isinstance(video_script, str) else None)
    context_memory.save(f'{session_id}_video_script', video_script)

    # Directly save all generated files into correct session-specific folders
    log.step_start("VideoGeneration",
                   max_total_duration_s=float(video_minutes) * 60,
                   animated=animated, silent=silent)
    if animated:
        video_path = video_generation_agent.run_storyboard(
            video_script,
            storyboard_composer=storyboard_composer,
            frames_dir=frames_dir,
            audio_dir=audio_dir,
            video_dir=video_dir,
            max_total_duration=float(video_minutes) * 60,
            silent=silent,
            topic=user_prompt or "",
        )
    else:
        video_path = video_generation_agent.run(
            video_script,
            frames_dir=frames_dir,
            audio_dir=audio_dir,
            video_dir=video_dir,
            max_total_duration=float(video_minutes) * 60  # convert min to sec
        )
    log.step_end("VideoGeneration", video_path=str(video_path))


    # No need to move files after this point!
    # Instead, directly reference files in their session folders
    video_files = glob.glob(os.path.join(video_dir, "*.mp4"))
    video_url = f"/output/video/{session_name}/{os.path.basename(video_files[0])}" if video_files else ""

    # Save response as output/response/{session_name}.txt
    response_path = os.path.join(response_dir, f"{session_name}.txt")
    with open(response_path, "w", encoding="utf-8") as f:
        f.write("User Input:\n")
        f.write((user_prompt or "") + "\n\n")
        f.write("Topic Tiers (DiscoveryAgent):\n")
        f.write(json.dumps(topic_tiers, indent=2) + "\n\n")
        f.write("Simplified Steps (SimplificationAgent):\n")
        f.write(json.dumps(simplified, indent=2) + "\n\n")
        f.write("Lessons (TeachingAgent):\n")
        f.write(json.dumps(lessons, indent=2) + "\n\n")
        f.write("Video Script (EngagingVideoTranscriptGeneratorAgent):\n")
        f.write(video_script + "\n\n")
        f.write(f"Video Path: {video_url}\n")

    log.info("teach request done", video_url=video_url, response_path=response_path)
    return {
        "session_id": session_id,
        "topic_tiers": topic_tiers,
        "simplified_steps": simplified,
        "lessons": lessons,
        "video_script": video_script,
        "video_url": video_url,
        "frames_folder": f"/output/frames/{session_name}/",
        "audio_folder": f"/output/audio/{session_name}/",
        "responce_txt_url": f"/output/response/{session_name}.txt",
        "log_url": f"/output/logs/{session_name}.log",
    }


@app.post("/clarify")
async def clarify(
    user_question: str = Form(...),
    topic: str = Form(...),
    session_id: str = Form("default")
):
    lessons = context_memory.get(f'{session_id}_lessons')
    video_script = context_memory.get(f'{session_id}_video_script')

    if isinstance(lessons, str):
        try:
            lessons = json.loads(lessons)
        except Exception as e:
            print("JSON decode error for lessons:", e)
            lessons = {}

    clarifications = context_memory.get(f'{session_id}_clarifications', '[]')
    if isinstance(clarifications, str):
        try:
            clarifications = json.loads(clarifications)
        except Exception as e:
            print("JSON decode error for clarifications:", e)
            clarifications = []

    context = {
        "topic_tiers": context_memory.get(f'{session_id}_topic_tiers'),
        "simplified_steps": context_memory.get(f'{session_id}_simplified_steps'),
        "clarifications": clarifications
    }
    answer = clarification_agent.run(
        user_question=user_question,
        lesson=lessons.get(topic, "") if isinstance(lessons, dict) else "",
        engaged_lesson="",  # Not used in new flow
        context=context
    )
    context_memory.append_to_list(f'{session_id}_clarifications', {'q': user_question, 'a': answer})
    return {"answer": answer}

@app.post("/storyboard")
async def storyboard(
    transcript: str = Form(None),
    user_prompt: str = Form(None),
    video_minutes: float = Form(None),
):
    """
    Build a structured storyboard (scenes + assets + layout + timing).

    Either pass a ready-made transcript, or pass user_prompt to run the
    full discovery -> simplification -> teaching -> transcript pipeline.
    """
    if not transcript and not user_prompt:
        return JSONResponse(
            {"error": "Provide either 'transcript' or 'user_prompt'."},
            status_code=400,
        )

    if not transcript:
        topic_tiers = discovery_agent.run(user_prompt, input_type="text")
        simplified = simplify_agent.run(topic_tiers)
        lessons = teaching_agent.run(simplified)
        per_topic_minutes = max(float(video_minutes or 4) / max(len(lessons), 1), 1)
        transcript = transcript_agent.run(lessons, min_minutes_per_topic=per_topic_minutes)

    max_seconds = float(video_minutes) * 60 if video_minutes else None
    storyboard_json = storyboard_composer.run(transcript, max_total_duration=max_seconds)
    return storyboard_json


@app.get("/")
def root():
    if os.path.exists(DASHBOARD_HTML):
        return FileResponse(DASHBOARD_HTML)
    return {"status": "AI Teacher Agent API running!", "dashboard": "missing"}


@app.get("/api/health")
def health():
    return {"status": "AI Teacher Agent API running!"}


@app.get("/log_tail/{session_name}")
def log_tail(session_name: str, after: int = 0):
    """Return jsonl log lines after byte offset `after`. Polled by frontend."""
    safe = re.sub(r"[^A-Za-z0-9_\-\.]", "", session_name)
    path = os.path.join("output", "logs", f"{safe}.jsonl")
    if not os.path.exists(path):
        return {"lines": [], "next_offset": 0, "exists": False}
    size = os.path.getsize(path)
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        f.seek(min(after, size))
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                lines.append(json.loads(raw))
            except Exception:
                lines.append({"raw": raw})
    return {"lines": lines, "next_offset": size, "exists": True}


@app.get("/sessions")
def list_sessions(limit: int = 30):
    log_dir = os.path.join("output", "logs")
    if not os.path.isdir(log_dir):
        return {"sessions": []}
    files = sorted(glob.glob(os.path.join(log_dir, "*.jsonl")), reverse=True)[:limit]
    return {"sessions": [os.path.splitext(os.path.basename(f))[0] for f in files]}
