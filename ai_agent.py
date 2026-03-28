"""Agentic YouTube niche explorer — autonomous browsing with AI judgment."""
import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Callable

from ai_client import LLMClient, get_fast_client
from ai_prompts import (
    AGENT_HYPOTHESIS_SYSTEM, AGENT_HYPOTHESIS_USER,
    AGENT_DECIDE_SYSTEM, AGENT_DECIDE_USER,
    AGENT_REFLECT_SYSTEM, AGENT_REFLECT_USER,
    RANDOM_EXPLORE_SYSTEM, RANDOM_EXPLORE_USER,
)
from models import CandidateNiche, AgentStep
from discovery import fetch_autocomplete, expand_with_alphabet, crawl_autocomplete


async def generate_random_seeds(llm: LLMClient) -> list[str]:
    """Use AI to generate diverse, surprising seed niches autonomously."""
    try:
        result = await llm.complete_json(RANDOM_EXPLORE_SYSTEM, RANDOM_EXPLORE_USER)
        seeds = []
        items = result if isinstance(result, list) else result.get("seeds", result.get("niches", [result]))
        for item in items:
            if isinstance(item, dict):
                seed = item.get("seed") or item.get("term") or item.get("niche") or ""
                if seed:
                    seeds.append(seed.lower().strip())
            elif isinstance(item, str):
                seeds.append(item.lower().strip())
        return seeds if seeds else ["smart home device", "music production plugin", "fitness tracker app"]
    except Exception:
        return ["smart home device", "music production plugin", "fitness tracker app"]


class NicheAgent:
    """Autonomous agent that explores YouTube niches with AI judgment."""

    def __init__(
        self,
        llm: LLMClient,
        direction: str,
        max_iterations: int = 8,
        max_youtube_searches: int = 5,
        on_step: Callable[[AgentStep], None] | None = None,
    ):
        self.llm = llm
        self.direction = direction
        self.max_iterations = max_iterations
        self.max_youtube_searches = max_youtube_searches
        self.on_step = on_step

        self.steps: list[AgentStep] = []
        self.discovered_candidates: list[CandidateNiche] = []
        self.youtube_budget_used = 0
        self._context_log: list[str] = []
        self._promising_terms: list[str] = []
        self._explored_areas: list[str] = []  # Track which areas we've explored
        self._steps_in_current_area = 0  # Force pivot after 3 steps in one area

    async def run(self) -> list[CandidateNiche]:
        """Execute the agentic exploration loop."""

        # Step 1: Generate hypotheses
        hypotheses = await self._generate_hypotheses()
        self._context_log.append(
            f"Generated {len(hypotheses)} hypotheses from direction: '{self.direction}'"
        )
        for h in hypotheses:
            self._context_log.append(f"  Hypothesis: {h.get('hypothesis', '')}")
            for t in h.get("search_terms", []):
                self._promising_terms.append(t)

        self._log_step(0, "hypothesize", "Generated initial exploration hypotheses",
                       self.direction, json.dumps(hypotheses, indent=2)[:500])

        # Step 2: Main exploration loop
        last_action = "Generated hypotheses"
        last_findings = f"{len(hypotheses)} hypotheses with {len(self._promising_terms)} search terms"

        for iteration in range(1, self.max_iterations + 1):
            remaining_yt = self.max_youtube_searches - self.youtube_budget_used

            # Force diversity: after 3 steps in one area, pivot to something new
            self._steps_in_current_area += 1

            # CHAOS MODE: 30% chance of completely random jump to a new area
            # This mimics how humans discover opportunities — by stumbling into unexpected places
            if self._steps_in_current_area > 1 and random.random() < 0.30:
                from config import ALL_INTENT_TEMPLATES
                random_template, random_category = random.choice(ALL_INTENT_TEMPLATES)
                decision = {
                    "type": "explore_autocomplete",
                    "query": random_template,
                    "reasoning": f"CHAOS JUMP — randomly exploring '{random_template}' ({random_category}) to discover unexpected niches"
                }
                self._steps_in_current_area = 0
                self._explored_areas.append(f"chaos:{random_category}")
            elif self._steps_in_current_area > 3:
                decision = {"type": "pivot", "query": "", "reasoning": "Forced diversity pivot — explored this area enough, moving to a new direction"}
                self._steps_in_current_area = 0
            else:
                decision = await self._decide_next_action(iteration, remaining_yt, last_action, last_findings)

            action_type = decision.get("type", "done")
            query = decision.get("query", "")
            reasoning = decision.get("reasoning", "")

            if action_type == "done":
                self._log_step(iteration, "done", reasoning, "", "Agent decided to stop")
                break

            elif action_type == "explore_autocomplete":
                results = fetch_autocomplete(query)
                findings = f"Autocomplete for '{query}': {len(results)} suggestions"
                if results:
                    findings += "\n" + "\n".join(f"  - {r}" for r in results[:10])
                    self._context_log.append(findings)
                    # Add multi-word results as candidates
                    for r in results:
                        wc = len(r.split())
                        if wc >= 3:
                            self._promising_terms.append(r)
                            self.discovered_candidates.append(CandidateNiche(
                                term=r, depth=1, word_count=wc,
                                parent_chain=[self.direction, query, r],
                            ))
                last_action = f"explore_autocomplete: '{query}'"
                last_findings = findings

            elif action_type == "search_youtube":
                if remaining_yt <= 0:
                    last_action = "search_youtube DENIED (budget exhausted)"
                    last_findings = "No YouTube API searches remaining"
                    self._log_step(iteration, "budget_exhausted", reasoning, query, last_findings)
                    continue

                findings = await self._sample_youtube(query)
                self.youtube_budget_used += 1
                self._context_log.append(f"YouTube search for '{query}': {findings[:200]}")
                last_action = f"search_youtube: '{query}'"
                last_findings = findings

            elif action_type == "go_deeper":
                candidates = crawl_autocomplete(query, max_depth=2)
                self.discovered_candidates.extend(candidates)
                findings = f"Deep crawl on '{query}': found {len(candidates)} candidates"
                if candidates:
                    top_terms = sorted(candidates, key=lambda c: c.word_count, reverse=True)[:5]
                    findings += "\n  Top specific terms: " + ", ".join(c.term for c in top_terms)
                self._context_log.append(findings)
                last_action = f"go_deeper: '{query}'"
                last_findings = findings

            elif action_type == "pivot":
                new_hyps = await self._pivot(reasoning)
                self._promising_terms = []
                self._steps_in_current_area = 0
                for h in new_hyps:
                    for t in h.get("search_terms", []):
                        self._promising_terms.append(t)
                findings = f"Pivoted. New hypotheses: {json.dumps(new_hyps)[:300]}"
                self._context_log.append(findings)
                last_action = "pivot"
                last_findings = findings

            else:
                last_action = f"unknown action: {action_type}"
                last_findings = ""

            self._log_step(iteration, action_type, reasoning, query, last_findings[:500])

        # Deduplicate candidates
        seen = set()
        unique = []
        for c in self.discovered_candidates:
            if c.term.lower() not in seen:
                seen.add(c.term.lower())
                unique.append(c)
        self.discovered_candidates = unique

        return self.discovered_candidates

    async def _generate_hypotheses(self) -> list[dict]:
        prompt = AGENT_HYPOTHESIS_USER.replace("{direction}", self.direction)
        try:
            result = await self.llm.complete_json(AGENT_HYPOTHESIS_SYSTEM, prompt)
            # Normalize: could be a list or a dict with a key containing a list
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                # Claude might wrap in {"hypotheses": [...]} or similar
                for key in ("hypotheses", "results", "items"):
                    if key in result and isinstance(result[key], list):
                        return result[key]
                return [result]  # Single hypothesis as dict
            return [{"hypothesis": self.direction, "search_terms": [self.direction], "reasoning": "unexpected format"}]
        except Exception as e:
            return [{"hypothesis": self.direction, "search_terms": [self.direction], "reasoning": f"fallback: {str(e)[:50]}"}]

    async def _decide_next_action(self, iteration: int, remaining_yt: int,
                                   last_action: str, last_findings: str) -> dict:
        context = "\n".join(self._context_log[-10:])
        # Use replace instead of .format() because context contains JSON with curly braces
        system = AGENT_DECIDE_SYSTEM.replace("{remaining_yt}", str(remaining_yt)).replace("{context}", context)
        user = (AGENT_DECIDE_USER
                .replace("{iteration}", str(iteration))
                .replace("{max_iterations}", str(self.max_iterations))
                .replace("{remaining_yt}", str(remaining_yt))
                .replace("{last_action}", last_action)
                .replace("{last_findings}", last_findings[:600]))
        try:
            result = await self.llm.complete_json(system, user, max_tokens=512)
            # Normalize the result — Claude might use "action" instead of "type", etc.
            if isinstance(result, dict):
                action_type = result.get("type") or result.get("action") or result.get("next_action") or "done"
                query = result.get("query") or result.get("search_term") or result.get("term") or ""
                reasoning = result.get("reasoning") or result.get("reason") or result.get("rationale") or ""
                return {"type": action_type, "query": query, "reasoning": reasoning}
            # If it's somehow a list, take the first item
            if isinstance(result, list) and result:
                item = result[0]
                if isinstance(item, dict):
                    return {"type": item.get("type", "done"), "query": item.get("query", ""), "reasoning": item.get("reasoning", "")}
            return {"type": "done", "reasoning": "unexpected LLM response format"}
        except Exception as e:
            # Fallback: explore the next promising term
            if self._promising_terms:
                return {"type": "explore_autocomplete", "query": self._promising_terms.pop(0),
                        "reasoning": f"fallback after error: {str(e)[:50]}"}
            return {"type": "done", "reasoning": f"error: {str(e)[:50]}"}

    async def _sample_youtube(self, query: str) -> str:
        """Use YouTube API to sample real video data for a term."""
        try:
            from analyzer import search_videos, fetch_video_stats, fetch_channel_stats, _get_youtube_client
            import quota as quota_tracker

            if not quota_tracker.can_afford(102):
                return "Insufficient YouTube API quota"

            youtube = _get_youtube_client()
            items, total = search_videos(youtube, query)

            if not items or total < 5:
                return f"Only {total} results — niche too small or dead"

            video_ids = [i["id"]["videoId"] for i in items if "videoId" in i.get("id", {})]
            videos = fetch_video_stats(youtube, video_ids[:25])
            channel_ids = list(set(v.channel_id for v in videos))
            channels = fetch_channel_stats(youtube, channel_ids[:25])

            ch_map = {c.channel_id: c for c in channels}
            small_ch = sum(1 for c in channels if c.subscriber_count < 10_000)

            lines = [f"Total results: ~{total}. Got {len(videos)} videos, {len(channels)} channels."]
            lines.append(f"Small channels (<10k subs): {small_ch}/{len(channels)}")

            for v in sorted(videos, key=lambda v: v.view_count, reverse=True)[:5]:
                ch = ch_map.get(v.channel_id)
                subs = ch.subscriber_count if ch else 0
                lines.append(f'  "{v.title}" — {v.view_count:,} views, channel: {subs:,} subs')

            # Add high-potential videos as candidates
            for v in videos:
                ch = ch_map.get(v.channel_id)
                if ch and ch.subscriber_count < 10_000 and v.view_count > ch.subscriber_count * 2:
                    self.discovered_candidates.append(CandidateNiche(
                        term=query, depth=0, word_count=len(query.split()),
                        parent_chain=[self.direction, query],
                    ))
                    break

            return "\n".join(lines)

        except Exception as e:
            return f"YouTube API error: {str(e)[:100]}"

    async def _pivot(self, reason: str) -> list[dict]:
        context = "\n".join(self._context_log[-5:])
        prompt = (
            f"Previous direction didn't work well. Reason: {reason}\n\n"
            f"What we've found so far:\n{context}\n\n"
            f"Generate 3 NEW hypotheses for different angles on: {self.direction}"
        )
        try:
            return await self.llm.complete_json(AGENT_HYPOTHESIS_SYSTEM, prompt)
        except Exception:
            return [{"hypothesis": self.direction, "search_terms": [self.direction], "reasoning": "pivot fallback"}]

    def _log_step(self, num: int, action: str, reasoning: str, query: str, findings: str):
        step = AgentStep(
            step_number=num, action=action, reasoning=reasoning,
            query=query, findings=findings,
        )
        self.steps.append(step)
        if self.on_step:
            self.on_step(step)
