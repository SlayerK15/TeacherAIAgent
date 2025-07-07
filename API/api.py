from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from Agents.Discovery_Agent import DiscoveryAgent
from Agents.Simplification_Agent import SimplificationAgent
from Agents.Teaching_Agent import TeachingAgent
from Agents.Engagement_Agent import EngagementAgent
from Agents.Clarification_Agent import ClarificationAgent
from Agents.ContextMemory_Agent import ContextMemoryAgent
from Agents.VoiceProcessing_Agent import VoiceProcessingAgent
import openai
import os
import shutil
import json

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
engagement_agent = EngagementAgent(llm_fn=openai_llm)
clarification_agent = ClarificationAgent(llm_fn=openai_llm)
context_memory = ContextMemoryAgent()

app = FastAPI()

# ------------- ENABLE CORS FOR ALL ORIGINS (for dev) -------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # <-- Allow all for local dev, restrict for prod!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/teach")
async def teach(
    user_prompt: str = Form(None),
    audio: UploadFile = File(None),
    session_id: str = Form("default")
):
    if user_prompt:
        context_memory.save(f'{session_id}_user_input', user_prompt)
        topic_tiers = discovery_agent.run(user_prompt, input_type="text")
    elif audio:
        temp_path = f"temp_{audio.filename}"
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
    engaged_lessons = engagement_agent.run(lessons)
    context_memory.save(f'{session_id}_engaged_lessons', engaged_lessons)

    return {
        "session_id": session_id,
        "topic_tiers": topic_tiers,
        "simplified_steps": simplified,
        "lessons": lessons,
        "engaged_lessons": engaged_lessons
    }

@app.post("/clarify")
async def clarify(
    user_question: str = Form(...),
    topic: str = Form(...),
    session_id: str = Form("default")
):
    lessons = context_memory.get(f'{session_id}_lessons')
    engaged_lessons = context_memory.get(f'{session_id}_engaged_lessons')

    # Only decode if lessons is a string, otherwise leave as dict
    if isinstance(lessons, str):
        try:
            lessons = json.loads(lessons)
        except Exception as e:
            print("JSON decode error for lessons:", e)
            lessons = {}
    if isinstance(engaged_lessons, str):
        try:
            engaged_lessons = json.loads(engaged_lessons)
        except Exception as e:
            print("JSON decode error for engaged_lessons:", e)
            engaged_lessons = {}

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
        lesson=lessons.get(topic, ""),
        engaged_lesson=engaged_lessons.get(topic, ""),
        context=context
    )
    context_memory.append_to_list(f'{session_id}_clarifications', {'q': user_question, 'a': answer})
    return {"answer": answer}


@app.get("/")
def root():
    return {"status": "AI Teacher Agent API running!"}
