import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from config import CACHE_DIR, CACHE_TTL_HOURS


def _cache_file(namespace: str) -> Path:
    return CACHE_DIR / f"{namespace}.json"


def _load_cache(namespace: str) -> dict:
    path = _cache_file(namespace)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(namespace: str, data: dict):
    path = _cache_file(namespace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str))


def _make_key(key: str) -> str:
    return hashlib.md5(key.encode()).hexdigest()


def cache_get(namespace: str, key: str) -> dict | None:
    cache = _load_cache(namespace)
    hashed = _make_key(key)
    entry = cache.get(hashed)
    if entry is None:
        return None
    expires = datetime.fromisoformat(entry["expires"])
    if datetime.now() > expires:
        return None
    return entry["data"]


def cache_set(namespace: str, key: str, data) -> None:
    cache = _load_cache(namespace)
    hashed = _make_key(key)
    cache[hashed] = {
        "key_raw": key,
        "data": data,
        "expires": (datetime.now() + timedelta(hours=CACHE_TTL_HOURS)).isoformat(),
    }
    _save_cache(namespace, cache)
