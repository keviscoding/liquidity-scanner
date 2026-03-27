#!/usr/bin/env python3
"""YouTube Liquidity Scanner - Find high-liquidity micro-niches on YouTube."""

import signal
import sys
from pathlib import Path

import click
from rich.console import Console

from config import ensure_dirs, MAX_SEARCHES_PER_RUN, AUTOCOMPLETE_MAX_DEPTH, RESULTS_DIR
from discovery import full_discovery, crawl_autocomplete, score_branch_counts, rank_candidates
from analyzer import analyze_candidates
from dashboard import (
    render_full_dashboard, render_header, render_discovery_preview,
    render_results_table, export_csv,
)
import quota as quota_tracker

console = Console()

# Store partial results for graceful shutdown
_partial_results = []


def _handle_interrupt(signum, frame):
    """Handle Ctrl+C gracefully - save partial results."""
    console.print("\n[yellow]Interrupted! Saving partial results...[/yellow]")
    if _partial_results:
        from dashboard import render_full_dashboard
        render_full_dashboard(_partial_results, export=True)
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_interrupt)


@click.group()
def cli():
    """YouTube Liquidity Scanner - Find high-liquidity micro-niches."""
    ensure_dirs()


@cli.command()
@click.option("--max-searches", default=MAX_SEARCHES_PER_RUN, help="Max API searches to use")
@click.option("--max-depth", default=AUTOCOMPLETE_MAX_DEPTH, help="Autocomplete crawl depth")
@click.option("--max-seeds", default=30, help="Max seed niches to crawl")
@click.option("--seeds", default="", help="Comma-separated additional seed terms")
@click.option("--dry-run", is_flag=True, help="Discovery only, no API calls (free)")
@click.option("--export/--no-export", default=True, help="Export results to CSV")
@click.option("--output", default=None, help="CSV output path")
@click.option("--verbose", is_flag=True, help="Show detailed progress")
def scan(max_searches, max_depth, max_seeds, seeds, dry_run, export, output, verbose):
    """Full autonomous scan: discover seeds, crawl autocomplete, score niches."""
    global _partial_results

    console.print("\n[bold cyan]YouTube Liquidity Scanner[/bold cyan]")
    console.print("[dim]Finding high-liquidity micro-niches...[/dim]\n")

    # Check quota
    if not dry_run:
        remaining = quota_tracker.get_remaining_quota()
        if remaining < 200:
            console.print(f"[red]Only {remaining} quota units remaining. Use --dry-run or wait for reset.[/red]")
            return

    # Step 1-4: Discovery (free)
    candidates = full_discovery(
        max_seeds=max_seeds,
        max_depth=max_depth,
        top_n=max_searches,
        verbose=verbose,
    )

    # Add user-provided seeds if any
    if seeds:
        extra_seeds = [s.strip() for s in seeds.split(",") if s.strip()]
        for seed in extra_seeds:
            console.print(f"[cyan]Crawling extra seed: {seed}[/cyan]")
            extra = crawl_autocomplete(seed, max_depth=max_depth)
            extra = score_branch_counts(extra, max_to_check=50)
            candidates.extend(rank_candidates(extra, top_n=10))

    if dry_run:
        console.print("\n[bold yellow]DRY RUN - Showing discovery results (no API cost)[/bold yellow]\n")
        render_header()
        render_discovery_preview(candidates, top_n=50)
        if export:
            # Export candidates as simple CSV
            import csv
            ensure_dirs()
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = RESULTS_DIR / f"dryrun_{timestamp}.csv"
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["rank", "term", "pre_score", "word_count", "branches", "depth", "discovery_path"])
                for i, c in enumerate(candidates[:100], 1):
                    writer.writerow([
                        i, c.term, round(c.pre_score, 1), c.word_count,
                        c.autocomplete_branch_count, c.depth,
                        " | ".join(c.parent_chain[-3:]),
                    ])
            console.print(f"\n[green]Candidates exported to: {path}[/green]")
        return

    # Step 5: API analysis
    scores = analyze_candidates(candidates, max_searches=max_searches)
    _partial_results = scores

    # Step 6: Dashboard + export
    render_full_dashboard(scores, export=export)


@cli.command()
@click.argument("term")
@click.option("--depth", default=AUTOCOMPLETE_MAX_DEPTH, help="Crawl depth")
@click.option("--analyze", is_flag=True, help="Also run API analysis on top candidates")
@click.option("--top", default=10, help="Number of top candidates to show/analyze")
def explore(term, depth, analyze, top):
    """Explore a single seed term's autocomplete tree."""
    console.print(f"\n[bold cyan]Exploring: {term}[/bold cyan]\n")

    candidates = crawl_autocomplete(term, max_depth=depth)
    console.print(f"[green]Found {len(candidates)} candidates[/green]\n")

    candidates = score_branch_counts(candidates, max_to_check=min(100, len(candidates)))
    ranked = rank_candidates(candidates, top_n=top)

    render_discovery_preview(ranked, top_n=top)

    if analyze:
        console.print()
        scores = analyze_candidates(ranked, max_searches=top)
        if scores:
            render_results_table(scores)
            for s in scores[:3]:
                from dashboard import render_detail
                render_detail(s)


@cli.command()
def quota():
    """Show today's API quota usage."""
    render_header()
    usage = quota_tracker.get_usage()
    console.print(f"  Date: {usage['date']}")
    console.print(f"  Units used: {usage['units_used']:,}")
    console.print(f"  Searches made: {usage['searches_made']}")
    console.print(f"  Remaining: {quota_tracker.get_remaining_quota():,} units")
    console.print(f"  Remaining searches: {quota_tracker.get_remaining_searches()}")

    if usage.get("calls"):
        console.print(f"\n  Last 5 API calls:")
        for call in usage["calls"][-5:]:
            console.print(f"    {call['endpoint']} ({call['cost']} units) - {call.get('timestamp', '')}")


@cli.command()
def history():
    """List past scan results."""
    ensure_dirs()
    csvs = sorted(RESULTS_DIR.glob("*.csv"), reverse=True)

    if not csvs:
        console.print("[yellow]No scan results found.[/yellow]")
        return

    from rich.table import Table
    table = Table(title="Scan History")
    table.add_column("File", min_width=30)
    table.add_column("Size", justify="right")
    table.add_column("Modified", width=20)

    for f in csvs[:20]:
        stat = f.stat()
        table.add_row(
            f.name,
            f"{stat.st_size:,} bytes",
            f"{stat.st_mtime:.0f}",
        )

    console.print(table)


if __name__ == "__main__":
    cli()
