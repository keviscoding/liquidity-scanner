import csv
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import BarColumn, Progress, TextColumn
from rich.columns import Columns
from rich import box

from models import NicheScore, CandidateNiche
from config import RESULTS_DIR, DAILY_QUOTA_LIMIT
import quota as quota_tracker

console = Console()


def _score_color(score: float) -> str:
    if score >= 80:
        return "bold green"
    elif score >= 60:
        return "green"
    elif score >= 40:
        return "yellow"
    elif score >= 20:
        return "red"
    return "dim red"


def render_header():
    usage = quota_tracker.get_usage()
    remaining = quota_tracker.get_remaining_quota()
    pct = (usage["units_used"] / DAILY_QUOTA_LIMIT) * 100

    if pct < 50:
        bar_color = "green"
    elif pct < 80:
        bar_color = "yellow"
    else:
        bar_color = "red"

    header = Text()
    header.append("YOUTUBE LIQUIDITY SCANNER", style="bold cyan")
    header.append(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M')}", style="dim")
    header.append(f"  |  Quota: {remaining:,}/{DAILY_QUOTA_LIMIT:,} remaining", style="dim")
    header.append(f"  |  Searches used: {usage['searches_made']}", style="dim")

    bar_filled = int(pct / 2)
    bar_empty = 50 - bar_filled
    bar = f"[{bar_color}]{'█' * bar_filled}[/{bar_color}][dim]{'░' * bar_empty}[/dim] {pct:.0f}%"

    console.print(Panel(header, border_style="cyan"))
    console.print(f"  Quota: {bar}\n")


def render_results_table(scores: list[NicheScore]):
    if not scores:
        console.print("[yellow]No results to display.[/yellow]")
        return

    table = Table(
        title="TOP NICHES BY LIQUIDITY SCORE",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Search Term", min_width=30, max_width=45)
    table.add_column("SCORE", justify="center", width=7)
    table.add_column("Liq", justify="center", width=5)
    table.add_column("Vel", justify="center", width=5)
    table.add_column("Rec", justify="center", width=5)
    table.add_column("Comp", justify="center", width=5)
    table.add_column("Spec", justify="center", width=5)
    table.add_column("Vids", justify="right", width=5)
    table.add_column("Avg Views", justify="right", width=10)
    table.add_column("Avg Subs", justify="right", width=10)
    table.add_column("V/S Ratio", justify="right", width=9)

    for i, s in enumerate(scores, 1):
        table.add_row(
            str(i),
            s.term,
            f"[{_score_color(s.overall_score)}]{s.overall_score:.1f}[/]",
            f"[{_score_color(s.liquidity_score)}]{s.liquidity_score:.0f}[/]",
            f"[{_score_color(s.velocity_score)}]{s.velocity_score:.0f}[/]",
            f"[{_score_color(s.recency_score)}]{s.recency_score:.0f}[/]",
            f"[{_score_color(s.competition_score)}]{s.competition_score:.0f}[/]",
            f"[{_score_color(s.specificity_score)}]{s.specificity_score:.0f}[/]",
            str(s.videos_last_30d),
            f"{s.avg_views:,.0f}",
            f"{s.avg_channel_subs:,.0f}",
            f"{s.view_to_sub_ratio:.1f}x",
        )

    console.print(table)


def render_detail(score: NicheScore):
    """Render expanded detail for a single niche."""
    lines = [
        f"[bold]{score.term}[/bold]",
        "",
        f"Overall: [{_score_color(score.overall_score)}]{score.overall_score:.1f}[/]  |  "
        f"Liquidity: [{_score_color(score.liquidity_score)}]{score.liquidity_score:.0f}[/]  |  "
        f"Velocity: [{_score_color(score.velocity_score)}]{score.velocity_score:.0f}[/]  |  "
        f"Recency: [{_score_color(score.recency_score)}]{score.recency_score:.0f}[/]",
        "",
        f"Videos (30d): {score.videos_last_30d}  |  "
        f"Avg views: {score.avg_views:,.0f}  |  "
        f"Avg views/day: {score.avg_views_per_day:,.0f}",
        f"Avg channel subs: {score.avg_channel_subs:,.0f}  |  "
        f"Small channels: {score.small_channels_pct:.0f}%  |  "
        f"View/Sub ratio: {score.view_to_sub_ratio:.1f}x",
    ]

    if score.best_video:
        lines.extend([
            "",
            f"[green]Best video:[/green] {score.best_video.title}",
            f"  Views: {score.best_video.view_count:,}  |  "
            f"Channel: {score.best_video.channel_title} ({score.best_video_channel_subs:,} subs)",
        ])

    if score.parent_chain:
        lines.extend(["", f"[dim]Discovery path: {' -> '.join(score.parent_chain)}[/dim]"])

    console.print(Panel("\n".join(lines), border_style="green", title="Niche Detail"))


def render_discovery_preview(candidates: list[CandidateNiche], top_n: int = 30):
    """Show a preview of discovered candidates (dry-run mode)."""
    table = Table(
        title="TOP CANDIDATES (Pre-API Score)",
        box=box.ROUNDED,
        title_style="bold yellow",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Search Term", min_width=30, max_width=50)
    table.add_column("Pre-Score", justify="center", width=10)
    table.add_column("Words", justify="center", width=6)
    table.add_column("Branches", justify="center", width=9)
    table.add_column("Depth", justify="center", width=6)
    table.add_column("Discovery Path", max_width=50)

    for i, c in enumerate(candidates[:top_n], 1):
        table.add_row(
            str(i),
            c.term,
            f"[{_score_color(c.pre_score)}]{c.pre_score:.1f}[/]",
            str(c.word_count),
            str(c.autocomplete_branch_count),
            str(c.depth),
            " -> ".join(c.parent_chain[-3:]) if c.parent_chain else "",
        )

    console.print(table)


def export_csv(scores: list[NicheScore], output_path: str | None = None) -> str:
    """Export results to CSV. Returns the file path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path:
        path = Path(output_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RESULTS_DIR / f"scan_{timestamp}.csv"

    fieldnames = [
        "rank", "term", "overall_score", "liquidity_score", "velocity_score",
        "recency_score", "competition_score", "specificity_score",
        "total_results", "videos_last_30d", "avg_views", "avg_views_per_day",
        "avg_channel_subs", "view_to_sub_ratio", "small_channels_pct",
        "best_video_title", "best_video_views", "best_video_channel_subs",
        "parent_chain", "scanned_at",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, s in enumerate(scores, 1):
            writer.writerow({
                "rank": i,
                "term": s.term,
                "overall_score": s.overall_score,
                "liquidity_score": s.liquidity_score,
                "velocity_score": s.velocity_score,
                "recency_score": s.recency_score,
                "competition_score": s.competition_score,
                "specificity_score": s.specificity_score,
                "total_results": s.total_results,
                "videos_last_30d": s.videos_last_30d,
                "avg_views": s.avg_views,
                "avg_views_per_day": s.avg_views_per_day,
                "avg_channel_subs": s.avg_channel_subs,
                "view_to_sub_ratio": s.view_to_sub_ratio,
                "small_channels_pct": s.small_channels_pct,
                "best_video_title": s.best_video.title if s.best_video else "",
                "best_video_views": s.best_video.view_count if s.best_video else 0,
                "best_video_channel_subs": s.best_video_channel_subs,
                "parent_chain": " | ".join(s.parent_chain),
                "scanned_at": s.searched_at.isoformat(),
            })

    return str(path)


def render_full_dashboard(scores: list[NicheScore], export: bool = True) -> str | None:
    """Render the complete dashboard and optionally export CSV."""
    console.print()
    render_header()
    render_results_table(scores)

    # Show details for top 5
    if scores:
        console.print(f"\n[bold cyan]Top {min(5, len(scores))} Niche Details:[/bold cyan]\n")
        for s in scores[:5]:
            render_detail(s)
            console.print()

    csv_path = None
    if export and scores:
        csv_path = export_csv(scores)
        console.print(f"[green]Results exported to: {csv_path}[/green]")

    return csv_path
