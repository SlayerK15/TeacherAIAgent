import os
from Agents.Discovery_Agent import DiscoveryAgent
from Agents.Simplification_Agent import SimplificationAgent
from Agents.Teaching_Agent import TeachingAgent
from Agents.Engagement_Agent import EngagementAgent
from Agents.Clarification_Agent import ClarificationAgent
from Agents.ContextMemory_Agent import ContextMemoryAgent
from Agents.VoiceProcessing_Agent import VoiceProcessingAgent
import openai
import json


openai.api_key = os.getenv("OPENAI_API_KEY") or "sk-..."

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
    return response.choices[0].message.content.strip()

# Instantiate agents
voice_agent = VoiceProcessingAgent(stt_model_size="base")
discovery_agent = DiscoveryAgent(llm_fn=openai_llm, voice_agent=voice_agent)
simplify_agent = SimplificationAgent(llm_fn=openai_llm)
teaching_agent = TeachingAgent(llm_fn=openai_llm)
engagement_agent = EngagementAgent(llm_fn=openai_llm)
clarification_agent = ClarificationAgent(llm_fn=openai_llm)
context_memory = ContextMemoryAgent()

def main():
    print("AI Teacher (Full Pipeline with Context Memory)")

    input_mode = input("Choose input mode: 1=Text, 2=Audio file: ").strip()

    if input_mode == "1":
        user_prompt = input("Enter your learning question or topic: ")
    elif input_mode == "2":
        audio_path = input("Enter audio file path (wav/mp3): ").strip()
        if not os.path.exists(audio_path):
            print("File does not exist.")
            return
        user_prompt = audio_path
    else:
        print("Invalid selection.")
        return

    context_memory.save('user_input', user_prompt)

    # Discovery
    if input_mode == "1":
        topic_tiers = discovery_agent.run(user_prompt, input_type="text")
    else:
        topic_tiers = discovery_agent.run(user_prompt, input_type="audio")
    print("\n--- DISCOVERY AGENT TOPIC TIERS ---")
    for tier, topics in topic_tiers.items():
        print(f"{tier}: {topics}")
    context_memory.save('topic_tiers', topic_tiers)

    # Simplification
    simplified = simplify_agent.run(topic_tiers)
    print("\n--- SIMPLIFICATION AGENT TEACHING STEPS ---")
    for topic, steps in simplified.items():
        print(f"\n{topic}:")
        for idx, step in enumerate(steps, 1):
            print(f"  {idx}. {step}")
    context_memory.save('simplified_steps', simplified)

    # Teaching
    lessons = teaching_agent.run(simplified)
    print("\n--- TEACHING AGENT LESSONS ---")
    for topic, lesson in lessons.items():
        print(f"\n--- Lesson: {topic} ---\n{lesson}\n")
    context_memory.save('lessons', lessons)

    # Engagement
    engaged_lessons = engagement_agent.run(lessons)
    print("\n--- ENGAGEMENT AGENT (ENHANCED LESSONS) ---")
    for topic, engaged in engaged_lessons.items():
        print(f"\n--- Engaged Lesson: {topic} ---\n{engaged}\n")
    context_memory.save('engaged_lessons', engaged_lessons)

    # Clarification step (with context memory)
    follow_up = input("\nDo you have a follow-up question about any topic? (Press Enter to skip): ")
    if follow_up.strip():
        # For now, default to the first topic
        topic = list(engaged_lessons.keys())[0]
        answer = clarification_agent.run(
            user_question=follow_up,
            lesson=lessons[topic],
            engaged_lesson=engaged_lessons[topic],
            context={
                "topic_tiers": context_memory.get('topic_tiers'),
                "simplified_steps": context_memory.get('simplified_steps'),
                "clarifications": context_memory.get('clarifications', [])
            }
        )
        print(f"\n--- Clarification/Answer ---\n{answer}\n")
        context_memory.append_to_list('clarifications', {'q': follow_up, 'a': answer})

    # For demonstration, you can print the full context memory
    # print("\n--- FULL CONTEXT MEMORY ---")
    # print(context_memory.memory)

if __name__ == "__main__":
    main()
