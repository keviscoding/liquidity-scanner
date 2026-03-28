import re
import unicodedata
from datetime import datetime, timedelta, timezone
from statistics import mean
from googleapiclient.discovery import build
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from models import VideoData, ChannelData, NicheScore, CandidateNiche
from config import YOUTUBE_API_KEY
from cache import cache_get, cache_set
import quota as quota_tracker

console = Console()

# Non-Latin script ranges to detect non-English titles
_NON_LATIN_RE = re.compile(
    r'[\u0900-\u097F'   # Devanagari (Hindi)
    r'\u0980-\u09FF'    # Bengali
    r'\u0A00-\u0A7F'    # Gurmukhi (Punjabi)
    r'\u0B00-\u0B7F'    # Oriya
    r'\u0B80-\u0BFF'    # Tamil
    r'\u0C00-\u0C7F'    # Telugu
    r'\u0C80-\u0CFF'    # Kannada
    r'\u0D00-\u0D7F'    # Malayalam
    r'\u0E00-\u0E7F'    # Thai
    r'\u1000-\u109F'    # Myanmar
    r'\u3040-\u309F'    # Hiragana
    r'\u30A0-\u30FF'    # Katakana
    r'\u4E00-\u9FFF'    # CJK (Chinese)
    r'\uAC00-\uD7AF'    # Korean Hangul
    r'\u0600-\u06FF'    # Arabic
    r'\u0590-\u05FF'    # Hebrew
    r']'
)


# Common romanized non-English words (Hindi, Indonesian, etc.)
_NON_ENGLISH_WORDS = {
    # Hindi/Urdu romanized
    "kaise", "banaye", "kya", "hote", "hai", "kaise", "banaen", "mein", "karo",
    "karein", "karna", "wala", "wali", "nahi", "hain", "aur", "ke", "ka", "ki",
    "se", "ko", "par", "yeh", "ye", "bahut", "bohot", "accha", "sab", "kuch",
    "aap", "tum", "mai", "ek", "do", "bhi", "sirf", "matlab", "lekin",
    "pehle", "baad", "jaise", "kyun", "kyunki", "abhi", "jab", "isliye",
    "chahiye", "dikha", "dikhaye", "seekhe", "seekho", "samjhe", "bataye",
    "dekhiye", "jaane", "janiye",
    # Indonesian/Malay
    "cara", "membuat", "untuk", "dengan", "dan", "dari", "ini", "itu",
    "bisa", "sudah", "belum", "sangat", "juga", "atau", "tapi",
    "pakai", "menggunakan", "tanpa", "gratis", "mudah", "cepat",
    "mari", "selesaikan", "dapatkan", "lebih", "banyak", "malam",
    "hutan", "bermain", "semua", "harus", "baru", "lagi", "saja",
    "akan", "bukan", "tidak", "ada", "apa", "siapa", "dimana",
    "kapan", "kenapa", "bagaimana", "kalau", "mau", "ingin",
    # Portuguese
    "como", "fazer", "para", "voce", "isso", "aqui", "muito",
    # Spanish
    "como", "hacer", "para", "esto", "aqui", "muy", "mejor",
}


def is_english_title(title: str) -> bool:
    """Check if a video title is primarily English using multiple detection methods."""
    if not title:
        return True
    # Check for non-Latin script characters
    non_latin_chars = len(_NON_LATIN_RE.findall(title))
    if non_latin_chars > 2:
        return False
    # Check for romanized non-English words (Hindi written in Latin chars, etc.)
    words = set(title.lower().split())
    non_eng_count = len(words & _NON_ENGLISH_WORDS)
    if non_eng_count >= 2:
        return False
    # Use langdetect as backup for Latin-script languages we might miss
    try:
        from langdetect import detect
        # Only run on titles with enough text to detect (>20 chars)
        clean = re.sub(r'[#@\[\](){}|*📌📝✅✨🔥💰🎮]', '', title).strip()
        if len(clean) > 20:
            lang = detect(clean)
            if lang not in ('en',):
                return False
    except Exception:
        pass  # If detection fails, assume English
    return True


def _get_youtube_client():
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set. Add it to .env file.")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def _parse_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str or "")
    if not match:
        return 0
    h, m, s = match.groups(default="0")
    return int(h) * 3600 + int(m) * 60 + int(s)


def search_videos(youtube, term: str) -> tuple[list[dict], int]:
    """Search for recent videos matching a term. Costs 100 quota units."""
    if not quota_tracker.can_afford(100):
        raise RuntimeError("Insufficient quota for search")

    cache_key = f"search:{term}"
    cached = cache_get("search", cache_key)
    if cached:
        return cached["items"], cached["total_results"]

    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    response = youtube.search().list(
        q=term,
        type="video",
        part="id,snippet",
        maxResults=50,  # Fetch more so we still have 25+ after English filter
        order="date",
        publishedAfter=thirty_days_ago,
        relevanceLanguage="en",
    ).execute()

    quota_tracker.record_usage("search.list", 100, {"q": term})

    items = response.get("items", [])
    total = response.get("pageInfo", {}).get("totalResults", 0)

    # Filter to English-title videos only
    items = [
        item for item in items
        if is_english_title(item.get("snippet", {}).get("title", ""))
    ]

    cache_set("search", cache_key, {"items": items, "total_results": total})
    return items, total


def fetch_video_stats(youtube, video_ids: list[str]) -> list[VideoData]:
    """Fetch statistics for a batch of videos. Costs 1 quota unit per batch of 50."""
    if not video_ids:
        return []

    cache_key = f"videos:{','.join(sorted(video_ids))}"
    cached = cache_get("video", cache_key)
    if cached:
        return [VideoData(**v) for v in cached]

    if not quota_tracker.can_afford(1):
        raise RuntimeError("Insufficient quota for videos.list")

    response = youtube.videos().list(
        id=",".join(video_ids[:50]),
        part="statistics,contentDetails,snippet",
    ).execute()

    quota_tracker.record_usage("videos.list", 1, {"count": len(video_ids)})

    videos = []
    for item in response.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})

        published = snippet.get("publishedAt", "")
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pub_dt = datetime.now(timezone.utc)

        videos.append(VideoData(
            video_id=item["id"],
            title=snippet.get("title", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            published_at=pub_dt,
            view_count=int(stats.get("viewCount", 0)),
            like_count=int(stats.get("likeCount", 0)),
            comment_count=int(stats.get("commentCount", 0)),
            duration_seconds=_parse_duration(content.get("duration", "")),
        ))

    cache_set("video", cache_key, [
        {**v.__dict__, "published_at": v.published_at.isoformat()} for v in videos
    ])
    return videos


def fetch_channel_stats(youtube, channel_ids: list[str]) -> list[ChannelData]:
    """Fetch statistics for a batch of channels. Costs 1 quota unit per batch of 50."""
    if not channel_ids:
        return []

    cache_key = f"channels:{','.join(sorted(channel_ids))}"
    cached = cache_get("channel", cache_key)
    if cached:
        return [ChannelData(**c) for c in cached]

    if not quota_tracker.can_afford(1):
        raise RuntimeError("Insufficient quota for channels.list")

    response = youtube.channels().list(
        id=",".join(channel_ids[:50]),
        part="statistics,snippet",
    ).execute()

    quota_tracker.record_usage("channels.list", 1, {"count": len(channel_ids)})

    channels = []
    for item in response.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        channels.append(ChannelData(
            channel_id=item["id"],
            title=snippet.get("title", ""),
            subscriber_count=int(stats.get("subscriberCount", 0)),
            video_count=int(stats.get("videoCount", 0)),
            view_count=int(stats.get("viewCount", 0)),
        ))

    cache_set("channel", cache_key, [c.__dict__ for c in channels])
    return channels


def fetch_buying_signals(youtube, video_ids: list[str], max_videos: int = 3) -> dict:
    """Sample comments from top videos to detect buying intent.
    Returns {"buying_signal_count": int, "sample_comments": list[str], "signal_ratio": float}
    Costs 1 quota unit per video checked."""
    from config import BUYING_SIGNAL_PATTERNS

    total_comments = 0
    buying_comments = 0
    sample_buying = []

    for vid_id in video_ids[:max_videos]:
        cache_key = f"comments:{vid_id}"
        cached = cache_get("comments", cache_key)

        if cached is not None:
            comments_text = cached
        else:
            if not quota_tracker.can_afford(1):
                break
            try:
                resp = youtube.commentThreads().list(
                    videoId=vid_id,
                    part="snippet",
                    maxResults=50,
                    order="relevance",
                    textFormat="plainText",
                ).execute()
                quota_tracker.record_usage("commentThreads.list", 1, {"videoId": vid_id})
                comments_text = [
                    item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                    for item in resp.get("items", [])
                ]
                cache_set("comments", cache_key, comments_text)
            except Exception:
                comments_text = []
                cache_set("comments", cache_key, [])

        for comment in comments_text:
            total_comments += 1
            comment_lower = comment.lower()
            if any(pattern in comment_lower for pattern in BUYING_SIGNAL_PATTERNS):
                buying_comments += 1
                if len(sample_buying) < 5:
                    sample_buying.append(comment[:120])

    return {
        "buying_signal_count": buying_comments,
        "total_comments_checked": total_comments,
        "signal_ratio": buying_comments / max(total_comments, 1),
        "sample_comments": sample_buying,
    }


def compute_score(
    term: str,
    videos: list[VideoData],
    channels: list[ChannelData],
    total_results: int,
    parent_chain: list[str],
    buying_signals: dict | None = None,
) -> NicheScore:
    """Compute the full NicheScore for a niche."""
    now = datetime.now(timezone.utc)

    # --- Recency Score ---
    videos_7d = sum(1 for v in videos if (now - v.published_at).days <= 7)
    videos_30d = len(videos)

    if videos_7d >= 5:
        recency = 100
    elif videos_7d >= 3:
        recency = 85
    elif videos_30d >= 10:
        recency = 70
    elif videos_30d >= 5:
        recency = 50
    else:
        recency = max(0, videos_30d * 10)

    # --- Velocity Score (tightened: 2000 views/day = 100, not 500) ---
    velocities = []
    for v in videos:
        age_days = max(1, (now - v.published_at).days)
        velocities.append(v.view_count / age_days)
    avg_velocity = mean(velocities) if velocities else 0
    velocity = min(100, avg_velocity / 20)  # 2000 views/day = 100

    # --- Liquidity Score (THE KEY METRIC) ---
    channel_map = {ch.channel_id: ch for ch in channels}
    small_channels = {ch.channel_id: ch for ch in channels if ch.subscriber_count < 10_000}

    if not small_channels:
        liquidity = 20
    else:
        small_vids = [v for v in videos if v.channel_id in small_channels]
        if not small_vids:
            liquidity = 20
        else:
            avg_views_small = mean(v.view_count for v in small_vids)
            avg_subs_small = mean(ch.subscriber_count for ch in small_channels.values())
            ratio = avg_views_small / max(avg_subs_small, 1)

            if ratio >= 10:
                liquidity = 100
            elif ratio >= 5:
                liquidity = 90
            elif ratio >= 2:
                liquidity = 75
            elif ratio >= 1:
                liquidity = 60
            elif ratio >= 0.5:
                liquidity = 40
            else:
                liquidity = 20

            # Bonus: small channels in top-viewed videos
            sorted_by_views = sorted(videos, key=lambda v: v.view_count, reverse=True)
            top_10 = sorted_by_views[:10]
            small_in_top = sum(1 for v in top_10 if v.channel_id in small_channels)
            bonus = (small_in_top / max(len(top_10), 1)) * 20
            liquidity = min(100, liquidity + bonus)

    # --- Competition Score ---
    if total_results < 100:
        competition = 100
    elif total_results < 500:
        competition = 85
    elif total_results < 2000:
        competition = 65
    elif total_results < 10_000:
        competition = 40
    elif total_results < 50_000:
        competition = 20
    else:
        competition = 5

    # --- Specificity Score ---
    word_count = len(term.split())
    if word_count >= 5:
        specificity = 100
    elif word_count == 4:
        specificity = 85
    elif word_count == 3:
        specificity = 65
    elif word_count == 2:
        specificity = 40
    else:
        specificity = 15

    # Penalize generic tutorial/beginner terms — these are NOT micro-niches
    _generic_penalties = [
        "tutorial for beginners", "beginner tutorial", "for beginners",
        "full course", "full tutorial", "complete guide", "complete tutorial",
        "crash course", "from scratch", "step by step",
        "for dummies", "explained simply", "basics",
    ]
    term_lower_check = term.lower()
    for gp in _generic_penalties:
        if gp in term_lower_check:
            specificity = max(0, specificity - 40)  # Heavy penalty
            break

    # --- Urgency / Intent Signal Boost ---
    from config import URGENCY_WORDS
    term_lower = term.lower()
    urgency_hits = sum(1 for w in URGENCY_WORDS if w in term_lower)
    urgency_boost = min(10, urgency_hits * 3)  # Max +10 points

    # --- Buying Signal Boost (from comments) ---
    buying_boost = 0
    buying_signal_count = 0
    buying_signal_ratio = 0.0
    if buying_signals:
        buying_signal_count = buying_signals.get("buying_signal_count", 0)
        buying_signal_ratio = buying_signals.get("signal_ratio", 0.0)
        # If 10%+ of comments contain buying signals, that's a strong signal
        if buying_signal_ratio >= 0.15:
            buying_boost = 15
        elif buying_signal_ratio >= 0.10:
            buying_boost = 10
        elif buying_signal_ratio >= 0.05:
            buying_boost = 5
        elif buying_signal_count >= 3:
            buying_boost = 3

    # --- Composite ---
    overall = (
        recency * 0.16 +
        velocity * 0.20 +
        liquidity * 0.28 +
        competition * 0.08 +
        specificity * 0.10 +
        urgency_boost +
        buying_boost
    )
    overall = min(100, overall)  # Cap at 100

    # Derived stats
    all_views = [v.view_count for v in videos]
    avg_views = mean(all_views) if all_views else 0
    all_subs = [ch.subscriber_count for ch in channels]
    avg_subs = mean(all_subs) if all_subs else 0
    small_pct = (len(small_channels) / max(len(channels), 1)) * 100
    v2s_ratio = avg_views / max(avg_subs, 1) if videos else 0

    # Best video: prioritize small channel videos with high views (the liquidity proof)
    # Not the overall highest-view video, which is often from a massive irrelevant channel
    small_channel_vids = [v for v in videos if v.channel_id in small_channels]
    if small_channel_vids:
        best = max(small_channel_vids, key=lambda v: v.view_count)
    else:
        best = max(videos, key=lambda v: v.view_count) if videos else None
    best_ch_subs = channel_map.get(best.channel_id, ChannelData("", "", 0)).subscriber_count if best else 0

    # Top small channels (sorted by lowest subs first — the most impressive liquidity proof)
    top_small = sorted(small_channels.values(), key=lambda c: c.subscriber_count)[:5]
    top_channel_urls = [c.url for c in top_small]

    # Evidence videos: top 5 videos from small channels sorted by views (the proof of liquidity)
    evidence = sorted(small_channel_vids, key=lambda v: v.view_count, reverse=True)[:5] if small_channel_vids else []
    evidence_urls = [v.url for v in evidence]

    return NicheScore(
        term=term,
        overall_score=round(overall, 1),
        recency_score=round(recency, 1),
        velocity_score=round(velocity, 1),
        liquidity_score=round(liquidity, 1),
        competition_score=round(competition, 1),
        specificity_score=round(specificity, 1),
        total_results=total_results,
        videos_last_30d=videos_30d,
        avg_views=round(avg_views, 1),
        avg_views_per_day=round(avg_velocity, 1),
        avg_channel_subs=round(avg_subs, 1),
        view_to_sub_ratio=round(v2s_ratio, 2),
        small_channels_pct=round(small_pct, 1),
        best_video=best,
        best_video_channel_subs=best_ch_subs,
        top_channels=top_channel_urls,
        evidence_videos=evidence_urls,
        buying_signal_count=buying_signal_count,
        buying_signal_ratio=round(buying_signal_ratio, 3),
        buying_signal_samples=buying_signals.get("sample_comments", []) if buying_signals else [],
        videos_analyzed=videos,
        channels_analyzed=channels,
        parent_chain=parent_chain,
        searched_at=datetime.now(timezone.utc),
        quota_cost=102,
    )


def analyze_niche(youtube, candidate: CandidateNiche) -> NicheScore | None:
    """Full analysis of a single niche candidate. Costs ~102 quota units."""
    term = candidate.term

    # Check quota before starting
    if not quota_tracker.can_afford(105):  # 100 search + 1 videos + 1 channels + 3 comments
        console.print(f"[red]Skipping '{term}' - insufficient quota[/red]")
        return None

    try:
        # Step 1: Search for recent videos
        search_items, total_results = search_videos(youtube, term)

        # Early abort on dead niches
        if total_results < 10 or len(search_items) < 3:
            return None

        # Step 2: Get video IDs and fetch stats
        video_ids = [item["id"]["videoId"] for item in search_items if "videoId" in item.get("id", {})]
        if not video_ids:
            return None

        videos = fetch_video_stats(youtube, video_ids)

        # Filter out Shorts (under 90 seconds) — they don't indicate real monetizable demand
        long_videos = [v for v in videos if not v.is_short]
        # Also filter out non-English titles that slipped past the search filter
        long_videos = [v for v in long_videos if is_english_title(v.title)]

        # Need at least 3 long-form English videos to consider this a valid niche
        if len(long_videos) < 3:
            return None

        # Step 3: Get unique channel IDs and fetch stats (only for remaining videos)
        channel_ids = list(set(v.channel_id for v in long_videos if v.channel_id))
        channels = fetch_channel_stats(youtube, channel_ids)

        # Step 4: Scrape comments from top-viewed videos for buying signals
        # Sample the top 3 videos by views — costs 3 extra quota units
        top_by_views = sorted(long_videos, key=lambda v: v.view_count, reverse=True)
        top_ids = [v.video_id for v in top_by_views[:3]]
        buying_signals = fetch_buying_signals(youtube, top_ids, max_videos=3)

        # Step 5: Compute score using only long-form English videos + buying signals
        return compute_score(term, long_videos, channels, total_results, candidate.parent_chain,
                           buying_signals=buying_signals)

    except RuntimeError as e:
        console.print(f"[red]Error analyzing '{term}': {e}[/red]")
        return None
    except Exception as e:
        console.print(f"[yellow]Unexpected error for '{term}': {e}[/yellow]")
        return None


def analyze_candidates(
    candidates: list[CandidateNiche],
    max_searches: int = 50,
) -> list[NicheScore]:
    """Analyze a list of candidates using the YouTube API."""
    if not YOUTUBE_API_KEY:
        console.print("[red]No YOUTUBE_API_KEY set. Add it to .env file.[/red]")
        console.print("[yellow]Run with --dry-run to see discovery results without API.[/yellow]")
        return []

    youtube = _get_youtube_client()
    results = []
    to_analyze = candidates[:max_searches]

    console.print(f"\n[bold cyan]Analyzing {len(to_analyze)} niches via YouTube API...[/bold cyan]")
    console.print(f"[dim]Quota remaining: {quota_tracker.get_remaining_quota()} units[/dim]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing niches", total=len(to_analyze))

        for candidate in to_analyze:
            if not quota_tracker.can_afford(102):
                console.print("[red]Quota exhausted. Stopping analysis.[/red]")
                break

            score = analyze_niche(youtube, candidate)
            if score:
                results.append(score)
            progress.advance(task)

    results.sort(key=lambda s: s.overall_score, reverse=True)
    return dedup_niches(results)


def dedup_niches(scores: list[NicheScore]) -> list[NicheScore]:
    """Remove near-duplicate niches. Keeps the highest-scoring version of each."""
    if not scores:
        return scores

    # Synonym groups — words that mean the same thing in niche contexts
    _synonyms = {
        "swap": "change", "replace": "change", "switch": "change", "transform": "change",
        "make": "create", "build": "create", "generate": "create",
        "get": "find", "download": "get",
        "tutorial": "guide", "course": "guide", "lesson": "guide", "setup": "guide",
        "cheap": "budget", "affordable": "budget",
        "pc": "computer", "laptop": "computer",
        "app": "software", "tool": "software", "program": "software", "tools": "software",
        "through": "using", "via": "using",
        # Domain synonyms
        "food": "diet", "meal": "diet", "feeding": "diet", "nutrition": "diet",
        "old": "senior", "elderly": "senior", "aging": "senior", "aged": "senior",
        "failure": "disease", "problems": "disease", "issues": "disease",
        "controller": "system", "hub": "system",
        "sprinkler": "irrigation",
        "stripe": "payment",
    }

    def _normalize(term: str) -> set[str]:
        """Reduce a term to its core word set, with synonym folding."""
        stop = {"how", "to", "the", "a", "an", "in", "for", "with", "using", "by", "on", "your", "my",
                "through", "from", "and", "or", "of", "is", "are", "can", "do", "does", "what", "best",
                "top", "free", "online", "new", "good", "i"}
        words = set()
        for w in term.lower().split():
            if w in stop:
                continue
            words.add(_synonyms.get(w, w))
        return words

    kept = []
    seen_word_sets = []
    seen_prefixes = set()

    for s in scores:
        words = _normalize(s.term)
        if not words:
            kept.append(s)
            continue

        # Check 1: word overlap (65%+ = duplicate)
        is_dup = False
        for seen in seen_word_sets:
            overlap = len(words & seen) / max(len(words | seen), 1)
            if overlap >= 0.65:
                is_dup = True
                break

        # Check 2: shared 2-word prefix (e.g. "resistance bands X" vs "resistance bands Y")
        if not is_dup:
            raw_words = s.term.lower().split()
            if len(raw_words) >= 3:
                prefix = f"{raw_words[0]} {raw_words[1]}"
                if prefix in seen_prefixes:
                    is_dup = True
                else:
                    seen_prefixes.add(prefix)

        if not is_dup:
            kept.append(s)
            seen_word_sets.append(words)

    return kept
