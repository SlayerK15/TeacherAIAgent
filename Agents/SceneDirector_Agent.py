import json
import re
from typing import Any, Callable, Dict, List, Optional


class SceneDirector_Agent:
    """Enhances scene plans with stronger visual storytelling while preserving narration text."""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self.llm_fn = llm_fn

    def enhance(self, existing_scene_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not existing_scene_plan:
            return []
        if not self.llm_fn:
            return [self._fallback_enhance(i, s) for i, s in enumerate(existing_scene_plan)]

        prompt = self._prompt(existing_scene_plan)
        raw = self.llm_fn(prompt)
        try:
            payload = self._parse_json(raw)
            scenes = payload if isinstance(payload, list) else payload.get("scenes", [])
            if not isinstance(scenes, list) or not scenes:
                raise ValueError("No scenes")
            # preserve original narration text strictly
            return self._merge_preserve_text(existing_scene_plan, scenes)
        except Exception:
            return [self._fallback_enhance(i, s) for i, s in enumerate(existing_scene_plan)]

    def _merge_preserve_text(self, original: List[Dict[str, Any]], enhanced: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for i, src in enumerate(original):
            e = enhanced[i] if i < len(enhanced) and isinstance(enhanced[i], dict) else {}
            item = {**src, **e}
            item["text"] = src.get("text", "")
            out.append(item)
        return out

    def _fallback_enhance(self, idx: int, scene: Dict[str, Any]) -> Dict[str, Any]:
        text = scene.get("text", "")
        visual_type = self._infer_type(text)
        emphasis = "highlight" if any(k in text.lower() for k in ["important", "key", "must", "critical"]) else "normal"
        return {
            **scene,
            "visual_type": visual_type,
            "background_query": self._background_query(visual_type, text),
            "overlay_elements": self._overlay_for_type(visual_type, text),
            "composition": {
                "background_placement": "full-bleed cinematic background with depth blur",
                "overlay_placement": "rule-of-thirds opposite speaker text",
                "text_placement": "lower third with safe margins",
            },
            "animation": {
                "entry": "soft fade + slight upward slide",
                "motion": "slow push-in (2-4%) with parallax overlays",
            },
            "emphasis_level": emphasis,
            "variation_strategy": "Alternates angle/motion/overlay density relative to previous scene",
            "reasoning": "Maps narration meaning to distinct visual metaphor/literal elements while keeping readability.",
        }

    def _infer_type(self, text: str) -> str:
        s = text.lower()
        if any(k in s for k in ["certification", "tool", "dashboard", "interface"]):
            return "literal"
        if any(k in s for k in ["growth", "learn", "confused", "journey"]):
            return "metaphor"
        if any(k in s for k in ["click", "menu", "app", "screen", "ui"]):
            return "ui"
        return "abstract"

    def _background_query(self, visual_type: str, text: str) -> str:
        base = text[:90]
        if visual_type == "metaphor":
            return f"cinematic symbolic scene representing {base}, volumetric light, shallow depth of field"
        if visual_type == "literal":
            return f"high-detail real-world scene of {base}, documentary style, natural lighting"
        if visual_type == "ui":
            return f"modern product UI mockup for {base}, dark mode, clean grid, 4k"
        return f"abstract motion graphics background for {base}, gradients, geometric depth"

    def _overlay_for_type(self, visual_type: str, text: str) -> List[str]:
        if visual_type == "metaphor":
            return ["path/roadmap line", "milestone markers", "glow arrows"]
        if visual_type == "literal":
            return ["labeled object callouts", "context icons", "keyword badges"]
        if visual_type == "ui":
            return ["interface cards", "cursor highlight", "step indicators"]
        return ["floating shape layers", "keyword chips", "soft data lines"]

    def _prompt(self, plan: List[Dict[str, Any]]) -> str:
        return (
            "You are a senior video director and visual storytelling expert.\n\n"
            "Your job is to enhance an existing video scene plan and make it highly engaging, visually rich, and logically aligned with narration.\n\n"
            "STRICT RULES:\n"
            "- Do NOT change narration text\n"
            "- Improve visuals, composition, and storytelling\n"
            "- Avoid generic stock visuals\n"
            "- Add depth (layered scenes, motion, overlays)\n"
            "- Ensure every visual clearly supports the meaning of narration\n"
            "- Introduce variety across scenes (no repetition)\n\n"
            "For EACH scene add:\n"
            "1. visual_type (literal / metaphor / abstract / ui)\n"
            "2. background_query\n"
            "3. overlay_elements\n"
            "4. composition {background placement, overlay placement, text placement}\n"
            "5. animation {entry, motion}\n"
            "6. emphasis_level (normal / highlight)\n"
            "7. variation_strategy\n"
            "8. reasoning\n\n"
            "SPECIAL INSTRUCTIONS:\n"
            "- For important sentences -> emphasis_level=highlight\n"
            "- Use metaphor visuals for abstract ideas\n"
            "- Use literal visuals for concrete terms\n"
            "- Mix at least 2 visual types across scenes\n"
            "- Avoid repeating the same type more than twice in a row\n\n"
            "INPUT:\n" + json.dumps(plan, ensure_ascii=False) + "\n\n"
            "OUTPUT: Enhanced structured JSON only."
        )

    @staticmethod
    def _parse_json(raw: str) -> Any:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
        m = re.search(r"(\[.*\]|\{.*\})", raw, re.S)
        return json.loads(m.group(1) if m else raw)
