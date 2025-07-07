import json
import re
from Agents.VoiceProcessing_Agent import VoiceProcessingAgent

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
        # Remove triple-backtick code blocks (optionally with "json" or "python" or nothing)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        return text

    def run(self, user_prompt, input_type="text"):
        prompt_text = self.process_input(user_prompt, input_type)
        llm_prompt = f"""
Given the following user prompt, analyze and break down the learning objectives into three tiers:
- Tier 1: The main topic and all essential supporting topics needed to understand the user's prompt.
- Tier 2: Topics that are helpful and often needed to support Tier 1, but not absolutely required.
- Tier 3: Background or related topics that are not important for Tier 1, but useful for deeper understanding or answering questions about Tier 2.

User Prompt: \"\"\"{prompt_text}\"\"\"

Respond ONLY in JSON format with keys 'tier_1', 'tier_2', 'tier_3', each mapping to a list of topic strings. Example:
{{
    "tier_1": ["main topic", "essential topic 1"],
    "tier_2": ["secondary topic 1", "secondary topic 2"],
    "tier_3": ["background topic 1"]
}}
"""
        result = self.llm_fn(llm_prompt)
        result = self._strip_codeblock(result)
        try:
            topic_tiers = json.loads(result)
        except Exception as e:
            print("DiscoveryAgent: Failed to parse LLM response. Raw output:")
            print(result)
            topic_tiers = {"tier_1": [], "tier_2": [], "tier_3": []}
        return topic_tiers
