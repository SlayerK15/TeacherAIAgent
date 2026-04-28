import json
from Agents.Logger_Agent import get_current

# Real-world TTS pace measured from logs: OpenAI tts-1 reads ~200 wpm and
# ElevenLabs ~175 wpm. We target the faster of the two so the transcript has
# enough words to fill the requested duration regardless of which engine runs,
# plus a 15% buffer to absorb LLM word-count undershoot.
WORDS_PER_MINUTE = 200
TARGET_OVERSHOOT = 1.15

class EngagingVideoTranscriptGeneratorAgent:
    """
    Generates a long, engaging video narration script for the requested duration.
    """

    def __init__(self, llm_fn, default_minutes=8, transition_phrase="\n\nNow, let's move on to our next topic!\n\n"):
        self.llm_fn = llm_fn
        self.default_minutes = default_minutes
        self.transition_phrase = transition_phrase

    def run_full(self, lesson_content, total_minutes: float, extra_context=None):
        """
        lesson_content: dict of topic -> outline/lesson text
        total_minutes: float, user requested length (e.g., 10 for 10 min)
        """
        target_words = int(total_minutes * WORDS_PER_MINUTE)
        # Ask the LLM for ~15% more than we strictly need; LLMs reliably
        # undershoot stated word counts, so this lands closer to target.
        prompt_target_words = int(target_words * TARGET_OVERSHOOT)
        all_topics = list(lesson_content.keys())
        # For the outline, include only first 120 chars for each topic to keep prompt short
        outline = "\n".join(f"{topic}: {lesson_content[topic][:120]}" for topic in all_topics)
        prompt = (
            "You are an expert teacher and storyteller creating a script for a highly engaging educational YouTube video.\n"
            f"Your task: Write a single, flowing, classroom-style narration covering ALL these topics, "
            f"with engaging transitions and no abrupt jumps. The entire script must run at least "
            f"{total_minutes} minutes when read aloud at a natural pace. Aim for {prompt_target_words} words. "
            "Going over is fine — the script will be trimmed. Going under is NOT acceptable.\n"
            "Make sure to cover each topic in a balanced way and make it beginner-friendly.\n\n"
            f"Topics to cover:\n{', '.join(all_topics)}\n"
            f"Outline/Notes per topic:\n{outline}\n"
        )
        if extra_context:
            prompt += f"\nExtra audience/context info: {extra_context}\n"
        prompt += (
            "\nInstructions:\n"
            "- Write as one continuous, natural narration (no headings or bullet points).\n"
            "- Include stories, analogies, fun facts, examples, and inviting transitions.\n"
            "- Expand on each topic deeply — do NOT summarize or rush.\n"
            "- End with an energetic summary and encouragement to keep learning.\n"
            f"- Hard requirement: produce at least {prompt_target_words} words. "
            f"Keep writing until you reach this. Do not stop early.\n"
        )

        log = get_current()
        script = self.llm_fn(prompt)
        words = script.split()
        if log: log.info("TranscriptAgent.run_full",
                         target_words=target_words,
                         prompt_target=prompt_target_words,
                         actual_words=len(words))

        # If the LLM still undershot, ask it to extend rather than ship a short video.
        if len(words) < target_words:
            shortfall = target_words - len(words)
            extend_prompt = (
                f"You wrote a {len(words)}-word script but it's about {shortfall} words too short "
                f"to fill the {total_minutes}-minute video. Continue the narration below — add more "
                "examples, deeper explanations, and analogies for the topics already covered. Do NOT "
                "repeat what's already there. Do NOT add a new ending. Just produce the additional "
                f"~{shortfall + 80} words that pick up where this leaves off:\n\n{script}"
            )
            try:
                extra = self.llm_fn(extend_prompt)
                script = (script.rstrip() + "\n\n" + extra.strip()).strip()
                words = script.split()
                if log: log.info("TranscriptAgent extended", new_word_count=len(words))
            except Exception as e:
                if log: log.warn("TranscriptAgent extend failed", error=str(e))

        # Trim only if we're meaningfully over the strict target (10% buffer).
        max_words = int(target_words * 1.10)
        if len(words) > max_words:
            trimmed = " ".join(words[:max_words])
            last_period = trimmed.rfind('.')
            if last_period > 0:
                script = trimmed[:last_period+1]
            else:
                script = trimmed + "..."
        return script.strip()

    def run(self, lesson_content, extra_context=None, min_minutes_per_topic=None):
        """
        Legacy: Generates a script per topic, each of at least min_minutes_per_topic.
        Used only if you want per-topic segments.
        """
        if min_minutes_per_topic is not None:
            minutes = float(min_minutes_per_topic)
        else:
            minutes = float(self.default_minutes)

        log = get_current()
        # If input is a dict (topic: lesson_text), generate detailed script per topic
        if isinstance(lesson_content, dict):
            if log: log.info("TranscriptAgent.run dict",
                             topic_count=len(lesson_content), minutes_per_topic=minutes)
            parts = []
            for idx, (topic, lesson) in enumerate(lesson_content.items()):
                lesson_text = lesson if isinstance(lesson, str) else json.dumps(lesson, indent=2)
                topic_prompt = (
                    f"You are an expert teacher and storyteller creating a script for a highly engaging educational YouTube video.\n"
                    f"Write a detailed, classroom-style narration about the following topic, "
                    f"so that when spoken aloud at a normal pace, it would take at least {minutes} minutes.\n"
                    "Requirements for the narration:\n"
                    "- Be friendly, conversational, and encouraging.\n"
                    "- Use vivid examples, analogies, stories, and ask the viewer to imagine or reflect.\n"
                    "- Sprinkle in fun facts, mini-quizzes, and relatable side notes.\n"
                    "- Never summarize or rush. Go deep on explanations and examples.\n"
                    "- No bullet points, no headings—write as one continuous, natural narration.\n"
                    "- Recap or encourage at key transitions, end each topic with energy and an invitation to keep learning.\n"
                )
                if extra_context:
                    topic_prompt += f"\nExtra audience/context info: {extra_context}\n"

                topic_prompt += (
                    f"\nTopic: {topic}\n\nLesson Outline or Notes:\n{lesson_text}\n\n"
                    f"Write the full, detailed script for this topic now (aim for {minutes * WORDS_PER_MINUTE} words or more):\n"
                )

                if log: log.step_start(f"TranscriptAgent.topic[{idx}]", topic=topic, prompt_len=len(topic_prompt))
                script_part = self.llm_fn(topic_prompt)
                if log: log.step_end(f"TranscriptAgent.topic[{idx}]", topic=topic, script_chars=len(script_part))
                parts.append(script_part.strip())

            # Seamlessly join all scripts for a "full video" transcript
            full_script = self.transition_phrase.join(parts)
            if log: log.info("TranscriptAgent done", total_chars=len(full_script), parts=len(parts))
            return full_script
        else:
            # If input is a string, just call the LLM as before
            prompt = (
                "You are an expert teacher and storyteller creating a script for an engaging educational YouTube video. "
                "Your goal is to captivate the viewer and keep them curious from start to finish.\n\n"
                "Requirements for the video script:\n"
                "- Start with an attention-grabbing question, surprising fact, or short story.\n"
                "- Use a friendly, conversational 'you' and 'we' style throughout.\n"
                "- Explain concepts with vivid analogies, stories, or examples.\n"
                "- Ask rhetorical questions and invite the viewer to pause, imagine, or guess what comes next.\n"
                "- Sprinkle in several surprising facts, funny asides, or relatable mini-stories.\n"
                "- Use light humor or encouraging comments when appropriate (e.g., 'Great job sticking with me!').\n"
                "- Avoid all section headings, bullet points, and lists; the script must flow naturally as spoken narration.\n"
                "- Recap or encourage at key transitions (e.g., 'Nice work so far! Ready for the next challenge?').\n"
                "- End with an energetic summary and a call to learn more or reflect on what was covered.\n"
            )
            if extra_context:
                prompt += f"\nExtra audience/context info: {extra_context}\n"

            minutes = min_minutes_per_topic or self.default_minutes
            prompt += (
                "\nHere are the lesson points, concepts, and examples to cover (put these into the script naturally):\n"
                f"{lesson_content}\n"
                f"\nWrite the full, engaging video narration script now (aim for {minutes * WORDS_PER_MINUTE} words or more):\n"
            )
            return self.llm_fn(prompt)
