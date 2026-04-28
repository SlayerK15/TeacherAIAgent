import json
import os
import sys

from pathlib import Path

env_path = Path(__file__).with_name(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if v:
            os.environ[k.strip()] = v.strip()

import openai

from Agents.SceneplannerAgent import SceneplannerAgent
from Agents.AssetFetcher_Agent import AssetFetcher_Agent
from Agents.LayoutEngine_Agent import LayoutEngine_Agent
from Agents.StoryboardComposer_Agent import StoryboardComposer_Agent

openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    sys.exit("OPENAI_API_KEY not set")


def llm(prompt: str) -> str:
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=1500,
    )
    return resp.choices[0].message.content.strip()


TOPIC = "What is Earth and its history"

transcript_prompt = f"""Write a short, engaging narration script for an educational video on:
\"{TOPIC}\".
Cover: what Earth is (a rocky planet in the solar system), its formation 4.5 billion years ago,
the early molten phase, formation of oceans and atmosphere, origin of life, the major eras
(Precambrian, Paleozoic, Mesozoic, Cenozoic), and humans today.
Keep it under 350 words, no headings, plain narration."""

print("Generating transcript...")
transcript = llm(transcript_prompt)
print(f"Transcript ({len(transcript.split())} words):\n{transcript}\n")

composer = StoryboardComposer_Agent(llm_fn=llm, per_keyword=4)
print("Composing storyboard...")
storyboard = composer.run(transcript, max_total_duration=120.0)
composer.close()

out_path = "output/storyboard_earth.json"
os.makedirs("output", exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"topic": TOPIC, "transcript": transcript, **storyboard}, f, indent=2)

print(f"\nWrote {out_path}")
print(f"scenes: {storyboard['scene_count']}  total_duration: {storyboard['total_duration']}s")
for s in storyboard["scenes"][:3]:
    print(f" - scene {s['scene_id']} [{s['layout']['layout_type']}] "
          f"{s['duration']}s  kw={s['keywords']}  assets={len(s['assets'])}")
