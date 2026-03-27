"""Track niches over time and detect rising/declining trends."""
import database as db
from models import NicheScore, AIAnalysis


def save_snapshots(scan_id: int, scores: list[NicheScore], analyses: list[AIAnalysis] | None = None):
    """Snapshot top niches after a scan for trend tracking."""
    ai_map = {}
    if analyses:
        ai_map = {a.term.lower(): a for a in analyses}

    for s in scores[:30]:  # Top 30
        ai = ai_map.get(s.term.lower())
        db.save_trend_snapshot(
            scan_id=scan_id,
            term=s.term,
            overall_score=s.overall_score,
            videos_30d=s.videos_last_30d,
            avg_views=s.avg_views,
            avg_subs=s.avg_channel_subs,
            ai_confidence=ai.confidence if ai else "",
        )


def detect_risers() -> list[dict]:
    """Find niches where metrics are improving scan-over-scan."""
    trends = db.get_all_trends(min_snapshots=2)
    risers = []

    for t in trends:
        history = db.get_trend_history(t["term"], limit=2)
        if len(history) < 2:
            continue

        current = history[0]  # Most recent
        previous = history[1]  # Previous

        score_delta = (current["overall_score"] or 0) - (previous["overall_score"] or 0)
        views_prev = previous["avg_views"] or 1
        views_delta_pct = ((current["avg_views"] or 0) - views_prev) / views_prev * 100
        vids_prev = previous["videos_30d"] or 1
        vids_delta_pct = ((current["videos_30d"] or 0) - vids_prev) / vids_prev * 100

        direction = "stable"
        if vids_delta_pct > 50 or views_delta_pct > 30 or score_delta > 10:
            direction = "rising"
        elif vids_delta_pct < -30 or views_delta_pct < -30 or score_delta < -10:
            direction = "declining"

        if direction != "stable":
            risers.append({
                "term": t["term"],
                "direction": direction,
                "current_score": current["overall_score"],
                "previous_score": previous["overall_score"],
                "score_delta": round(score_delta, 1),
                "views_delta_pct": round(views_delta_pct, 1),
                "vids_delta_pct": round(vids_delta_pct, 1),
                "current_videos": current["videos_30d"],
                "current_views": current["avg_views"],
                "snapshot_count": t["snapshot_count"],
                "first_seen": t["first_seen"],
            })

    risers.sort(key=lambda r: r["score_delta"], reverse=True)
    return risers


def detect_newcomers(scan_id: int) -> list[str]:
    """Find terms in this scan that never appeared in any previous scan."""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT term FROM niche_results WHERE scan_id=?
            AND lower(term) NOT IN (
                SELECT DISTINCT lower(term) FROM trend_snapshots WHERE scan_id != ?
            )
        """, (scan_id, scan_id)).fetchall()
        return [r["term"] for r in rows]


def get_terms_for_rescan(top_n: int = 20) -> list[str]:
    """Get best terms from past scans to re-check."""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT term, MAX(overall_score) as best_score, MAX(snapshot_at) as last_seen
            FROM trend_snapshots
            GROUP BY lower(term)
            ORDER BY best_score DESC
            LIMIT ?
        """, (top_n,)).fetchall()
        return [r["term"] for r in rows]
