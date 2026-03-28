"""YouTube browsing tools for the autonomous agent.

These are the "hands" of the agent — each tool lets it interact with YouTube
the way a human would. The agent decides which tool to use and when.

Tool costs:
  FREE:     autocomplete, alphabet_expand
  CHEAP:    video_stats (1 unit), channel_stats (1 unit), comments (1 unit), trending (1 unit)
  EXPENSIVE: search (100 units)
"""
import json
import random
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from config import YOUTUBE_API_KEY, BUYING_SIGNAL_PATTERNS
from cache import cache_get, cache_set
from analyzer import is_english_title
import quota as quota_tracker


def _get_youtube():
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


# ─── FREE TOOLS (no quota) ───────────────────────────────────────────────────

def tool_autocomplete(query: str) -> dict:
    """See what YouTube suggests when someone starts typing a query. FREE.
    Returns the raw suggestions — these reflect real search demand."""
    cached = cache_get("autocomplete", query)
    if cached is not None:
        return {"query": query, "suggestions": cached, "count": len(cached)}

    url = "https://clients1.google.com/complete/search"
    params = {"client": "youtube", "hl": "en", "ds": "yt", "q": query}
    try:
        resp = requests.get(url, params=params, timeout=10)
        text = resp.text
        start = text.index("(") + 1
        end = text.rindex(")")
        data = json.loads(text[start:end])
        suggestions = [item[0] for item in data[1]] if len(data) > 1 else []
    except Exception:
        suggestions = []

    cache_set("autocomplete", query, suggestions)
    time.sleep(0.3 + random.uniform(0, 0.2))
    return {"query": query, "suggestions": suggestions, "count": len(suggestions)}


def tool_alphabet_expand(query: str) -> dict:
    """Expand a query with a-z suffix to find all autocomplete branches. FREE.
    This reveals the breadth of search demand around a topic."""
    all_suggestions = set()

    base = tool_autocomplete(query)
    all_suggestions.update(base["suggestions"])

    for letter in "abcdefghijklmnopqrstuvwxyz":
        result = tool_autocomplete(f"{query} {letter}")
        all_suggestions.update(result["suggestions"])

    # Filter to English only
    english = [s for s in all_suggestions if is_english_title(s)]

    return {
        "query": query,
        "total_branches": len(english),
        "suggestions": sorted(english)[:50],  # Cap at 50 for readability
        "high_demand": len(english) > 15,  # 15+ branches = strong search volume
    }


# ─── CHEAP TOOLS (1 quota unit each) ─────────────────────────────────────────

def tool_browse_trending(category: str = "0", region: str = "US") -> dict:
    """Browse YouTube's trending/popular videos. Like opening YouTube's homepage.
    Category IDs: 0=all, 20=gaming, 22=people&blogs, 24=entertainment,
    25=news, 26=howto, 28=science&tech. Costs 1 quota unit."""

    cache_key = f"trending:{category}:{region}"
    cached = cache_get("trending", cache_key)
    if cached:
        return cached

    if not quota_tracker.can_afford(1):
        return {"error": "Insufficient quota"}

    yt = _get_youtube()
    resp = yt.videos().list(
        chart="mostPopular",
        regionCode=region,
        videoCategoryId=category,
        part="snippet,statistics",
        maxResults=25,
    ).execute()
    quota_tracker.record_usage("videos.list(trending)", 1, {"category": category})

    videos = []
    for item in resp.get("items", []):
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        title = snippet.get("title", "")
        if not is_english_title(title):
            continue
        videos.append({
            "video_id": item["id"],
            "title": title,
            "channel": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "published": snippet.get("publishedAt", ""),
        })

    result = {"category": category, "region": region, "videos": videos[:20]}
    cache_set("trending", cache_key, result)
    return result


def tool_get_video_details(video_ids: list[str]) -> dict:
    """Get detailed stats for specific videos. Costs 1 quota unit per batch of 50.
    Use this to check if a video's view count is disproportionate to its channel size."""

    if not video_ids:
        return {"videos": []}

    cache_key = f"vdetail:{','.join(sorted(video_ids[:10]))}"
    cached = cache_get("video_detail", cache_key)
    if cached:
        return cached

    if not quota_tracker.can_afford(1):
        return {"error": "Insufficient quota"}

    yt = _get_youtube()
    resp = yt.videos().list(
        id=",".join(video_ids[:50]),
        part="snippet,statistics,contentDetails",
    ).execute()
    quota_tracker.record_usage("videos.list", 1, {"count": len(video_ids)})

    videos = []
    for item in resp.get("items", []):
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        title = snippet.get("title", "")
        videos.append({
            "video_id": item["id"],
            "title": title,
            "channel": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "published": snippet.get("publishedAt", ""),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        })

    result = {"videos": videos}
    cache_set("video_detail", cache_key, result)
    return result


def tool_get_channel_info(channel_ids: list[str]) -> dict:
    """Get channel subscriber counts and stats. Costs 1 quota unit.
    Use this to check if a channel is small (key liquidity signal)."""

    if not channel_ids:
        return {"channels": []}

    cache_key = f"chinfo:{','.join(sorted(channel_ids[:10]))}"
    cached = cache_get("channel_info", cache_key)
    if cached:
        return cached

    if not quota_tracker.can_afford(1):
        return {"error": "Insufficient quota"}

    yt = _get_youtube()
    resp = yt.channels().list(
        id=",".join(channel_ids[:50]),
        part="snippet,statistics",
    ).execute()
    quota_tracker.record_usage("channels.list", 1, {"count": len(channel_ids)})

    channels = []
    for item in resp.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        channels.append({
            "channel_id": item["id"],
            "name": snippet.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "url": f"https://www.youtube.com/channel/{item['id']}",
        })

    result = {"channels": channels}
    cache_set("channel_info", cache_key, result)
    return result


def tool_read_comments(video_id: str) -> dict:
    """Read top comments on a video. Costs 1 quota unit.
    Look for buying signals: 'where do I get this', 'link?', 'does this work'"""

    cache_key = f"comments_tool:{video_id}"
    cached = cache_get("comments_tool", cache_key)
    if cached:
        return cached

    if not quota_tracker.can_afford(1):
        return {"error": "Insufficient quota"}

    yt = _get_youtube()
    try:
        resp = yt.commentThreads().list(
            videoId=video_id,
            part="snippet",
            maxResults=50,
            order="relevance",
            textFormat="plainText",
        ).execute()
        quota_tracker.record_usage("commentThreads.list", 1, {"videoId": video_id})
    except Exception as e:
        result = {"video_id": video_id, "comments": [], "buying_signals": [], "error": str(e)[:100]}
        cache_set("comments_tool", cache_key, result)
        return result

    comments = []
    buying_signals = []
    for item in resp.get("items", []):
        text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        likes = item["snippet"]["topLevelComment"]["snippet"].get("likeCount", 0)
        comments.append({"text": text[:200], "likes": likes})

        text_lower = text.lower()
        for pattern in BUYING_SIGNAL_PATTERNS:
            if pattern in text_lower:
                buying_signals.append({"comment": text[:200], "signal": pattern, "likes": likes})
                break

    result = {
        "video_id": video_id,
        "total_comments": len(comments),
        "comments": comments[:20],  # Top 20 for readability
        "buying_signals": buying_signals,
        "buying_signal_count": len(buying_signals),
        "buying_signal_ratio": len(buying_signals) / max(len(comments), 1),
    }
    cache_set("comments_tool", cache_key, result)
    return result


# ─── EXPENSIVE TOOLS (100 quota units) ───────────────────────────────────────

def tool_search_youtube(query: str, max_results: int = 25) -> dict:
    """Full YouTube search. Costs 100 quota units — use sparingly!
    Only use when you've already validated demand via autocomplete."""

    cache_key = f"agent_search:{query}"
    cached = cache_get("agent_search", cache_key)
    if cached:
        return cached

    if not quota_tracker.can_afford(100):
        return {"error": "Insufficient quota for search (need 100 units)"}

    yt = _get_youtube()
    thirty_days = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = yt.search().list(
        q=query,
        type="video",
        part="id,snippet",
        maxResults=max_results,
        order="date",
        publishedAfter=thirty_days,
        relevanceLanguage="en",
    ).execute()
    quota_tracker.record_usage("search.list", 100, {"q": query})

    items = resp.get("items", [])
    total = resp.get("pageInfo", {}).get("totalResults", 0)

    videos = []
    for item in items:
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        if not is_english_title(title):
            continue
        vid_id = item.get("id", {}).get("videoId", "")
        if vid_id:
            videos.append({
                "video_id": vid_id,
                "title": title,
                "channel": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "published": snippet.get("publishedAt", ""),
                "url": f"https://www.youtube.com/watch?v={vid_id}",
            })

    result = {
        "query": query,
        "total_results": total,
        "videos_found": len(videos),
        "videos": videos,
    }
    cache_set("agent_search", cache_key, result)
    return result


# ─── TOOL REGISTRY (for the agent to know what's available) ──────────────────

TOOL_DESCRIPTIONS = {
    "autocomplete": {
        "description": "See what YouTube suggests for a search query. Reveals real search demand. FREE, no quota.",
        "cost": "free",
        "args": "query (string)",
    },
    "alphabet_expand": {
        "description": "Get ALL autocomplete suggestions for a term (a-z expansion). Shows breadth of demand. FREE but slower.",
        "cost": "free",
        "args": "query (string)",
    },
    "browse_trending": {
        "description": "Browse YouTube's trending/popular videos. Like opening the homepage. Categories: 0=all, 20=gaming, 22=people&blogs, 24=entertainment, 25=news, 26=howto, 28=science&tech",
        "cost": "1 unit",
        "args": "category (string, default '0'), region (string, default 'US')",
    },
    "get_video_details": {
        "description": "Get detailed stats (views, likes, comments) for specific videos. Use to check view counts.",
        "cost": "1 unit per batch",
        "args": "video_ids (list of strings, max 50)",
    },
    "get_channel_info": {
        "description": "Get channel subscriber count and stats. Use to check if a channel is small (<10k subs).",
        "cost": "1 unit per batch",
        "args": "channel_ids (list of strings, max 50)",
    },
    "read_comments": {
        "description": "Read top 50 comments on a video. Automatically detects buying signals ('where do I get this', 'link?', etc.)",
        "cost": "1 unit",
        "args": "video_id (string)",
    },
    "search_youtube": {
        "description": "Full YouTube search for videos from the last 30 days. EXPENSIVE — use ONLY to validate a niche after autocomplete confirms demand.",
        "cost": "100 units",
        "args": "query (string)",
    },
}

TOOL_MAP = {
    "autocomplete": tool_autocomplete,
    "alphabet_expand": tool_alphabet_expand,
    "browse_trending": tool_browse_trending,
    "get_video_details": tool_get_video_details,
    "get_channel_info": tool_get_channel_info,
    "read_comments": tool_read_comments,
    "search_youtube": tool_search_youtube,
}


def execute_tool(tool_name: str, args: dict) -> dict:
    """Execute a browsing tool by name with the given arguments."""
    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"error": f"Tool error: {str(e)[:200]}"}
