import re
from typing import Dict, List
from Agents.Logger_Agent import get_current

CANVAS = {"width": 1280, "height": 720}


class LayoutEngine_Agent:
    """
    Rule-based layout engine. Picks one of four fixed templates per scene
    based on visual_type + light text introspection.

    Templates:
        - explanation: text left, image right
        - definition:  centered text + icon top
        - list:        bullet text + icon column
        - highlight:   background image + overlay text
    """

    TEMPLATES = {
        "explanation": {
            "text_position": {"x": 60, "y": 120, "width": 540, "height": 480, "align": "left"},
            "asset_position": {"x": 660, "y": 120, "width": 560, "height": 480, "align": "center"},
        },
        "definition": {
            "text_position": {"x": 140, "y": 320, "width": 1000, "height": 320, "align": "center"},
            "asset_position": {"x": 540, "y": 80, "width": 200, "height": 200, "align": "center"},
        },
        "list": {
            "text_position": {"x": 240, "y": 100, "width": 800, "height": 520, "align": "left"},
            "asset_position": {"x": 80, "y": 120, "width": 120, "height": 120, "align": "center", "repeat": True},
        },
        "highlight": {
            "text_position": {"x": 100, "y": 480, "width": 1080, "height": 160, "align": "center", "overlay": True},
            "asset_position": {"x": 0, "y": 0, "width": CANVAS["width"], "height": CANVAS["height"], "align": "cover"},
        },
    }

    def apply(self, scene: Dict, assets: List[Dict]) -> Dict:
        layout_type = self._pick_template(scene, assets)
        template = self.TEMPLATES[layout_type]
        return {
            "layout_type": layout_type,
            "canvas": dict(CANVAS),
            "text_position": dict(template["text_position"]),
            "asset_position": dict(template["asset_position"]),
        }

    @staticmethod
    def _pick_template(scene: Dict, assets: List[Dict]) -> str:
        text = (scene.get("text") or "").lower()
        visual_type = scene.get("visual_type", "illustration")

        if LayoutEngine_Agent._looks_like_list(text):
            return "list"
        if LayoutEngine_Agent._looks_like_definition(text):
            return "definition"
        if visual_type == "background":
            return "highlight"
        if visual_type == "icon" and len(text.split()) <= 18:
            return "definition"
        return "explanation"

    @staticmethod
    def _looks_like_list(text: str) -> bool:
        if re.search(r"\b(first|second|third|finally)[ ,]", text):
            return True
        if text.count(",") >= 3 and re.search(r"\b(such as|including|like)\b", text):
            return True
        if re.search(r"\b(steps?|examples?)\b", text) and text.count(",") >= 2:
            return True
        return False

    @staticmethod
    def _looks_like_definition(text: str) -> bool:
        return bool(
            re.search(r"\b(is the|is a|means|refers to|defined as|known as)\b", text)
        )
