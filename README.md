# TeacherAIAgent

TeacherAIAgent is an AI-powered teaching assistant platform that helps break down complex topics, generate structured lessons, answer clarifying questions, and even process voice input. It leverages large language models (LLMs) and modular agents to deliver a personalized, interactive learning experience.

## Features

- **Topic Discovery:** Breaks down user prompts into structured learning objectives (tiers).
- **Simplification:** Simplifies complex topics into step-by-step learning paths.
- **Lesson Generation:** Creates detailed lessons for each learning step.
- **Engagement:** Enhances lessons with analogies, examples, and interactive elements.
- **Clarification:** Answers follow-up questions and provides further explanations.
- **Voice Input:** Accepts both text and audio (speech-to-text) prompts.
- **Session Memory:** Remembers user sessions and context for continuity.
- **REST API:** FastAPI-based backend for easy integration.

## Folder Structure

```
Agents/           # Core agent modules (Discovery, Teaching, VoiceProcessing, etc.)
API/              # FastAPI backend
Dashboard/        # (Optional) Frontend dashboard
Docs/             # Documentation and checklists
output/           # Generated audio, video, and response files
requirements.txt  # Python dependencies
main.py           # (Entry point, if used)
```

## Setup

1. **Clone the repository:**
   ```sh
   git clone https://github.com/SlayerK15/TeacherAIAgent.git
   cd TeacherAIAgent
   ```
2. **Create and activate a virtual environment:**
   ```sh
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Unix/Mac:
   source venv/bin/activate
   ```
3. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
4. **Set your OpenAI API key:**
   - Create a `.env` file or set the `OPENAI_API_KEY` environment variable.

5. **Run the API server:**
   ```sh
   uvicorn API.api:app --reload
   ```

## Usage

### Teach Endpoint
- **POST** `/teach`
- Accepts: `user_prompt` (text) or `audio` (file)
- Returns: Topic tiers, simplified steps, lessons, and engaged lessons

Example (using `curl`):
```sh
curl -X POST "http://localhost:8000/teach" -F "user_prompt=Explain quantum computing"
```

### Clarify Endpoint
- **POST** `/clarify`
- Accepts: `user_question`, `topic`, `session_id`
- Returns: Clarification/answer

Example:
```sh
curl -X POST "http://localhost:8000/clarify" -F "user_question=What is a qubit?" -F "topic=Quantum Computing"
```

## Agents Overview
- **DiscoveryAgent:** Breaks down prompts into learning tiers (main, supporting, background topics).
- **SimplificationAgent:** Simplifies topics into actionable steps.
- **TeachingAgent:** Generates lessons for each step.
- **EngagementAgent:** Adds engagement (examples, analogies).
- **ClarificationAgent:** Answers follow-up questions.
- **VoiceProcessingAgent:** Converts speech (audio) to text.
- **ContextMemoryAgent:** Stores and retrieves session data.

## Audio Input
- Send an audio file (e.g., `.wav`, `.mp3`) to `/teach` as the `audio` field.
- The system will transcribe and process it as a prompt.

## Output
- Generated audio, video, and response files are saved in the `output/` directory.

## Development
- All agents are modular and can be extended or replaced.
- See `Docs/` for checklists and POC notes.

## License
This project is for educational and research purposes. See `LICENSE` for details.

## Acknowledgments
- Powered by OpenAI GPT models
- Built with FastAPI
