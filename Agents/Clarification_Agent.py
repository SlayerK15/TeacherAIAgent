from typing import Optional, Dict

class ClarificationAgent:
    def __init__(self, llm_fn):
        self.llm_fn = llm_fn

    def run(
        self,
        user_question: str,
        lesson: str,
        engaged_lesson: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> str:
        """
        user_question: The user's follow-up question or confusion (text)
        lesson: The original teaching lesson (string)
        engaged_lesson: The engaged lesson version (optional, string)
        context: (optional) Any additional context or history
        Returns: string (clarification/answer)
        """
        lesson_context = engaged_lesson if engaged_lesson is not None else lesson
        extra = ""
        if context is not None:
            extra = f"\nPrevious conversation/context:\n{context}"

        prompt = f"""
You are a supportive, expert teacher. A user has just asked a follow-up question about the lesson below.
Lesson:
\"\"\"{lesson_context}\"\"\"
User's follow-up question:
\"\"\"{user_question}\"\"\"
{extra}
Respond with a clear, concise, and helpful clarification. If the question is ambiguous, politely ask for more details.
If possible, give an additional analogy or example to help the learner understand.
Return your response as plain text (not as a list or JSON).
        """
        answer = self.llm_fn(prompt)
        return answer.strip()
