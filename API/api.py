from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
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

import openai
import os
import shutil
import json
import glob
import re
import datetime

openai.api_key = os.getenv("OPENAI_API_KEY") or "API_Key"

def openai_llm(prompt: str, model: str = "gpt-4o", temperature: float = 0.4) -> str:
    response = openai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful AI teaching assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=temperature,
        max_tokens=1200
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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/output", StaticFiles(directory="output"), name="output")

def slugify(text, maxlen=32):
    text = re.sub(r'\W+', '_', text)
    return text[:maxlen]

@app.post("/teach")
async def teach(
    user_prompt: str = Form(None),
    audio: UploadFile = File(None),
    session_id: str = Form("default"),
    video_minutes: float = Form(8)    # <-- default 8 min for backward compatibility
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

    # Agents run
    if user_prompt:
        context_memory.save(f'{session_id}_user_input', user_prompt)
        topic_tiers = discovery_agent.run(user_prompt, input_type="text")
    elif audio:
        temp_path = os.path.join(audio_dir, f"temp_{audio.filename}")
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        context_memory.save(f'{session_id}_user_input', temp_path)
        topic_tiers = discovery_agent.run(temp_path, input_type="audio")
        os.remove(temp_path)
    else:
        return JSONResponse({"error": "Provide user_prompt or audio"}, status_code=400)
    
    context_memory.save(f'{session_id}_topic_tiers', topic_tiers)
    simplified = simplify_agent.run(topic_tiers)
    context_memory.save(f'{session_id}_simplified_steps', simplified)
    lessons = teaching_agent.run(simplified)
    context_memory.save(f'{session_id}_lessons', lessons)

    # PATCHED LOGIC: Compute per-topic minutes based on total video_minutes desired
    topics_for_script = list(lessons.keys())
    num_topics = max(len(topics_for_script), 1)
    per_topic_minutes = max(float(video_minutes) / num_topics, 1)  # at least 1 min per topic

    video_script = transcript_agent.run(lessons, min_minutes_per_topic=per_topic_minutes)
    context_memory.save(f'{session_id}_video_script', video_script)

    # Directly save all generated files into correct session-specific folders
    video_path = video_generation_agent.run(
        video_script,
        frames_dir=frames_dir,
        audio_dir=audio_dir,
        video_dir=video_dir,
        max_total_duration=float(video_minutes) * 60  # convert min to sec
    )


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

    return {
        "session_id": session_id,
        "topic_tiers": topic_tiers,
        "simplified_steps": simplified,
        "lessons": lessons,
        "video_script": video_script,
        "video_url": video_url,
        "frames_folder": f"/output/frames/{session_name}/",
        "audio_folder": f"/output/audio/{session_name}/",
        "responce_txt_url": f"/output/response/{session_name}.txt"
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

@app.get("/")
def root():
    return {"status": "AI Teacher Agent API running!"}
