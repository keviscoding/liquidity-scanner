"""Background job runner for scans — standard, agent, and rescan modes."""
import asyncio
import threading
from datetime import datetime

import database as db
from discovery import crawl_autocomplete, score_branch_counts, rank_candidates, discover_seed_niches
from analyzer import analyze_candidates, _get_youtube_client, analyze_niche
from models import CandidateNiche, NicheScore
from config import AI_SCORING_ENABLED, LLM_API_KEY
import quota as quota_tracker

_active_jobs: dict[int, threading.Thread] = {}


def _progress(scan_id: int, msg: str, step: str = "", pct: int = 0):
    db.add_progress(scan_id, msg, step, pct)


def _ai_available() -> bool:
    return AI_SCORING_ENABLED and bool(LLM_API_KEY)


# ─── Standard Scan ────────────────────────────────────────────────────────────

async def _run_standard_async(scan_id: int, config: dict):
    dry_run = config.get("dry_run", False)
    max_searches = config.get("max_searches", 50)
    max_seeds = config.get("max_seeds", 25)
    max_depth = config.get("max_depth", 3)
    extra_seeds = config.get("extra_seeds", [])

    # Step 1: Discover seeds (combine hardcoded + AI-generated for maximum diversity)
    _progress(scan_id, "Discovering seed niches from trending data...", "discover", 3)
    seeds = discover_seed_niches(verbose=False)

    # Add AI-generated random seeds for spontaneous discovery
    if _ai_available():
        _progress(scan_id, "AI generating surprising seed niches...", "discover", 5)
        try:
            from ai_agent import generate_random_seeds
            from ai_client import get_fast_client
            ai_seeds = await generate_random_seeds(get_fast_client())
            seeds = list(set(seeds + ai_seeds))
            _progress(scan_id, f"AI added {len(ai_seeds)} diverse seeds", "discover", 7)
        except Exception:
            pass

    if extra_seeds:
        seeds = list(set(seeds + [s.lower().strip() for s in extra_seeds]))
    seeds = seeds[:max_seeds]
    _progress(scan_id, f"Found {len(seeds)} seed niches to crawl", "discover", 8)

    # Step 2: Crawl autocomplete
    _progress(scan_id, f"Crawling YouTube autocomplete for {len(seeds)} seeds...", "crawl", 10)
    all_candidates = []
    for i, seed in enumerate(seeds):
        pct = 10 + int((i / len(seeds)) * 30)
        _progress(scan_id, f"Crawling: {seed}", "crawl", pct)
        candidates = crawl_autocomplete(seed, max_depth=max_depth)
        all_candidates.extend(candidates)

    _progress(scan_id, f"Found {len(all_candidates)} candidate niches total", "crawl", 42)

    # Step 3: Score branch counts
    _progress(scan_id, "Scoring candidate popularity via autocomplete...", "score", 44)
    all_candidates = score_branch_counts(all_candidates, max_to_check=200)

    # Step 4: Rank
    _progress(scan_id, f"Ranking top {max_searches} candidates...", "rank", 55)
    top_candidates = rank_candidates(all_candidates, top_n=max_searches)

    if dry_run:
        _progress(scan_id, f"Dry run complete. Top {len(top_candidates)} candidates ranked.", "done", 100)
        scores = [
            NicheScore(
                term=c.term,
                overall_score=round(c.pre_score, 1),
                specificity_score=min(100, c.word_count * 20),
                competition_score=min(100, c.autocomplete_branch_count * 10),
                parent_chain=c.parent_chain,
            )
            for c in top_candidates
        ]
        db.save_results(scan_id, scores)
        db.update_scan_status(scan_id, "completed")
        return

    # Step 5: YouTube API analysis
    remaining = quota_tracker.get_remaining_quota()
    _progress(scan_id, f"YouTube API analysis. Quota: {remaining:,} units", "analyze", 58)

    scores = []
    youtube = _get_youtube_client()
    for i, candidate in enumerate(top_candidates):
        if not quota_tracker.can_afford(102):
            _progress(scan_id, "Quota exhausted.", "analyze", 80)
            break
        pct = 58 + int((i / max(len(top_candidates), 1)) * 22)
        _progress(scan_id, f"Analyzing: {candidate.term}", "analyze", pct)
        try:
            score = analyze_niche(youtube, candidate)
            if score:
                scores.append(score)
        except Exception as e:
            _progress(scan_id, f"Error: {candidate.term}: {str(e)[:60]}", "analyze", pct)

    scores.sort(key=lambda s: s.overall_score, reverse=True)
    _progress(scan_id, f"Formula scoring done: {len(scores)} niches", "analyze", 82)
    db.save_results(scan_id, scores)

    # Step 6: AI scoring (if enabled)
    ai_analyses = []
    if _ai_available() and scores:
        _progress(scan_id, "AI Pass 1: Filtering niches with Claude...", "ai", 84)
        try:
            from ai_scorer import ai_score_pipeline
            ai_analyses = await ai_score_pipeline(
                scores,
                max_deep=15,
                on_progress=lambda msg: _progress(scan_id, msg, "ai", 0),
            )
            _progress(scan_id, f"AI analysis complete: {len(ai_analyses)} niches analyzed", "ai", 94)
            db.save_ai_analyses(scan_id, ai_analyses)
        except Exception as e:
            _progress(scan_id, f"AI scoring error (results saved without AI): {str(e)[:80]}", "ai", 94)

    # Step 7: Save trend snapshots
    try:
        from trend_tracker import save_snapshots
        save_snapshots(scan_id, scores, ai_analyses)
    except Exception:
        pass

    _progress(scan_id, f"Scan complete! {len(scores)} niches scored, {len(ai_analyses)} AI-analyzed.", "done", 100)
    db.update_scan_status(scan_id, "completed")


# ─── Agent Scan ───────────────────────────────────────────────────────────────

async def _run_agent_async(scan_id: int, config: dict):
    direction = config.get("agent_direction", "")
    max_iterations = config.get("agent_max_iterations", 8)
    max_youtube = config.get("agent_max_youtube", 5)

    if not direction:
        _progress(scan_id, "Error: No exploration direction provided.", "error", 0)
        db.update_scan_status(scan_id, "failed", error="No direction")
        return

    if not _ai_available():
        _progress(scan_id, "Error: LLM_API_KEY required for agent mode.", "error", 0)
        db.update_scan_status(scan_id, "failed", error="No LLM key")
        return

    # Step 1: Run agent
    _progress(scan_id, f"Agent exploring: '{direction}'", "agent", 5)

    from ai_client import get_fast_client
    from ai_agent import NicheAgent

    llm = get_fast_client()

    def on_step(step):
        pct = min(45, 5 + step.step_number * 5)
        _progress(scan_id, f"Agent [{step.action}]: {step.reasoning[:80]}", "agent", pct)

    agent = NicheAgent(
        llm=llm,
        direction=direction,
        max_iterations=max_iterations,
        max_youtube_searches=max_youtube,
        on_step=on_step,
    )
    candidates = await agent.run()

    _progress(scan_id, f"Agent found {len(candidates)} candidates in {len(agent.steps)} steps", "agent", 48)
    db.save_agent_session(scan_id, direction, agent.steps, len(candidates))

    if not candidates:
        _progress(scan_id, "Agent found no candidates. Try a different direction.", "done", 100)
        db.update_scan_status(scan_id, "completed")
        return

    # Step 2: Score branch counts on agent's candidates
    _progress(scan_id, "Scoring agent candidates...", "score", 50)
    candidates = score_branch_counts(candidates, max_to_check=min(100, len(candidates)))
    top_candidates = rank_candidates(candidates, top_n=config.get("max_searches", 30))

    # Step 3: YouTube API analysis
    _progress(scan_id, f"YouTube API on top {len(top_candidates)} candidates...", "analyze", 55)
    scores = []
    youtube = _get_youtube_client()
    for i, candidate in enumerate(top_candidates):
        if not quota_tracker.can_afford(102):
            break
        pct = 55 + int((i / max(len(top_candidates), 1)) * 25)
        _progress(scan_id, f"Analyzing: {candidate.term}", "analyze", pct)
        try:
            score = analyze_niche(youtube, candidate)
            if score:
                scores.append(score)
        except Exception:
            pass

    scores.sort(key=lambda s: s.overall_score, reverse=True)
    db.save_results(scan_id, scores)
    _progress(scan_id, f"API scoring done: {len(scores)} niches", "analyze", 82)

    # Step 4: AI deep analysis
    ai_analyses = []
    if scores:
        _progress(scan_id, "AI analyzing agent discoveries...", "ai", 84)
        try:
            from ai_scorer import ai_score_pipeline
            ai_analyses = await ai_score_pipeline(scores, max_deep=15,
                on_progress=lambda msg: _progress(scan_id, msg, "ai", 0))
            db.save_ai_analyses(scan_id, ai_analyses)
        except Exception as e:
            _progress(scan_id, f"AI error: {str(e)[:60]}", "ai", 92)

    try:
        from trend_tracker import save_snapshots
        save_snapshots(scan_id, scores, ai_analyses)
    except Exception:
        pass

    _progress(scan_id, f"Agent scan complete! {len(scores)} niches, {len(ai_analyses)} AI-analyzed.", "done", 100)
    db.update_scan_status(scan_id, "completed")


# ─── Rescan Mode ──────────────────────────────────────────────────────────────

async def _run_rescan_async(scan_id: int, config: dict):
    from trend_tracker import get_terms_for_rescan, save_snapshots, detect_risers

    _progress(scan_id, "Loading previous top niches for re-check...", "discover", 5)
    terms = get_terms_for_rescan(top_n=20)

    if not terms:
        _progress(scan_id, "No previous scans to re-check. Run a standard scan first.", "done", 100)
        db.update_scan_status(scan_id, "completed")
        return

    _progress(scan_id, f"Re-scanning {len(terms)} previous top niches...", "analyze", 10)

    # Convert terms to candidates and analyze
    candidates = [CandidateNiche(term=t, depth=0, word_count=len(t.split())) for t in terms]
    scores = []
    youtube = _get_youtube_client()
    for i, c in enumerate(candidates):
        if not quota_tracker.can_afford(102):
            break
        pct = 10 + int((i / len(candidates)) * 60)
        _progress(scan_id, f"Re-scanning: {c.term}", "analyze", pct)
        try:
            score = analyze_niche(youtube, c)
            if score:
                scores.append(score)
        except Exception:
            pass

    scores.sort(key=lambda s: s.overall_score, reverse=True)
    db.save_results(scan_id, scores)

    # AI analysis on all (they're pre-vetted, worth deep analysis)
    ai_analyses = []
    if _ai_available() and scores:
        _progress(scan_id, "AI analyzing re-scanned niches...", "ai", 75)
        try:
            from ai_scorer import ai_score_pipeline
            ai_analyses = await ai_score_pipeline(scores, max_deep=20,
                on_progress=lambda msg: _progress(scan_id, msg, "ai", 0))
            db.save_ai_analyses(scan_id, ai_analyses)
        except Exception:
            pass

    save_snapshots(scan_id, scores, ai_analyses)

    risers = detect_risers()
    rising_count = sum(1 for r in risers if r["direction"] == "rising")
    declining_count = sum(1 for r in risers if r["direction"] == "declining")

    _progress(scan_id,
              f"Rescan complete! {len(scores)} niches. {rising_count} rising, {declining_count} declining.",
              "done", 100)
    db.update_scan_status(scan_id, "completed")


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def _run_scan(scan_id: int, config: dict):
    try:
        db.update_scan_status(scan_id, "running")
        scan_type = config.get("scan_type", "standard")

        if scan_type == "agent":
            asyncio.run(_run_agent_async(scan_id, config))
        elif scan_type == "rescan":
            asyncio.run(_run_rescan_async(scan_id, config))
        else:
            asyncio.run(_run_standard_async(scan_id, config))

    except Exception as e:
        db.add_progress(scan_id, f"Fatal error: {str(e)}", "error", 0)
        db.update_scan_status(scan_id, "failed", error=str(e))
    finally:
        _active_jobs.pop(scan_id, None)


def start_scan(scan_id: int, config: dict):
    t = threading.Thread(target=_run_scan, args=(scan_id, config), daemon=True)
    _active_jobs[scan_id] = t
    t.start()


def is_running(scan_id: int) -> bool:
    t = _active_jobs.get(scan_id)
    return t is not None and t.is_alive()
