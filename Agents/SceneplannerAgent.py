import json
import re
from typing import List, Dict, Any
from Agents.Logger_Agent import get_current

WORDS_PER_SECOND = 200 / 60.0  # match real TTS pace so duration estimates and
                                # _fit_to_budget truncation reflect actual playback length.
MIN_DURATION = 3.0
MAX_DURATION = 6.0           # used in the LLM prompt only — keeps planner output well-paced
SPLIT_THRESHOLD = 10.0       # _normalize splits any scene whose text would read longer than this
MIN_WORDS_PER_CHUNK = 8      # anything shorter gets merged into a neighbor (no 1-word frames)


class SceneplannerAgent:
    """
    Convert a free-form transcript into a list of structured scenes.

    Each scene is:
        {
            "scene_id": int,
            "text": str,
            "keywords": [str, ...],
            "visual_type": "icon" | "illustration" | "background",
            "duration": float (3.0 - 6.0)
        }
    """

    VISUAL_TYPES = {"icon", "illustration", "background"}

    def __init__(self, llm_fn=None):
        self.llm_fn = llm_fn

    def run(self, transcript: str, topic: str = "") -> List[Dict[str, Any]]:
        log = get_current()
        if not transcript or not transcript.strip():
            if log: log.warn("Sceneplanner: empty transcript")
            return []

        # Chunk the transcript verbatim — total duration tracks transcript reading time.
        chunk_texts = self._chunk_transcript(transcript)
        scenes: List[Dict[str, Any]] = [{"text": t} for t in chunk_texts]

        # Enrich each chunk with keywords + visual_type. Single LLM call (best relevance);
        # fall back to per-chunk heuristic on parse/network failure.
        used = "heuristic"
        if self.llm_fn:
            enriched = self._enrich_chunks_with_llm(chunk_texts, topic=topic)
            if enriched:
                # Match by 1-based id when present, else fall back to positional zip.
                by_id: Dict[int, Dict[str, Any]] = {}
                for meta in enriched:
                    try:
                        by_id[int(meta.get("id"))] = meta
                    except Exception:
                        pass
                hits = 0
                for i, s in enumerate(scenes):
                    meta = by_id.get(i + 1) if by_id else (
                        enriched[i] if i < len(enriched) else None
                    )
                    if not meta:
                        continue
                    kws = meta.get("keywords") or []
                    if kws:
                        s["keywords"] = kws
                        hits += 1
                    vt = meta.get("visual_type")
                    if vt in self.VISUAL_TYPES:
                        s["visual_type"] = vt
                if hits:
                    used = f"llm({hits}/{len(scenes)})"
                else:
                    if log: log.warn("Sceneplanner: LLM enrichment had no usable entries")
            else:
                if log: log.warn("Sceneplanner: LLM enrichment unusable, heuristic per-chunk")

        normalized = self._normalize(scenes)
        if log: log.info("Sceneplanner.run done", method=used,
                         raw_count=len(scenes), normalized_count=len(normalized))
        return normalized

    @classmethod
    def _chunk_transcript(cls, transcript: str) -> List[str]:
        """Split the transcript into chunks of MIN_DURATION..MAX_DURATION reading time,
        breaking at sentence boundaries so the entire transcript is preserved verbatim."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript.strip()) if s.strip()]
        chunks: List[str] = []
        buf: List[str] = []
        buf_dur = 0.0
        for sent in sentences:
            sent_dur = cls._estimate_duration(sent)
            if buf and buf_dur + sent_dur > MAX_DURATION:
                chunks.append(" ".join(buf))
                buf, buf_dur = [sent], sent_dur
            elif buf and buf_dur >= MIN_DURATION and sent_dur >= MIN_DURATION:
                # Both buffer and next sentence already satisfy MIN — start a new chunk
                chunks.append(" ".join(buf))
                buf, buf_dur = [sent], sent_dur
            else:
                buf.append(sent)
                buf_dur += sent_dur
        if buf:
            chunks.append(" ".join(buf))
        return cls._merge_tiny_chunks(chunks)

    @staticmethod
    def _merge_tiny_chunks(chunks: List[str]) -> List[str]:
        """Drop empties and merge any chunk shorter than MIN_WORDS_PER_CHUNK words
        into a neighbor. Prevents single-word/blank scene frames."""
        cleaned = [c.strip() for c in chunks if c and c.strip()]
        if not cleaned:
            return []
        merged: List[str] = []
        for c in cleaned:
            wc = len(c.split())
            if wc < MIN_WORDS_PER_CHUNK and merged:
                merged[-1] = (merged[-1] + " " + c).strip()
            else:
                merged.append(c)
        # If the very first chunk was tiny it's still alone — fold it into the next.
        if len(merged) >= 2 and len(merged[0].split()) < MIN_WORDS_PER_CHUNK:
            merged[1] = (merged[0] + " " + merged[1]).strip()
            merged = merged[1:]
        return merged

    def _enrich_chunks_with_llm(self, chunks: List[str], topic: str = "") -> List[Dict[str, Any]]:
        """Single LLM round-trip to label each chunk with keywords + visual_type.

        topic is the lesson subject (e.g. "binary trees data structure"). Passing it
        lets the LLM disambiguate generic words: "tree" -> "binary tree node diagram",
        "bank" -> "investment bank building", "cloud" -> "cloud computing servers"."""
        log = get_current()
        numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(chunks))
        topic_hint = f'\nLesson topic: "{topic}". Use this to disambiguate generic words.\n' if topic else ""
        prompt = f"""You are labeling video scenes for stock-image retrieval.
{topic_hint}
Below are {len(chunks)} numbered scene texts. For each, return:
- "keywords": 2-4 CONCRETE noun phrases describing what the viewer should see on screen.
  Rules:
    * NEVER use abstract verbs (imagine, explore, consider, learn).
    * NEVER use a single ambiguous word alone. Always include a domain qualifier so the
      stock image search returns the right thing. Examples:
        - "tree" in a CS lesson -> "binary tree data structure" (NOT a real tree)
        - "bank" in a finance lesson -> "bank building" or "money vault" (NOT riverbank)
        - "cloud" in a computing lesson -> "cloud computing server" (NOT weather cloud)
        - "virus" in a biology lesson -> "virus cell microscope" (NOT computer virus)
        - "java" in a programming lesson -> "java code editor" (NOT coffee)
        - "mouse" in a hardware lesson -> "computer mouse" (NOT animal)
    * Prefer multi-word phrases like "neural network diagram", "earth crust layer",
      "pangaea continent map", "stock market chart".
- "visual_type": "illustration" by default. Use "background" only for atmospheric
  scene-setters (history, story openings, world-building). Use "icon" only for very
  short single-concept callouts (one definition word). Default: "illustration".

Return ONLY valid JSON in this exact shape:
{{"scenes": [{{"id": 1, "keywords": ["..."], "visual_type": "illustration"}}]}}

Scenes:
{numbered}
"""
        try:
            if log: log.step_start("Sceneplanner.llm_call", prompt_len=len(prompt), chunks=len(chunks))
            raw = self.llm_fn(prompt)
            if log: log.step_end("Sceneplanner.llm_call", response_len=len(raw))
            data = self._parse_json_lenient(raw)
            scenes = data.get("scenes", []) if isinstance(data, dict) else []
            scenes.sort(key=lambda s: s.get("id", 0))
            return scenes
        except Exception as e:
            if log: log.error("Sceneplanner LLM enrich failed", exc_info=True, error=str(e))
            return []

    @classmethod
    def _parse_json_lenient(cls, raw: str) -> Dict[str, Any]:
        """Parse LLM JSON with best-effort repairs; raise if every attempt fails."""
        text = cls._strip_codeblock(raw)
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last > first:
            text = text[first:last + 1]
        attempts = [
            text,
            cls._normalize_quotes(text),
            cls._strip_trailing_commas(cls._normalize_quotes(text)),
        ]
        last_err: Exception = ValueError("empty")
        for candidate in attempts:
            try:
                return json.loads(candidate)
            except Exception as e:
                last_err = e
        scenes = cls._extract_scenes_array(text)
        if scenes:
            return {"scenes": scenes}
        raise last_err

    @staticmethod
    def _normalize_quotes(text: str) -> str:
        return (text
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2018", "'").replace("\u2019", "'"))

    @staticmethod
    def _strip_trailing_commas(text: str) -> str:
        return re.sub(r",(\s*[}\]])", r"\1", text)

    @staticmethod
    def _extract_scenes_array(text: str) -> List[Dict[str, Any]]:
        """Last-resort: pull each {...} object inside the scenes array, parse individually."""
        m = re.search(r'"scenes"\s*:\s*\[(.+)\]', text, flags=re.DOTALL)
        body = m.group(1) if m else text
        scenes: List[Dict[str, Any]] = []
        depth = 0
        start = -1
        for i, ch in enumerate(body):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    chunk = body[start:i + 1]
                    try:
                        scenes.append(json.loads(chunk))
                    except Exception:
                        try:
                            scenes.append(json.loads(re.sub(r",(\s*})", r"\1", chunk)))
                        except Exception:
                            pass
                    start = -1
        return scenes

    def _heuristic_plan(self, transcript: str) -> List[Dict[str, Any]]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript.strip()) if s.strip()]
        scenes: List[Dict[str, Any]] = []
        buf: List[str] = []
        scene_id = 1

        for sent in sentences:
            buf.append(sent)
            joined = " ".join(buf)
            duration = self._estimate_duration(joined)
            if duration >= MIN_DURATION:
                scenes.append({
                    "scene_id": scene_id,
                    "text": joined,
                    "keywords": self._extract_keywords(joined),
                    "visual_type": self._infer_visual_type(joined),
                    "duration": min(duration, MAX_DURATION),
                })
                scene_id += 1
                buf = []

        if buf:
            joined = " ".join(buf)
            scenes.append({
                "scene_id": scene_id,
                "text": joined,
                "keywords": self._extract_keywords(joined),
                "visual_type": self._infer_visual_type(joined),
                "duration": max(MIN_DURATION, min(self._estimate_duration(joined), MAX_DURATION)),
            })
        return scenes

    def _normalize(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Duration is derived from per-scene word count so the storyboard's total length
        # tracks the transcript reading time. Long scenes are split at sentence boundaries
        # to keep individual shots from outlasting SPLIT_THRESHOLD.
        normalized: List[Dict[str, Any]] = []
        next_id = 1
        for raw in scenes:
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            visual_type = raw.get("visual_type")
            if visual_type not in self.VISUAL_TYPES:
                # "illustration" routes to Pexels/Unsplash/Openverse — providers that
                # actually return content. "icon" defaulted everything to Iconify, which
                # fails on phrase queries and produced empty results across the board.
                visual_type = self._infer_visual_type(text)
            keywords = raw.get("keywords") or self._extract_keywords(text)
            keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()][:4]
            if not keywords:
                keywords = self._extract_keywords(text)
            for chunk in self._split_long_text(text):
                chunk = chunk.strip()
                # Skip blank/punctuation-only fragments — they would render as empty frames.
                if not chunk or len(chunk.split()) < 2:
                    continue
                duration = max(MIN_DURATION, self._estimate_duration(chunk))
                normalized.append({
                    "scene_id": next_id,
                    "text": chunk,
                    "keywords": keywords,
                    "visual_type": visual_type,
                    "duration": round(duration, 2),
                })
                next_id += 1
        return normalized

    @classmethod
    def _split_long_text(cls, text: str) -> List[str]:
        """Pack sentences into chunks each under SPLIT_THRESHOLD seconds of read time."""
        if cls._estimate_duration(text) <= SPLIT_THRESHOLD:
            return [text]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
        if len(sentences) <= 1:
            words = text.split()
            max_words = max(MIN_WORDS_PER_CHUNK, int(SPLIT_THRESHOLD * WORDS_PER_SECOND))
            pieces = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
            # Fold short tail back so we don't emit a 1-3 word fragment.
            if len(pieces) >= 2 and len(pieces[-1].split()) < MIN_WORDS_PER_CHUNK:
                pieces[-2] = pieces[-2] + " " + pieces[-1]
                pieces.pop()
            return pieces
        chunks: List[str] = []
        buf: List[str] = []
        buf_dur = 0.0
        for sent in sentences:
            sent_dur = cls._estimate_duration(sent)
            if buf and buf_dur + sent_dur > SPLIT_THRESHOLD:
                chunks.append(" ".join(buf))
                buf, buf_dur = [sent], sent_dur
            else:
                buf.append(sent)
                buf_dur += sent_dur
        if buf:
            chunks.append(" ".join(buf))
        return cls._merge_tiny_chunks(chunks)

    @staticmethod
    def _estimate_duration(text: str) -> float:
        words = max(len(text.split()), 1)
        return words / WORDS_PER_SECOND

    _STOPWORDS = {
        "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in",
        "on", "at", "for", "with", "is", "are", "was", "were", "be", "been",
        "this", "that", "these", "those", "it", "its", "as", "by", "from",
        "we", "you", "i", "they", "he", "she", "our", "your", "their",
        "have", "has", "had", "do", "does", "did", "will", "would", "can",
        "could", "should", "about", "into", "than", "so", "not", "no", "yes",
        # abstract verbs / transition words that produce irrelevant image queries
        "imagine", "picture", "consider", "think", "look", "see", "watch",
        "delve", "explore", "uncover", "discover", "reveal", "explain",
        "young", "old", "many", "some", "every", "each", "more", "less",
        "next", "first", "second", "third", "last", "final", "finally",
        "really", "very", "quite", "almost", "often", "sometimes", "always",
        "over", "under", "above", "below", "before", "after", "during",
        "there", "here", "where", "when", "while", "such", "even", "just",
        "make", "made", "take", "took", "give", "gave", "come", "came",
        "much", "most", "also", "only", "still", "ever", "well",
        # contractions left over after apostrophe stripping
        "youre", "lets", "dont", "doesnt", "didnt", "wont", "cant", "wasnt",
        "hes", "shes", "theyre", "weve", "ive", "thats", "whats", "isnt",
    }

    @classmethod
    def _extract_keywords(cls, text: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", text)
        seen = []
        for t in tokens:
            lower = t.lower()
            if lower in cls._STOPWORDS or len(lower) < 4:
                continue
            if lower not in seen:
                seen.append(lower)
            if len(seen) >= 4:
                break
        if not seen:
            seen = ["learning"]
        return seen

    @staticmethod
    def _infer_visual_type(text: str) -> str:
        # Bias toward "illustration" — that hits Pexels/Unsplash/Openverse where real
        # photos and illustrations live. "icon" is reserved for short, single-concept
        # callouts because Iconify only matches single-token queries reliably.
        lower = text.lower()
        if re.search(r"\b(imagine|picture|world|history|introduction|overview|story|setting)\b", lower):
            return "background"
        words = len(text.split())
        if words <= 6 and re.search(r"\b(define|definition|means|refers to|is the|is a|term|called)\b", lower):
            return "icon"
        return "illustration"

    @staticmethod
    def _strip_codeblock(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        return text
