import json
from datetime import datetime, timezone
from pathlib import Path
from config import DATA_DIR, DAILY_QUOTA_LIMIT

QUOTA_FILE = DATA_DIR / "quota_log.json"


def _today_pacific() -> str:
    """Get today's date in Pacific time (YouTube quota resets at midnight PT)."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def _load() -> dict:
    if QUOTA_FILE.exists():
        try:
            data = json.loads(QUOTA_FILE.read_text())
            if data.get("date") == _today_pacific():
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": _today_pacific(), "units_used": 0, "searches_made": 0, "calls": []}


def _save(data: dict):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_FILE.write_text(json.dumps(data, indent=2, default=str))


def get_remaining_quota() -> int:
    data = _load()
    return max(0, DAILY_QUOTA_LIMIT - data["units_used"])


def get_remaining_searches() -> int:
    return get_remaining_quota() // 100


def get_usage() -> dict:
    return _load()


def can_afford(cost: int) -> bool:
    return get_remaining_quota() >= cost


def record_usage(endpoint: str, cost: int, params: dict | None = None):
    data = _load()
    data["units_used"] += cost
    if endpoint == "search.list":
        data["searches_made"] += 1
    data["calls"].append({
        "endpoint": endpoint,
        "cost": cost,
        "params": params or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save(data)
