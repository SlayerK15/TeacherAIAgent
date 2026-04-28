import json
import re
from Agents.VoiceProcessing_Agent import VoiceProcessingAgent
from Agents.Logger_Agent import get_current

class DiscoveryAgent:
    """
    DiscoveryAgent breaks down a user's prompt into 3 tiers:
      - Tier 1: Main topic & 100% necessary supporting topics
      - Tier 2: Helpful supporting topics (not strictly required for Tier 1)
      - Tier 3: Related or background topics (good to know for deeper understanding)
    """
    def __init__(self, llm_fn, voice_agent=None):
        self.llm_fn = llm_fn
        self.voice_agent = voice_agent

    def process_input(self, input_data, input_type="text"):
        if input_type == "text":
            return input_data
        elif input_type == "audio":
            if self.voice_agent is None:
                raise ValueError("VoiceProcessingAgent instance required for audio input.")
            return self.voice_agent.speech_to_text(input_data)
        else:
            raise ValueError("input_type must be 'text' or 'audio'")

    def _strip_codeblock(self, text):
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        return text

    def run(self, user_prompt, input_type="text"):
        log = get_current()
        if log: log.info("DiscoveryAgent.run", input_type=input_type, prompt_len=len(str(user_prompt)))
        prompt_text = self.process_input(user_prompt, input_type)
        if log: log.info("DiscoveryAgent processed input", text_len=len(prompt_text))
        llm_prompt = f"""
Given the following user prompt, identify what to teach. The lesson must be ONE focused video
with a single intro and a single conclusion — no greeting twice.

- Tier 1: EXACTLY ONE topic — the single main subject of the lesson. If the user mentions
  multiple things, pick the primary one and treat the rest as Tier 2 sub-topics covered
  inside the same lesson. Do NOT split them into separate Tier 1 entries.
- Tier 2: Helpful supporting topics referenced in passing while teaching Tier 1
  (these will NOT become standalone lessons).
- Tier 3: Background or related topics for deeper understanding only.

User Prompt: \"\"\"{prompt_text}\"\"\"

Respond ONLY in JSON. Tier 1 MUST be a list with exactly one string. Example:
{{
    "tier_1": ["the one main topic"],
    "tier_2": ["sub-topic 1", "sub-topic 2"],
    "tier_3": ["background topic 1"]
}}
"""
        if log: log.step_start("DiscoveryAgent.llm_call", prompt_len=len(llm_prompt))
        result = self.llm_fn(llm_prompt)
        if log: log.step_end("DiscoveryAgent.llm_call", response_len=len(result))
        result = self._strip_codeblock(result)
        try:
            topic_tiers = json.loads(result)
        except Exception as e:
            if log: log.error("DiscoveryAgent json parse failed", error=str(e), raw=result[:400])
            else: print("DiscoveryAgent: Failed to parse LLM response. Raw output:\n" + result)
            topic_tiers = {"tier_1": [], "tier_2": [], "tier_3": []}
        # Enforce single tier_1: if the LLM returned multiple, demote the rest to tier_2.
        # This guarantees one greeting / one intro / one conclusion in the final video.
        t1 = topic_tiers.get("tier_1") or []
        if len(t1) > 1:
            extras = t1[1:]
            topic_tiers["tier_1"] = [t1[0]]
            topic_tiers["tier_2"] = list(dict.fromkeys((topic_tiers.get("tier_2") or []) + extras))
            if log: log.info("DiscoveryAgent collapsed multi tier_1",
                             primary=t1[0], demoted=extras)
        if log: log.info("DiscoveryAgent done", tier_sizes={k: len(v) for k, v in topic_tiers.items()})
        return topic_tiers
