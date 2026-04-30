import json
import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from Agents.AssetFetcher_Agent import AssetFetcher_Agent
from Agents.Logger_Agent import get_current


class VisualIntelligenceLayer_Agent:
    STOPWORDS = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "as", "is", "are", "was", "were",
        "be", "by", "that", "this", "it", "at", "from", "we", "you", "they", "i", "he", "she", "them", "our",
        "their", "your", "can", "will", "would", "should", "could", "about", "into", "over", "under", "than",
    }

    def __init__(
        self,
        collector: Optional[AssetFetcher_Agent] = None,
        llm_fn: Optional[Callable[[str], str]] = None,
        max_keywords: int = 6,
    ):
        self.collector = collector or AssetFetcher_Agent()
        self.llm_fn = llm_fn
        self.max_keywords = max_keywords

    def extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
        tokens = [w for w in words if w not in self.STOPWORDS and not w.isdigit()]
        if not tokens:
            return []
        ranked = [w for w, _ in Counter(tokens).most_common(self.max_keywords * 2)]
        ordered: List[str] = []
        seen = set()
        for w in words:
            if w in ranked and w not in seen:
                ordered.append(w)
                seen.add(w)
            if len(ordered) >= self.max_keywords:
                break
        return ordered

    def extract_semantic_data(self, text: str, topic: str = "") -> Dict[str, Any]:
        fallback = {
            "keywords": self.extract_keywords(text),
            "intent": self._infer_intent(text),
            "visual_type": self._visual_type_from_intent(self._infer_intent(text), []),
            "priority": "high" if len(text) > 180 else "low",
        }
        if not self.llm_fn:
            return fallback

        prompt = (
            "Extract visual-planning semantics as strict JSON with keys: "
            "keywords(list[str], max 6), intent(str), visual_type(str from literal|diagram|metaphor|background|illustration), "
            "priority(str high|low).\n"
            f"Topic: {topic or 'general'}\nText: {text}"
        )
        try:
            raw = self.llm_fn(prompt)
            obj = self._json_from_text(raw)
            kws = obj.get("keywords") if isinstance(obj.get("keywords"), list) else fallback["keywords"]
            intent = str(obj.get("intent") or fallback["intent"])
            visual_type = str(obj.get("visual_type") or self._visual_type_from_intent(intent, kws))
            priority = str(obj.get("priority") or fallback["priority"])
            return {
                "keywords": [str(k).lower() for k in kws][: self.max_keywords],
                "intent": intent,
                "visual_type": visual_type,
                "priority": "high" if priority.lower().startswith("h") else "low",
            }
        except Exception:
            return fallback

    def split_by_meaning(self, transcript: str) -> List[str]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript or "") if s.strip()]
        chunks: List[str] = []
        current: List[str] = []
        for s in sentences:
            if self._starts_new_idea(s) and current:
                chunks.append(" ".join(current))
                current = [s]
            else:
                current.append(s)
            if len(" ".join(current)) > 320:
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))
        return chunks

    def build_visual_queries(self, topic: str, semantic: Dict[str, Any]) -> List[str]:
        kws = semantic.get("keywords") or []
        intent = semantic.get("intent", "explain")
        visual_type = semantic.get("visual_type", "illustration")
        queries = [f"{visual_type} {intent}"]
        if kws:
            queries.append(f"{kws[0]} {topic or intent}")
        queries.append(f"{topic or 'education'} {intent} visual")
        return [q.strip() for q in queries if q.strip()]

    def build_visual_plan(self, transcript: str, topic: str = "") -> List[Dict[str, Any]]:
        log = get_current()
        chunks = self.split_by_meaning(transcript)
        out: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks, start=1):
            semantic = self.extract_semantic_data(chunk, topic=topic)
            queries = self.build_visual_queries(topic, semantic)

            assets: List[Dict[str, Any]] = []
            for q in queries:
                kws = [k for k in re.split(r"\s+", q) if k]
                assets.extend(self.collector.fetch_for_scene(kws, semantic["visual_type"], topic=topic))
                if len(assets) >= 10:
                    break

            ranked = self._rank_assets(assets, semantic["visual_type"], queries)
            if len(ranked) < 2:
                ranked.extend(self._generic_fallback_assets(semantic["intent"], topic))
            ranked = ranked[:3]

            out.append({
                "chunk_id": idx,
                "text": chunk,
                "keywords": semantic["keywords"],
                "intent": semantic["intent"],
                "priority": semantic["priority"],
                "visual_type": semantic["visual_type"],
                "queries": queries,
                "assets": ranked,
            })
            if log:
                log.info("VisualIntelligenceLayer chunk planned", chunk_id=idx, intent=semantic["intent"], assets=len(ranked))
        return out

    def _rank_assets(self, assets: List[Dict[str, Any]], visual_type: str, queries: List[str]) -> List[Dict[str, Any]]:
        scored = []
        qtokens = set(" ".join(queries).lower().split())
        seen = set()
        for a in assets:
            url = a.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            title = str(a.get("title", "")).lower()
            score = 0
            if any(t in title for t in qtokens):
                score += 2
            atype = str(a.get("type", "")).lower()
            if visual_type in atype or (visual_type == "diagram" and "icon" in atype):
                score += 3
            if a.get("width") and a.get("height"):
                if int(a["width"]) >= 1000 or int(a["height"]) >= 1000:
                    score += 1
            scored.append((score, a))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored]

    def _generic_fallback_assets(self, intent: str, topic: str) -> List[Dict[str, Any]]:
        mapping = {
            "growth": ["graph", "roadmap"],
            "confusion": ["maze", "question"],
            "learning": ["roadmap", "book"],
        }
        seed = []
        for k, vals in mapping.items():
            if k in intent.lower():
                seed = vals
                break
        seed = seed or ["education", "concept"]
        return self.collector.fetch_for_scene(seed, "illustration", topic=topic)[:2]

    def _starts_new_idea(self, sentence: str) -> bool:
        s = sentence.lower().strip()
        markers = ("next", "now", "however", "on the other hand", "in contrast", "first", "second", "finally")
        return any(s.startswith(m) for m in markers)

    def _infer_intent(self, text: str) -> str:
        s = text.lower()
        if any(k in s for k in ["grow", "career", "improve", "increase"]):
            return "growth"
        if any(k in s for k in ["confused", "problem", "struggle", "challenge"]):
            return "confusion"
        if any(k in s for k in ["compare", "difference", "versus"]):
            return "comparison"
        return "explain"

    def _visual_type_from_intent(self, intent: str, keywords: List[str]) -> str:
        i = intent.lower()
        if "growth" in i:
            return "metaphor"
        if "explain" in i or "comparison" in i:
            return "diagram"
        if any(k in {"device", "object", "tool", "cell", "atom"} for k in keywords):
            return "literal"
        return "illustration"

    @staticmethod
    def _json_from_text(raw: str) -> Dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
        match = re.search(r"\{.*\}", raw, re.S)
        return json.loads(match.group(0) if match else raw)
