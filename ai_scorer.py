"""Two-pass AI scoring pipeline: quick filter → deep analysis."""
import asyncio
import json
from datetime import datetime, timezone

from ai_client import LLMClient, get_fast_client, get_deep_client
from ai_prompts import (
    QUICK_FILTER_SYSTEM, QUICK_FILTER_USER,
    DEEP_ANALYSIS_SYSTEM, DEEP_ANALYSIS_USER,
    BRIEFING_SYSTEM, BRIEFING_USER,
)
from models import NicheScore, AIAnalysis


def _format_niche_for_filter(idx: int, score: NicheScore) -> str:
    """Format a single niche for the quick filter prompt."""
    titles = []
    for v in score.videos_analyzed[:5]:
        titles.append(f'  "{v.title}"')
    titles_str = "\n".join(titles) if titles else "  (no video data)"

    return (
        f"{idx}. \"{score.term}\"\n"
        f"   {score.videos_last_30d} videos in 30d, avg {score.avg_views:,.0f} views, "
        f"avg {score.avg_channel_subs:,.0f} subs, {score.view_to_sub_ratio:.1f}x V/S ratio\n"
        f"   Top titles:\n{titles_str}"
    )


def _format_video_block(score: NicheScore) -> str:
    """Format video details for deep analysis."""
    lines = []
    sorted_vids = sorted(score.videos_analyzed, key=lambda v: v.view_count, reverse=True)
    for v in sorted_vids[:15]:
        age = max(1, (datetime.now(timezone.utc) - v.published_at).days)
        lines.append(
            f'- "{v.title}" | {v.view_count:,} views | {v.view_count // age:,} views/day | '
            f"published {age}d ago | channel: {v.channel_title}"
        )
    return "\n".join(lines) if lines else "(no video data)"


def _format_channel_block(score: NicheScore) -> str:
    """Format channel details for deep analysis."""
    lines = []
    sorted_chs = sorted(score.channels_analyzed, key=lambda c: c.subscriber_count)
    for c in sorted_chs[:15]:
        label = "SMALL" if c.subscriber_count < 10_000 else ""
        lines.append(f"- {c.title} | {c.subscriber_count:,} subs | {c.video_count} videos {label}")
    return "\n".join(lines) if lines else "(no channel data)"


# ─── Pass 1: Quick Filter ────────────────────────────────────────────────────

async def quick_filter(
    scores: list[NicheScore],
    batch_size: int = 10,
    min_rating: int = 3,
    on_progress=None,
) -> list[tuple[NicheScore, int, str]]:
    """
    Filter niches using Claude. Returns (score, rating, reason) tuples for niches rated >= min_rating.
    """
    client = get_fast_client()
    batches = []
    for i in range(0, len(scores), batch_size):
        batch = scores[i:i + batch_size]
        niches_block = "\n\n".join(
            _format_niche_for_filter(j + 1, s) for j, s in enumerate(batch)
        )
        batches.append({
            "system": QUICK_FILTER_SYSTEM,
            "user": QUICK_FILTER_USER.format(niches_block=niches_block),
            "batch_scores": batch,
        })

    if on_progress:
        on_progress(f"AI Pass 1: Filtering {len(scores)} niches in {len(batches)} batches...")

    requests = [{"system": b["system"], "user": b["user"]} for b in batches]
    results = await client.batch_complete_json(requests, max_tokens=2048)

    passed = []
    for batch_idx, result in enumerate(results):
        if isinstance(result, Exception):
            # On error, pass through all niches in this batch
            for s in batches[batch_idx]["batch_scores"]:
                passed.append((s, 3, "AI filter error — passed through"))
            continue

        batch_scores = batches[batch_idx]["batch_scores"]
        # Build term → score lookup
        term_map = {s.term.lower(): s for s in batch_scores}

        if isinstance(result, list):
            for item in result:
                term = item.get("term", "").lower()
                rating = item.get("rating", 0)
                reason = item.get("reason", "")
                if rating >= min_rating:
                    score = term_map.get(term)
                    if score:
                        passed.append((score, rating, reason))

    if on_progress:
        on_progress(f"AI Pass 1 complete: {len(passed)}/{len(scores)} niches passed (rated {min_rating}+)")

    return passed


# ─── Pass 2: Deep Analysis ───────────────────────────────────────────────────

async def deep_analyze_one(client: LLMClient, score: NicheScore) -> AIAnalysis:
    """Deep analysis of a single niche."""
    user_prompt = DEEP_ANALYSIS_USER.format(
        term=score.term,
        total_results=score.total_results,
        videos_30d=score.videos_last_30d,
        video_block=_format_video_block(score),
        channel_block=_format_channel_block(score),
        avg_views=f"{score.avg_views:,.0f}",
        avg_subs=f"{score.avg_channel_subs:,.0f}",
        v2s_ratio=f"{score.view_to_sub_ratio:.1f}",
        small_pct=f"{score.small_channels_pct:.0f}",
        avg_vpd=f"{score.avg_views_per_day:,.0f}",
    )

    try:
        result = await client.complete_json(DEEP_ANALYSIS_SYSTEM, user_prompt)
    except Exception:
        return AIAnalysis(
            term=score.term,
            confidence="unknown",
            quick_rating=0,
            quick_reason="deep analysis failed",
        )

    # Generate briefing in the same call path
    briefing = await _generate_briefing(client, score, result)

    return AIAnalysis(
        term=score.term,
        confidence=result.get("confidence", "unknown"),
        quick_rating=0,
        quick_reason="",
        opportunity_type=result.get("opportunity_type", ""),
        buying_intent_signals=result.get("buying_intent_signals", []),
        competition_summary=result.get("competition_summary", ""),
        timing=result.get("timing", "unknown"),
        monetization_angles=result.get("monetization_angles", []),
        risks=result.get("risks", []),
        action_plan=result.get("action_plan", []),
        full_briefing=briefing,
        model_used=client.model,
        tokens_used=client.total_output_tokens,
    )


async def _generate_briefing(client: LLMClient, score: NicheScore, analysis: dict) -> str:
    """Generate human-readable briefing from analysis data."""
    best_title = score.best_video.title if score.best_video else "N/A"
    best_views = score.best_video.view_count if score.best_video else 0
    best_ch_subs = score.best_video_channel_subs

    user_prompt = BRIEFING_USER.format(
        term=score.term,
        confidence=analysis.get("confidence", "unknown"),
        timing=analysis.get("timing", "unknown"),
        opportunity_type=analysis.get("opportunity_type", ""),
        buying_intent=", ".join(analysis.get("buying_intent_signals", [])),
        monetization=", ".join(analysis.get("monetization_angles", [])),
        risks=", ".join(analysis.get("risks", [])),
        videos_30d=score.videos_last_30d,
        avg_views=f"{score.avg_views:,.0f}",
        avg_subs=f"{score.avg_channel_subs:,.0f}",
        v2s_ratio=f"{score.view_to_sub_ratio:.1f}",
        small_pct=f"{score.small_channels_pct:.0f}",
        best_title=best_title,
        best_views=f"{best_views:,}",
        best_ch_subs=f"{best_ch_subs:,}",
    )

    try:
        return await client.complete(BRIEFING_SYSTEM, user_prompt, max_tokens=1024)
    except Exception:
        return f"Briefing generation failed for '{score.term}'"


async def deep_analyze(
    passed_niches: list[tuple[NicheScore, int, str]],
    max_deep: int = 15,
    on_progress=None,
) -> list[AIAnalysis]:
    """Deep analysis on top niches from Pass 1. Returns AIAnalysis list."""
    client = get_deep_client()

    # Sort by quick rating descending, take top N
    sorted_niches = sorted(passed_niches, key=lambda x: x[1], reverse=True)
    to_analyze = sorted_niches[:max_deep]

    if on_progress:
        on_progress(f"AI Pass 2: Deep analyzing {len(to_analyze)} niches...")

    tasks = [deep_analyze_one(client, score) for score, rating, reason in to_analyze]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    analyses = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            score, rating, reason = to_analyze[i]
            analyses.append(AIAnalysis(
                term=score.term,
                confidence="unknown",
                quick_rating=rating,
                quick_reason=f"Deep analysis failed: {str(result)[:100]}",
            ))
        else:
            result.quick_rating = to_analyze[i][1]
            result.quick_reason = to_analyze[i][2]
            analyses.append(result)

    if on_progress:
        on_progress(f"AI Pass 2 complete: {len(analyses)} niches analyzed")

    return analyses


# ─── Full Pipeline ────────────────────────────────────────────────────────────

async def ai_score_pipeline(
    scores: list[NicheScore],
    max_deep: int = 15,
    on_progress=None,
) -> list[AIAnalysis]:
    """Run the full two-pass AI scoring pipeline on formula-scored niches."""
    if not scores:
        return []

    # Pass 1: Quick filter
    passed = await quick_filter(scores, on_progress=on_progress)

    if not passed:
        if on_progress:
            on_progress("AI Pass 1 filtered out all niches. No opportunities found.")
        return []

    # Pass 2: Deep analysis
    analyses = await deep_analyze(passed, max_deep=max_deep, on_progress=on_progress)

    # Sort by confidence: high > medium > low > unknown
    conf_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    analyses.sort(key=lambda a: (conf_order.get(a.confidence, 3), -a.quick_rating))

    return analyses
