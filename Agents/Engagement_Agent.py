class EngagementAgent:
    """
    EngagementAgent:
    - Enhances teaching lessons (from TeachingAgent)
    - Injects attention-retaining, engagement-promoting prompts (not quizzes)
    """

    def __init__(self, llm_fn):
        """
        llm_fn: a function that takes a prompt string and returns a completion string
        """
        self.llm_fn = llm_fn

    def run(self, lessons: dict):
        """
        lessons: dict mapping topic -> lesson text (from TeachingAgent)
        Returns dict mapping topic -> engaged lesson (string)
        """
        engaged_lessons = {}

        for topic, lesson in lessons.items():
            prompt = f"""
You are an educational expert focused on engagement and attention retention.
Take the following lesson about "{topic}" and, without changing its factual content, enhance it with engaging, attention-retaining assets:
- Add reflection prompts (e.g., "Pause and think about...").
- Suggest visualizations or mental imagery.
- Insert real-life application thoughts ("Imagine if you...").
- Encourage the user to recall or say something aloud.
- Add supportive, motivational comments at key points.
Do NOT add any quizzes or knowledge checks.
Return the result as a single, natural-flowing lesson (not a list or JSON).
Lesson:
\"\"\"{lesson}\"\"\"
            """
            engaged_lesson = self.llm_fn(prompt)
            engaged_lessons[topic] = engaged_lesson.strip()

        return engaged_lessons
