from typing import Any, Dict, List, Optional

from Agents.SceneplannerAgent import SceneplannerAgent
from Agents.AssetFetcher_Agent import AssetFetcher_Agent
from Agents.LayoutEngine_Agent import LayoutEngine_Agent
from Agents.VisualIntelligenceLayer_Agent import VisualIntelligenceLayer_Agent
from Agents.SceneDirector_Agent import SceneDirector_Agent
from Agents.Logger_Agent import get_current


class StoryboardComposer_Agent:
    """
    Orchestrates the structured storyboard pipeline:
        transcript -> scenes -> assets -> layout -> timing -> storyboard JSON
    """

    def __init__(
        self,
        llm_fn=None,
        cache_dir: str = "output/asset_cache",
        per_keyword: int = 5,
    ):
        self.planner = SceneplannerAgent(llm_fn=llm_fn)
        self.fetcher = AssetFetcher_Agent(cache_dir=cache_dir, per_keyword=per_keyword)
        self.layout = LayoutEngine_Agent()
        self.visual_layer = VisualIntelligenceLayer_Agent(collector=self.fetcher, llm_fn=llm_fn)
        self.scene_director = SceneDirector_Agent(llm_fn=llm_fn)

    def close(self):
        self.fetcher.close()

    def run(
        self,
        transcript: str,
        max_total_duration: Optional[float] = None,
        topic: str = "",
    ) -> Dict[str, Any]:
        log = get_current()
        if log: log.step_start("StoryboardComposer.plan",
                               transcript_chars=len(transcript or ""),
                               max_duration=max_total_duration)
        scenes = self.planner.run(transcript, topic=topic)
        if log: log.step_end("StoryboardComposer.plan", scene_count=len(scenes))
        if not scenes:
            if log: log.warn("StoryboardComposer: planner returned no scenes")
            return {"scenes": [], "total_duration": 0.0}

        scenes = self._fit_to_budget(scenes, max_total_duration)

        composed: List[Dict[str, Any]] = []
        cursor = 0.0
        for idx, scene in enumerate(scenes):
            if log: log.step_start(f"StoryboardComposer.scene[{idx}]",
                                   scene_id=scene.get("scene_id"),
                                   keywords=scene.get("keywords"))
            scene_keywords = scene.get("keywords", [])
            scene_visual_type = scene.get("visual_type", "illustration")
            if len(scene_keywords) < 2:
                semantic = self.visual_layer.extract_semantic_data(scene.get("text", ""), topic=topic)
                extra = semantic.get("keywords", [])[:3]
                scene_keywords = list(dict.fromkeys([*scene_keywords, *extra]))
                scene_visual_type = semantic.get("visual_type") or scene_visual_type

            assets = self.fetcher.fetch_for_scene(
                keywords=scene_keywords,
                visual_type=scene_visual_type,
                topic=topic,
            )
            layout = self.layout.apply(scene, assets)
            if log: log.step_end(f"StoryboardComposer.scene[{idx}]",
                                 asset_count=len(assets),
                                 layout_blocks=len(layout) if hasattr(layout, "__len__") else None)
            composed.append({
                "scene_id": scene["scene_id"],
                "text": scene["text"],
                "keywords": scene_keywords,
                "visual_type": scene_visual_type,
                "duration": scene["duration"],
                "start_time": round(cursor, 2),
                "end_time": round(cursor + scene["duration"], 2),
                "assets": assets,
                "layout": layout,
            })
            cursor += scene["duration"]

        enhanced = self.scene_director.enhance(composed)

        return {
            "scenes": enhanced,
            "total_duration": round(cursor, 2),
            "scene_count": len(enhanced),
        }

    @staticmethod
    def _fit_to_budget(
        scenes: List[Dict[str, Any]],
        max_total_duration: Optional[float],
    ) -> List[Dict[str, Any]]:
        """Truncate the scene list so cumulative duration <= budget. The previous
        rescale-only approach hit the per-scene min-duration clamp and never
        actually shortened the total, leading to runaway scene counts."""
        if not max_total_duration or max_total_duration <= 0:
            return scenes
        out: List[Dict[str, Any]] = []
        cumulative = 0.0
        for s in scenes:
            d = float(s.get("duration", 4.0))
            if cumulative + d > max_total_duration:
                remaining = max_total_duration - cumulative
                if remaining >= 3.0:
                    out.append({**s, "duration": round(remaining, 2)})
                break
            out.append(s)
            cumulative += d
        return out
