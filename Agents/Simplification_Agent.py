import json
import re

class SimplificationAgent:
    """
    SimplificationAgent:
    - Takes topic tiers (output of DiscoveryAgent)
    - Breaks main and supporting topics into simple, beginner-friendly, teachable steps or modules
    """

    def __init__(self, llm_fn):
        """
        llm_fn: a function that takes a prompt string and returns a completion string
        """
        self.llm_fn = llm_fn

    def _strip_codeblock(self, text):
        # Remove triple-backtick code blocks (optionally with "json" or "python" or nothing)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        return text

    def run(self, topic_tiers: dict):
        """
        Accepts topic_tiers dict with keys 'tier_1', 'tier_2', 'tier_3' (DiscoveryAgent output).
        Returns a dict mapping each main/supporting topic to a list of simple steps or segments for teaching.
        """
        main_topics = topic_tiers.get("tier_1", [])
        support_topics = topic_tiers.get("tier_2", [])

        if not main_topics and not support_topics:
            print("SimplificationAgent: No topics provided for breakdown.")
            return {}

        prompt = (
            "You are an expert teacher. For each of the topics below, break it down into 3-5 clear, beginner-friendly learning steps. "
            "Use simple language, avoid jargon, and only include the topics listed. Format your response as valid JSON like this:\n"
            '{\n  "topic1": ["step 1", "step 2", ...],\n  "topic2": ["step 1", ...]\n}\n\n'
            f"Tier 1 (Main topics): {main_topics}\n"
            f"Tier 2 (Supporting topics): {support_topics}\n"
            "Now, provide a breakdown for each topic:"
        )

        print("Prompt sent to LLM:\n", prompt)  # (Optional: Remove in production)

        result = self.llm_fn(prompt)
        result = self._strip_codeblock(result)
        try:
            steps_by_topic = json.loads(result)
        except Exception as e:
            print("SimplificationAgent: Failed to parse LLM response. Raw output:")
            print(result)
            steps_by_topic = {}
        return steps_by_topic
