class TeachingAgent:
    """
    TeachingAgent:
    - Takes simplified teaching steps (from SimplificationAgent)
    - Generates detailed, beginner-friendly lectures for each topic
    """

    def __init__(self, llm_fn):
        """
        llm_fn: a function that takes a prompt string and returns a completion string
        """
        self.llm_fn = llm_fn

    def run(self, simplified_steps: dict):
        """
        Accepts simplified_steps dict (topic: [steps...])
        Returns a dict mapping topic to a full teaching lesson (string)
        """
        teaching_content = {}

        for topic, steps in simplified_steps.items():
            steps_text = "\n".join(f"- {step}" for step in steps)
            prompt = f"""
You are an expert, friendly teacher. Your goal is to teach the topic "{topic}" to a total beginner.
Use the following steps as your lesson outline:
{steps_text}

For each step, provide a clear, concise explanation in natural language. Include examples or analogies where helpful.
Make the explanation flow like a real mini-lecture—not just bullet points.
Keep the tone engaging, supportive, and simple.
Return the lesson as plain text (not as a list or JSON).
            """
            lesson = self.llm_fn(prompt)
            teaching_content[topic] = lesson.strip()

        return teaching_content
