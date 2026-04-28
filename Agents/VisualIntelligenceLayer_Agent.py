import re
from collections import Counter
from typing import Any, Dict, List, Optional

from Agents.AssetFetcher_Agent import AssetFetcher_Agent
from Agents.Logger_Agent import get_current


class VisualIntelligenceLayer_Agent:
    """
    Visual-intelligence pass that:
    1) extracts reusable visual keywords from transcript text
    2) builds compact scene-like chunks
    3) queries the graphics collector (AssetFetcher_Agent)

    Notes:
    - AssetFetcher only uses free providers (Iconify/Openverse) or optionally-keyed
      providers (Pexels/Unsplash) and keeps source metadata/license values.
    - This layer is intentionally lightweight and deterministic so it can run even
      when LLM calls are rate-limited.
    """

    STOPWORDS = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "as", "is", "are", "was", "were",
        "be", "by", "that", "this", "it", "at", "from", "we", "you", "they", "i", "he", "she", "them", "our",
        "their", "your", "can", "will", "would", "should", "could", "about", "into", "over", "under", "than",
    }

    def __init__(self, collector: Optional[AssetFetcher_Agent] = None, max_keywords: int = 6):
        self.collector = collector or AssetFetcher_Agent()
        self.max_keywords = max_keywords

    def extract_keywords(self, transcript: str) -> List[str]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", transcript.lower())
        tokens = [w for w in words if w not in self.STOPWORDS and not w.isdigit()]
        if not tokens:
            return []
        ranked = [w for w, _ in Counter(tokens).most_common(self.max_keywords * 2)]

        # Preserve first-appearance order to keep semantic flow.
        ordered: List[str] = []
        seen = set()
        for w in words:
            if w in ranked and w not in seen:
                ordered.append(w)
                seen.add(w)
            if len(ordered) >= self.max_keywords:
                break
        return ordered

    def build_visual_plan(self, transcript: str, topic: str = "") -> List[Dict[str, Any]]:
        log = get_current()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript or "") if s.strip()]
        if not sentences:
            return []

        # Chunk every ~2 sentences for a compact plan.
        chunks: List[str] = []
        for i in range(0, len(sentences), 2):
            chunks.append(" ".join(sentences[i:i + 2]))

        output: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks, start=1):
            kws = self.extract_keywords(chunk)
            if not kws:
                kws = self.extract_keywords(transcript)[:3]
            visual_type = "background" if idx % 3 == 0 else "illustration"
            assets = self.collector.fetch_for_scene(kws, visual_type=visual_type, topic=topic)
            output.append({
                "chunk_id": idx,
                "text": chunk,
                "keywords": kws,
                "visual_type": visual_type,
                "assets": assets,
            })
            if log:
                log.info("VisualIntelligenceLayer chunk planned", chunk_id=idx, keywords=kws, assets=len(assets))
        return output
