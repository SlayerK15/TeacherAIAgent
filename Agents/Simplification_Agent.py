import json
import re
from Agents.Logger_Agent import get_current

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
        # Tier 2/3 are background context for the LLM, NOT lesson topics — keeping them
        # in the simplification output bloated lessons (e.g. "History of Earth" turning
        # into 11 separate sub-lessons). The teaching pipeline now stays focused on tier_1.
        support_context = topic_tiers.get("tier_2", [])

        log = get_current()
        if log: log.info("SimplificationAgent.run",
                         tier1_count=len(main_topics),
                         tier2_context_count=len(support_context))
        if not main_topics:
            if log: log.warn("SimplificationAgent: no tier_1 topics provided")
            else: print("SimplificationAgent: No tier_1 topics provided for breakdown.")
            return {}

        prompt = (
            "You are an expert teacher. For each of the MAIN topics below, break it down into 3-5 clear, beginner-friendly learning steps. "
            "Only produce keys for the main topics — the supporting context list is only there to help you frame the steps with appropriate background. "
            "Format your response as valid JSON like this:\n"
            '{\n  "topic1": ["step 1", "step 2", ...],\n  "topic2": ["step 1", ...]\n}\n\n'
            f"Main topics (produce one entry per item): {main_topics}\n"
            f"Supporting context (do NOT produce entries for these — use them only as reference): {support_context}\n"
            "Now, provide a breakdown for each MAIN topic only:"
        )

        if log: log.step_start("SimplificationAgent.llm_call", prompt_len=len(prompt))
        result = self.llm_fn(prompt)
        if log: log.step_end("SimplificationAgent.llm_call", response_len=len(result))
        result = self._strip_codeblock(result)
        try:
            steps_by_topic = json.loads(result)
        except Exception as e:
            if log: log.error("SimplificationAgent json parse failed", error=str(e), raw=result[:400])
            else: print("SimplificationAgent: Failed to parse LLM response. Raw output:\n" + result)
            steps_by_topic = {}
        if log: log.info("SimplificationAgent done", topic_count=len(steps_by_topic))
        return steps_by_topic
