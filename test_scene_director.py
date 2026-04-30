from Agents.SceneDirector_Agent import SceneDirector_Agent


def test_scene_director_preserves_text_and_adds_fields():
    plan = [{"scene_id": 1, "text": "Certifications help career growth."}]
    out = SceneDirector_Agent(llm_fn=None).enhance(plan)
    assert out[0]["text"] == plan[0]["text"]
    for k in ["visual_type", "background_query", "overlay_elements", "composition", "animation", "emphasis_level", "variation_strategy", "reasoning"]:
        assert k in out[0]
