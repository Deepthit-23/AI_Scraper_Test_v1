"""
Persistent JSON cache for LLM calls — keyed by (namespace, content_key).

Prevents re-spending Groq free-tier tokens (100k/day) on identical descriptions.
Cache file: unihack/data/cache/llm_cache.json
"""

import json
import os
from pathlib import Path

_CACHE_FILE = Path(__file__).parent / "data" / "cache" / "llm_cache.json"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _CACHE_FILE.exists():
            try:
                with open(_CACHE_FILE, encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:
                _cache = {}
        else:
            _cache = {}
    return _cache


def _save() -> None:
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2)


def get(namespace: str, key: str):
    cache = _load()
    return cache.get(namespace, {}).get(key)


def set(namespace: str, key: str, value) -> None:
    cache = _load()
    if namespace not in cache:
        cache[namespace] = {}
    cache[namespace][key] = value
    _save()


def size() -> dict[str, int]:
    cache = _load()
    return {ns: len(entries) for ns, entries in cache.items()}


def find_by_substring(namespace: str, substring: str) -> tuple[str, object] | None:
    """
    Return (key, value) for the first entry in `namespace` whose key contains
    `substring` (case-insensitive), or None if no match.

    Used to recover cached extractions when the original URL can no longer be
    fetched (e.g. site is Cloudflare-blocked) but a prior successful extraction
    was stored under that URL as the key.
    """
    sub_lower = substring.lower()
    for key, val in _load().get(namespace, {}).items():
        if sub_lower in key.lower():
            return key, val
    return None


# ── Token / call tracking (in-process, reset each run) ────────────────────────

_stats: dict[str, int] = {"calls": 0, "tokens": 0}


def record_usage(total_tokens: int) -> None:
    _stats["calls"] += 1
    _stats["tokens"] += total_tokens


def reset_stats() -> None:
    _stats["calls"] = 0
    _stats["tokens"] = 0


def get_stats() -> dict[str, int]:
    return dict(_stats)
