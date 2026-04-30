from Agents.VisualIntelligenceLayer_Agent import VisualIntelligenceLayer_Agent


class StubCollector:
    def fetch_for_scene(self, keywords, visual_type, topic=""):
        return [
            {"url": f"http://x/{'-'.join(keywords[:2])}", "title": "career growth roadmap", "type": "image", "width": 1200, "height": 800},
            {"url": f"http://y/{visual_type}", "title": "generic visual", "type": visual_type},
        ]


def test_extract_semantic_data_fallback():
    a = VisualIntelligenceLayer_Agent(collector=StubCollector(), llm_fn=None)
    s = a.extract_semantic_data("I want to grow my cybersecurity career and improve skills")
    assert s["intent"] == "growth"
    assert s["visual_type"] in {"metaphor", "diagram", "illustration", "literal"}
    assert len(s["keywords"]) > 0


def test_build_visual_plan_has_queries_and_assets():
    a = VisualIntelligenceLayer_Agent(collector=StubCollector(), llm_fn=None)
    plan = a.build_visual_plan("First we explain basics. Next we compare career paths and improve outcomes.", topic="cybersecurity")
    assert len(plan) >= 1
    assert "queries" in plan[0]
    assert len(plan[0]["assets"]) >= 1
