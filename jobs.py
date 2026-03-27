"""Background job runner for scans."""
import threading
from datetime import datetime

import database as db
from discovery import crawl_autocomplete, score_branch_counts, rank_candidates, discover_seed_niches
from analyzer import analyze_candidates, _get_youtube_client
from models import CandidateNiche
import quota as quota_tracker

# Active job threads keyed by scan_id
_active_jobs: dict[int, threading.Thread] = {}


def _progress(scan_id: int, msg: str, step: str = "", pct: int = 0):
    db.add_progress(scan_id, msg, step, pct)


def _run_scan(scan_id: int, config: dict):
    try:
        db.update_scan_status(scan_id, "running")
        dry_run = config.get("dry_run", False)
        max_searches = config.get("max_searches", 50)
        max_seeds = config.get("max_seeds", 25)
        max_depth = config.get("max_depth", 3)
        extra_seeds = config.get("extra_seeds", [])

        # Step 1: Discover seeds
        _progress(scan_id, "Discovering seed niches from trending data...", "discover", 5)
        seeds = discover_seed_niches(verbose=False)
        if extra_seeds:
            seeds = list(set(seeds + [s.lower().strip() for s in extra_seeds]))
        seeds = seeds[:max_seeds]
        _progress(scan_id, f"Found {len(seeds)} seed niches to crawl", "discover", 10)

        # Step 2: Crawl autocomplete
        _progress(scan_id, f"Crawling YouTube autocomplete for {len(seeds)} seeds...", "crawl", 12)
        all_candidates = []
        for i, seed in enumerate(seeds):
            pct = 12 + int((i / len(seeds)) * 35)
            _progress(scan_id, f"Crawling: {seed}", "crawl", pct)
            candidates = crawl_autocomplete(seed, max_depth=max_depth)
            all_candidates.extend(candidates)

        _progress(scan_id, f"Found {len(all_candidates)} candidate niches total", "crawl", 48)

        # Step 3: Score branch counts
        _progress(scan_id, "Scoring candidate popularity via autocomplete...", "score", 50)
        all_candidates = score_branch_counts(all_candidates, max_to_check=200)

        # Step 4: Rank
        _progress(scan_id, f"Ranking top {max_searches} candidates...", "rank", 65)
        top_candidates = rank_candidates(all_candidates, top_n=max_searches)

        if dry_run:
            # Save candidates as placeholder results
            _progress(scan_id, f"Dry run complete. Top {len(top_candidates)} candidates ranked.", "done", 100)
            # Convert candidates to fake NicheScore objects for display
            from models import NicheScore
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

        # Step 5: API analysis
        remaining = quota_tracker.get_remaining_quota()
        _progress(scan_id, f"Starting API analysis. Quota remaining: {remaining:,} units", "analyze", 68)

        scores = []
        for i, candidate in enumerate(top_candidates):
            if not quota_tracker.can_afford(102):
                _progress(scan_id, "Quota exhausted. Stopping analysis.", "analyze", 90)
                break
            pct = 68 + int((i / max(len(top_candidates), 1)) * 27)
            _progress(scan_id, f"Analyzing: {candidate.term}", "analyze", pct)

            from analyzer import analyze_niche
            try:
                youtube = _get_youtube_client()
                score = analyze_niche(youtube, candidate)
                if score:
                    scores.append(score)
            except Exception as e:
                _progress(scan_id, f"Error on '{candidate.term}': {str(e)[:80]}", "analyze", pct)

        scores.sort(key=lambda s: s.overall_score, reverse=True)

        _progress(scan_id, f"Scan complete! Found {len(scores)} scored niches.", "done", 100)
        db.save_results(scan_id, scores)
        db.update_scan_status(scan_id, "completed")

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
