import hashlib
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from Agents.Logger_Agent import get_current

CACHE_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_PER_KEYWORD = 5
MIN_PER_KEYWORD = 3

# Single-word keywords that are notoriously ambiguous in stock-image search.
# When one of these appears alone, we always prepend topic context to disambiguate
# (so "tree" in a CS lesson doesn't return real trees).
AMBIGUOUS_TERMS = {
    "tree", "bank", "cloud", "virus", "java", "python", "mouse", "apple", "mercury",
    "plant", "spring", "shell", "bug", "kernel", "node", "field", "key", "queue",
    "stack", "heap", "pipe", "thread", "table", "column", "row", "match", "branch",
    "leaf", "root", "trunk", "network", "model", "function", "object", "class",
    "instance", "pool", "link", "chain", "block", "ring", "set", "map", "bridge",
    "saturn", "amazon", "windows", "linux", "ruby", "go",
}


class AssetFetcher_Agent:
    """
    Fetch visual assets per keyword from free providers (Iconify, Pexels,
    Unsplash, Openverse), rank them, dedupe, and cache locally.

    Design notes:
    - Provider order is chosen by visual_type:
        icon         -> Iconify, Openverse
        illustration -> Openverse, Unsplash, Pexels
        background   -> Unsplash, Pexels, Openverse
    - Pexels and Unsplash require API keys (env: PEXELS_API_KEY, UNSPLASH_ACCESS_KEY).
      If a key is missing, that provider is silently skipped.
    - Iconify and Openverse are key-less.
    - All network calls have short timeouts; failures degrade gracefully.
    - Each scene gets between MIN_PER_KEYWORD and DEFAULT_PER_KEYWORD assets.
    - Fallback: if no asset is found, a placeholder dict is returned so the
      downstream layout engine never crashes.
    """

    # Backgrounds are ALWAYS photos. "icon" visual_type still uses the same photo
    # providers — iconify is pulled separately as a foreground accent (see fetch_for_scene).
    PROVIDER_ORDER = {
        "icon": ["pexels", "unsplash", "openverse"],
        "illustration": ["pexels", "unsplash", "openverse"],
        "background": ["unsplash", "pexels", "openverse"],
    }

    def __init__(
        self,
        cache_dir: str = "output/asset_cache",
        per_keyword: int = DEFAULT_PER_KEYWORD,
        timeout: float = 6.0,
        pexels_key: Optional[str] = None,
        unsplash_key: Optional[str] = None,
    ):
        self.cache_dir = cache_dir
        self.files_dir = os.path.join(cache_dir, "files")
        self.index_path = os.path.join(cache_dir, "index.json")
        os.makedirs(self.files_dir, exist_ok=True)
        self.per_keyword = max(MIN_PER_KEYWORD, per_keyword)
        self.timeout = timeout
        self.pexels_key = pexels_key or os.getenv("PEXELS_API_KEY")
        self.unsplash_key = unsplash_key or os.getenv("UNSPLASH_ACCESS_KEY")
        self._index = self._load_index()
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "TeacherAIAgent/1.0 (+https://github.com/anthropics/claude-code)"},
        )

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

    def fetch_for_scene(self, keywords: List[str], visual_type: str, topic: str = "") -> List[Dict]:
        log = get_current()
        if log: log.info("AssetFetcher.fetch_for_scene",
                         keywords=keywords, visual_type=visual_type, topic=topic)
        seen_urls: set = set()
        results: List[Dict] = []
        providers = self.PROVIDER_ORDER.get(visual_type, self.PROVIDER_ORDER["illustration"])

        # Try a combined multi-word query first — providers rank phrase queries far better
        # than single tokens. Topic context is prepended for ambiguous single-word
        # keywords so "tree" in a CS lesson returns binary trees, not real trees.
        cleaned = [k.strip() for k in (keywords or []) if k and k.strip()]
        topic_terms = self._topic_terms(topic)
        queries: List[str] = []
        if cleaned:
            primary = " ".join(cleaned[:3])
            queries.append(self._disambiguate(primary, topic_terms))
        for kw in cleaned:
            queries.append(self._disambiguate(kw, topic_terms))

        seen_queries: set = set()
        for query in queries:
            qkey = query.lower()
            if qkey in seen_queries:
                continue
            seen_queries.add(qkey)
            ranked = self._fetch_keyword(query, visual_type, providers)
            for asset in ranked:
                url = asset.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append(asset)
                if len(results) >= self.per_keyword:
                    break
            if len(results) >= self.per_keyword:
                break

        if not results:
            if log: log.warn("AssetFetcher: no assets found, using fallback", keywords=keywords)
            results.append(self._fallback(keywords, visual_type))

        # Always tack on a foreground icon (PNG) when one matches a single keyword.
        # The video pipeline pastes it in a corner as a small accent — backgrounds stay
        # photos, icons stay separate.
        icon = self._fetch_foreground_icon(cleaned)
        if icon and not any(a.get("provider") == "iconify" for a in results):
            results.append(icon)

        if log: log.info("AssetFetcher.fetch_for_scene done",
                         result_count=len(results),
                         providers_used=list({a.get("provider") for a in results}))
        return results[: self.per_keyword + 1]

    def _fetch_foreground_icon(self, keywords: List[str]) -> Optional[Dict]:
        """Fetch a single iconify PNG matching one of the keywords. Returns None
        if no clean single-token match is found."""
        log = get_current()
        for kw in keywords:
            token = self._best_iconify_token(kw)
            if not token or token in AMBIGUOUS_TERMS:
                continue
            try:
                icons = self._provider_iconify(token, "icon")
            except Exception as e:
                if log: log.warn("AssetFetcher.icon fetch failed", token=token, error=str(e))
                continue
            if not icons:
                continue
            top = icons[0]
            local_path = self._download_to_cache(top["url"])
            if local_path:
                top["local_path"] = local_path
                return top
        return None

    def _fetch_keyword(self, keyword: str, visual_type: str, providers: List[str]) -> List[Dict]:
        log = get_current()
        cache_key = f"{visual_type}:{keyword.lower()}"
        cached = self._index.get(cache_key)
        if cached and (time.time() - cached.get("ts", 0) < CACHE_TTL_SECONDS):
            if log: log.info("AssetFetcher cache hit", key=cache_key,
                             count=len(cached.get("assets", [])))
            return cached.get("assets", [])

        collected: List[Dict] = []
        for provider in providers:
            if log: log.step_start(f"AssetFetcher.{provider}", keyword=keyword)
            try:
                handler = getattr(self, f"_provider_{provider}")
                provider_assets = handler(keyword, visual_type)
                if log: log.step_end(f"AssetFetcher.{provider}",
                                     keyword=keyword, count=len(provider_assets))
            except Exception as e:
                if log: log.error(f"AssetFetcher.{provider} failed",
                                  exc_info=True, keyword=keyword, error=str(e))
                else: print(f"AssetFetcher: provider {provider} failed for '{keyword}': {e}")
                provider_assets = []
            collected.extend(provider_assets)
            if len(collected) >= self.per_keyword * 2:
                break

        ranked = self._rank(collected, keyword, visual_type)[: self.per_keyword]

        for asset in ranked:
            local_path = self._download_to_cache(asset["url"])
            if local_path:
                asset["local_path"] = local_path

        self._index[cache_key] = {"ts": time.time(), "assets": ranked}
        self._save_index()
        return ranked

    def _provider_iconify(self, keyword: str, _visual_type: str) -> List[Dict]:
        # Iconify matches icon names — phrase queries like "cloud computing services"
        # return nothing. Use the most concrete-looking single token instead.
        # We pull PNG (rendered server-side, height=192) so MoviePy/PIL can use it
        # directly without an SVG rasterizer dependency.
        single = self._best_iconify_token(keyword)
        if not single:
            return []
        url = f"https://api.iconify.design/search?query={quote_plus(single)}&limit=10"
        resp = self._client.get(url)
        resp.raise_for_status()
        data = resp.json()
        out: List[Dict] = []
        for icon_id in data.get("icons", []):
            if ":" not in icon_id:
                continue
            collection, name = icon_id.split(":", 1)
            out.append({
                "provider": "iconify",
                "type": "icon_png",
                "url": f"https://api.iconify.design/{collection}/{name}.png?height=192&color=%23ffffff",
                "id": icon_id,
                "title": name.replace("-", " "),
                "is_svg": False,
            })
        return out

    def _provider_openverse(self, keyword: str, visual_type: str) -> List[Dict]:
        category = "illustration" if visual_type != "background" else "photograph"
        url = (
            "https://api.openverse.org/v1/images/"
            f"?q={quote_plus(keyword)}&page_size=10&license_type=commercial"
            f"&category={category}"
        )
        resp = self._client.get(url, headers={"User-Agent": "TeacherAIAgent/1.0"})
        resp.raise_for_status()
        data = resp.json()
        out: List[Dict] = []
        for item in data.get("results", []):
            asset_url = item.get("url") or item.get("thumbnail")
            if not asset_url:
                continue
            out.append({
                "provider": "openverse",
                "type": "image",
                "url": asset_url,
                "id": item.get("id"),
                "title": item.get("title", ""),
                "is_svg": str(asset_url).lower().endswith(".svg"),
                "license": item.get("license"),
            })
        return out

    def _provider_pexels(self, keyword: str, _visual_type: str) -> List[Dict]:
        if not self.pexels_key:
            return []
        url = f"https://api.pexels.com/v1/search?query={quote_plus(keyword)}&per_page=10"
        resp = self._client.get(url, headers={"Authorization": self.pexels_key})
        resp.raise_for_status()
        data = resp.json()
        out: List[Dict] = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            asset_url = src.get("large") or src.get("medium") or src.get("original")
            if not asset_url:
                continue
            out.append({
                "provider": "pexels",
                "type": "image",
                "url": asset_url,
                "id": photo.get("id"),
                "title": photo.get("alt", ""),
                "is_svg": False,
            })
        return out

    def _provider_unsplash(self, keyword: str, _visual_type: str) -> List[Dict]:
        if not self.unsplash_key:
            return []
        url = (
            "https://api.unsplash.com/search/photos"
            f"?query={quote_plus(keyword)}&per_page=10"
        )
        resp = self._client.get(
            url, headers={"Authorization": f"Client-ID {self.unsplash_key}"}
        )
        resp.raise_for_status()
        data = resp.json()
        out: List[Dict] = []
        for photo in data.get("results", []):
            urls = photo.get("urls", {})
            asset_url = urls.get("regular") or urls.get("small")
            if not asset_url:
                continue
            out.append({
                "provider": "unsplash",
                "type": "image",
                "url": asset_url,
                "id": photo.get("id"),
                "title": photo.get("alt_description", ""),
                "is_svg": False,
            })
        return out

    @staticmethod
    def _disambiguate(query: str, topic_terms: str) -> str:
        """Always prepend topic_terms when the query is a single ambiguous word, or
        when the query has no topic context but topic_terms exist. Multi-word queries
        that already contain a topic anchor are left alone."""
        q = (query or "").strip()
        if not q:
            return topic_terms
        if not topic_terms:
            return q
        tokens = q.lower().split()
        # Single ambiguous token — always disambiguate.
        if len(tokens) == 1 and tokens[0] in AMBIGUOUS_TERMS:
            return f"{topic_terms} {q}".strip()
        # If any topic term already appears in the query, don't double-stuff it.
        topic_set = set(topic_terms.lower().split())
        if topic_set & set(tokens):
            return q
        return f"{topic_terms} {q}".strip()

    @staticmethod
    def _best_iconify_token(query: str) -> str:
        """Iconify needs a single token. Pick the longest concrete-looking word
        from the query (skip generic stopwords)."""
        stop = {"the", "and", "for", "with", "from", "into", "onto", "this", "that",
                "what", "why", "how", "all", "any", "is", "are", "of", "to", "in"}
        best = ""
        for tok in re.findall(r"[A-Za-z][A-Za-z\-]+", query):
            low = tok.lower()
            if low in stop or len(low) < 3:
                continue
            if len(low) > len(best):
                best = low
        return best

    @staticmethod
    def _topic_terms(topic: str) -> str:
        """Reduce a free-form topic ('LLM what is and how to make') to 1-2 anchor terms
        for query prefixing. Drops generic question words and short tokens."""
        if not topic:
            return ""
        stop = {
            "what", "why", "how", "who", "when", "where", "which", "whose",
            "the", "a", "an", "and", "or", "of", "to", "in", "on", "is", "are",
            "make", "do", "does", "did", "tell", "me", "about", "explain",
            "teach", "show", "describe", "this", "that",
        }
        out: List[str] = []
        for tok in re.findall(r"[A-Za-z][A-Za-z\-]+", topic):
            low = tok.lower()
            if low in stop or len(low) < 3:
                continue
            if low not in out:
                out.append(low)
            if len(out) >= 3:
                break
        return " ".join(out)

    @staticmethod
    def _rank(assets: List[Dict], keyword: str, visual_type: str) -> List[Dict]:
        kw = keyword.lower()
        provider_pref = {
            "icon": {"iconify": 3, "openverse": 2, "unsplash": 1, "pexels": 1},
            "illustration": {"openverse": 3, "unsplash": 2, "pexels": 2, "iconify": 1},
            "background": {"unsplash": 3, "pexels": 3, "openverse": 2, "iconify": 0},
        }.get(visual_type, {})

        def score(asset: Dict) -> Tuple[int, int, int]:
            title = (asset.get("title") or "").lower()
            kw_score = 2 if kw in title else (1 if any(w in title for w in kw.split()) else 0)
            svg_bonus = 1 if (visual_type == "icon" and asset.get("is_svg")) else 0
            provider_score = provider_pref.get(asset.get("provider", ""), 0)
            return (provider_score, kw_score, svg_bonus)

        return sorted(assets, key=score, reverse=True)

    def _fallback(self, keywords: List[str], visual_type: str) -> Dict:
        label = (keywords[0] if keywords else "concept").lower()
        return {
            "provider": "fallback",
            "type": "placeholder",
            "url": "",
            "id": f"fallback:{visual_type}:{label}",
            "title": label,
            "is_svg": False,
            "local_path": None,
            "fallback": True,
        }

    def _download_to_cache(self, url: str) -> Optional[str]:
        if not url:
            return None
        ext = self._guess_extension(url)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        local_path = os.path.join(self.files_dir, f"{digest}{ext}")
        if os.path.exists(local_path):
            return local_path
        try:
            with self._client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
            return local_path
        except Exception as e:
            print(f"AssetFetcher: download failed for {url}: {e}")
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError:
                    pass
            return None

    @staticmethod
    def _guess_extension(url: str) -> str:
        match = re.search(r"\.(svg|png|jpg|jpeg|webp|gif)(\?|$)", url, re.IGNORECASE)
        return f".{match.group(1).lower()}" if match else ".bin"

    def _load_index(self) -> Dict:
        if not os.path.exists(self.index_path):
            return {}
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_index(self):
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, indent=2)
        except Exception as e:
            print(f"AssetFetcher: failed to write cache index: {e}")
