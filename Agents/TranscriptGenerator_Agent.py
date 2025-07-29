import json

WORDS_PER_MINUTE = 140

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
        all_topics = list(lesson_content.keys())
        # For the outline, include only first 120 chars for each topic to keep prompt short
        outline = "\n".join(f"{topic}: {lesson_content[topic][:120]}" for topic in all_topics)
        prompt = (
            "You are an expert teacher and storyteller creating a script for a highly engaging educational YouTube video.\n"
            f"Your task: Write a single, flowing, classroom-style narration covering ALL these topics, "
            f"with engaging transitions and no abrupt jumps. The entire script should take about {total_minutes} minutes to read aloud (aim for ~{target_words} words, DO NOT exceed this length). "
            "Make sure to cover each topic in a balanced way and make it beginner-friendly.\n\n"
            f"Topics to cover:\n{', '.join(all_topics)}\n"
            f"Outline/Notes per topic:\n{outline}\n"
        )
        if extra_context:
            prompt += f"\nExtra audience/context info: {extra_context}\n"
        prompt += (
            "\nInstructions:\n"
            "- Write as one continuous, natural narration (no headings or bullet points).\n"
            "- Include stories, analogies, fun facts, and inviting transitions.\n"
            "- End with an energetic summary and encouragement to keep learning.\n"
            f"- Write the script now (MAX {target_words} words):\n"
        )

        script = self.llm_fn(prompt)
        # Trim result to target_words, end at last full sentence
        words = script.split()
        if len(words) > target_words:
            trimmed = " ".join(words[:target_words])
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

        # If input is a dict (topic: lesson_text), generate detailed script per topic
        if isinstance(lesson_content, dict):
            parts = []
            for topic, lesson in lesson_content.items():
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

                script_part = self.llm_fn(topic_prompt)
                parts.append(script_part.strip())

            # Seamlessly join all scripts for a "full video" transcript
            full_script = self.transition_phrase.join(parts)
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
