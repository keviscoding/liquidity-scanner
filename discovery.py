import json
import time
import random
import requests
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from models import CandidateNiche
from config import (
    AUTOCOMPLETE_DELAY, AUTOCOMPLETE_MAX_DEPTH, MIN_WORD_COUNT_FOR_CANDIDATE,
    ALL_INTENT_TEMPLATES, EVERGREEN_SEEDS, MONETIZABLE_KEYWORDS, URGENCY_WORDS,
)
from cache import cache_get, cache_set

console = Console()


def fetch_autocomplete(query: str) -> list[str]:
    """Fetch YouTube autocomplete suggestions for a query. FREE, no API quota."""
    cached = cache_get("autocomplete", query)
    if cached is not None:
        return cached

    url = "https://clients1.google.com/complete/search"
    params = {"client": "youtube", "hl": "en", "ds": "yt", "q": query}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        text = resp.text
        start = text.index("(") + 1
        end = text.rindex(")")
        data = json.loads(text[start:end])
        suggestions = [item[0] for item in data[1]] if len(data) > 1 else []
    except Exception:
        suggestions = []

    cache_set("autocomplete", query, suggestions)
    return suggestions


def _polite_delay():
    """Rate limit autocomplete requests."""
    time.sleep(AUTOCOMPLETE_DELAY + random.uniform(0, 0.2))


def expand_with_alphabet(seed: str, progress=None, task_id=None) -> list[str]:
    """Expand a seed term using alphabet trick: seed + ' a' through seed + ' z'."""
    all_suggestions = set()

    base = fetch_autocomplete(seed)
    all_suggestions.update(base)
    _polite_delay()

    for letter in "abcdefghijklmnopqrstuvwxyz":
        query = f"{seed} {letter}"
        suggestions = fetch_autocomplete(query)
        all_suggestions.update(suggestions)
        if progress and task_id:
            progress.advance(task_id)
        _polite_delay()

    return list(all_suggestions)


def discover_seed_niches(verbose: bool = False) -> list[str]:
    """Discover seed niches using INTENT TEMPLATES as primary mechanism.

    Instead of seeding by topic, we seed by intent pattern. Each intent template
    is domain-agnostic — "best script for" naturally discovers gaming scripts,
    productivity macros, music presets, etc. The MARKET fills in the domains.
    """
    seeds = set()
    intent_categories_hit = set()

    # Layer 1 (PRIMARY): Intent templates — domain-agnostic buyer-intent patterns
    # These are the main fishing nets. Each template naturally crosses domains.
    console.print("[cyan]Discovering seeds from intent templates (domain-agnostic)...[/cyan]")

    # Randomly sample templates from each category for diversity
    # (don't run ALL of them every time — be spontaneous)
    templates_to_run = []
    from config import INTENT_TEMPLATES
    for category, template_list in INTENT_TEMPLATES.items():
        # Take 3-5 random templates from each category
        sample_size = min(len(template_list), random.randint(3, 5))
        sampled = random.sample(template_list, sample_size)
        for t in sampled:
            templates_to_run.append((t, category))

    random.shuffle(templates_to_run)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Intent template scanning", total=len(templates_to_run))
        for template, category in templates_to_run:
            suggestions = fetch_autocomplete(template)
            for s in suggestions:
                seeds.add(s.lower().strip())
            intent_categories_hit.add(category)
            progress.advance(task)
            _polite_delay()

    if verbose:
        console.print(f"  [dim]Intent categories covered: {', '.join(intent_categories_hit)}[/dim]")

    # Layer 2: Try pytrends for trending searches (supplementary)
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360)
        trending = pytrends.trending_searches(pn="united_states")
        for term in trending[0].tolist()[:30]:
            term_lower = term.lower()
            if any(kw in term_lower for kw in MONETIZABLE_KEYWORDS):
                seeds.add(term_lower)
    except Exception:
        pass

    # Layer 3: Supplementary evergreen seeds (kept small — intent templates do the heavy lifting)
    for seed in EVERGREEN_SEEDS:
        seeds.add(seed.lower().strip())

    result = sorted(seeds)
    console.print(f"[green]Discovered {len(result)} seed niches across {len(intent_categories_hit)} intent categories[/green]")
    return result


def crawl_autocomplete(
    seed: str,
    max_depth: int = AUTOCOMPLETE_MAX_DEPTH,
    verbose: bool = False,
) -> list[CandidateNiche]:
    """Recursively crawl YouTube autocomplete starting from a seed term."""
    visited = set()
    candidates = []
    queue = [(seed, 0, [seed])]  # (term, depth, parent_chain)

    while queue:
        term, depth, chain = queue.pop(0)
        term_lower = term.lower().strip()

        if term_lower in visited or depth > max_depth:
            continue
        visited.add(term_lower)

        # Get suggestions
        if depth == 0:
            # For the seed itself, use alphabet expansion for thorough coverage
            suggestions = expand_with_alphabet(term_lower)
        else:
            suggestions = fetch_autocomplete(term_lower)
            _polite_delay()

        for s in suggestions:
            s_lower = s.lower().strip()
            if s_lower in visited or s_lower == term_lower:
                continue

            word_count = len(s_lower.split())
            new_chain = chain + [s_lower]

            candidate = CandidateNiche(
                term=s_lower,
                depth=depth + 1,
                word_count=word_count,
                autocomplete_branch_count=0,
                parent_chain=new_chain,
            )
            candidates.append(candidate)

            # Only recurse deeper if term is specific enough
            if depth + 1 < max_depth and word_count >= MIN_WORD_COUNT_FOR_CANDIDATE:
                queue.append((s_lower, depth + 1, new_chain))

    return candidates


def score_branch_counts(candidates: list[CandidateNiche], max_to_check: int = 200) -> list[CandidateNiche]:
    """For the most promising candidates, count how many autocomplete children they spawn."""
    # Sort by word count (prefer specific terms) and take top N
    sorted_candidates = sorted(candidates, key=lambda c: c.word_count, reverse=True)
    to_check = sorted_candidates[:max_to_check]

    console.print(f"[cyan]Scoring branch counts for top {len(to_check)} candidates...[/cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Branch counting", total=len(to_check))
        for candidate in to_check:
            branches = fetch_autocomplete(candidate.term)
            candidate.autocomplete_branch_count = len(branches)
            progress.advance(task)
            _polite_delay()

    return candidates


def rank_candidates(candidates: list[CandidateNiche], top_n: int = 50) -> list[CandidateNiche]:
    """Rank candidates by pre-score and return top N for API analysis."""
    # Deduplicate by term
    seen = {}
    for c in candidates:
        if c.term not in seen or c.pre_score > seen[c.term].pre_score:
            seen[c.term] = c
    unique = list(seen.values())

    # Filter: must have minimum word count and some autocomplete branches
    filtered = [
        c for c in unique
        if c.word_count >= MIN_WORD_COUNT_FOR_CANDIDATE
    ]

    # Sort by pre-score descending
    filtered.sort(key=lambda c: c.pre_score, reverse=True)

    return filtered[:top_n]


def full_discovery(
    max_seeds: int = 30,
    max_depth: int = AUTOCOMPLETE_MAX_DEPTH,
    top_n: int = 50,
    verbose: bool = False,
) -> list[CandidateNiche]:
    """Run the full autonomous discovery pipeline. Zero API cost."""

    # Step 1: Discover seeds
    console.print("\n[bold cyan]Step 1: Discovering seed niches...[/bold cyan]")
    all_seeds = discover_seed_niches(verbose=verbose)
    seeds_to_crawl = all_seeds[:max_seeds]
    console.print(f"Using top {len(seeds_to_crawl)} seeds for crawling\n")

    # Step 2: Crawl autocomplete for each seed
    console.print("[bold cyan]Step 2: Crawling YouTube autocomplete...[/bold cyan]")
    all_candidates = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Seeds crawled", total=len(seeds_to_crawl))
        for seed in seeds_to_crawl:
            candidates = crawl_autocomplete(seed, max_depth=max_depth, verbose=verbose)
            all_candidates.extend(candidates)
            progress.advance(task)
            if verbose:
                console.print(f"  [dim]{seed}: {len(candidates)} candidates[/dim]")

    console.print(f"[green]Found {len(all_candidates)} total candidates[/green]\n")

    # Step 3: Score branch counts on promising candidates
    console.print("[bold cyan]Step 3: Scoring candidate popularity...[/bold cyan]")
    all_candidates = score_branch_counts(all_candidates)

    # Step 4: Rank and return top N
    console.print(f"\n[bold cyan]Step 4: Ranking top {top_n} candidates...[/bold cyan]")
    top = rank_candidates(all_candidates, top_n=top_n)
    console.print(f"[green]Top {len(top)} candidates ready for API analysis[/green]\n")

    return top
