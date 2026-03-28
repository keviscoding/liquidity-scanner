"""Fully autonomous YouTube market hunter.

This agent has NO hardcoded seeds, templates, or patterns. It knows WHAT to find
(the Cronus Zen pattern) and has YouTube browsing tools to explore freely.

The AI decides everything: where to start, what to explore, when to go deeper,
when to pivot. It browses YouTube the way a sharp human analyst would.
"""
import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Callable

from ai_client import LLMClient
from browser_tools import execute_tool, TOOL_DESCRIPTIONS
from models import CandidateNiche, AgentStep
import quota as quota_tracker

# ─── THE AGENT'S KNOWLEDGE: What it's looking for ────────────────────────────

AGENT_IDENTITY = """You are a YouTube market hunter. You find micro-niches where someone can start a small channel, post videos, and immediately make money by selling a digital product to the audience.

## THE PATTERN YOU'RE HUNTING (Study this carefully)

REAL EXAMPLE — "cronus zen script nba 2k26":
- Cronus Zen is a $100 gaming device. NBA 2K26 is a popular basketball game.
- Players wanted "auto green" scripts (scripts that make their shots always go in).
- Someone was selling these scripts for $50 each and making $300K/month.
- On YouTube, THOUSANDS of people searched "cronus zen script nba 2k26" every day.
- Tiny channels with 500-2000 subscribers posted videos and got 20,000-50,000 views PURELY FROM SEARCH.
- The comments were full of "where do I get this?", "link?", "does this work on PS5?"

WHY this worked — the structure:
- AUDIENCE: NBA 2K players (millions of them, passionate, willing to spend)
- FRUSTRATION: They keep missing shots in the game
- TOOL: Cronus Zen device with custom scripts
- OUTCOME: Guaranteed "greens" (perfect shots every time)
- PRODUCT TO SELL: The script itself ($50), or coaching, or a guide

## WHAT MAKES A NICHE WORTH FLAGGING

The niche MUST have a clear PRODUCT someone could sell. Ask yourself: "What would someone pay $20-100 for in this niche?"

GOOD niches — the person would PAY $20-100 for a solution:
- "roblox blox fruits script no key" → sell scripts (EXACT Cronus Zen pattern)
- "fortnite macro controller ps5" → sell macro configs
- "lightroom preset pack free download" → sell premium preset packs
- "obs stream overlay template" → sell overlay packs
- "capcut template pack viral reels" → sell template packs
- "midjourney prompt pack portrait" → sell prompt collections
- "fl studio drum kit 2026" → sell sample packs
- "shopify theme customization" → sell themes or customization service
- "tinder ai photo generator" → sell AI photo service
- "cricut svg files wedding" → sell SVG bundles

Notice the PATTERN: every good niche has someone who wants a SPECIFIC DIGITAL SHORTCUT to get a result they can't easily get on their own. They want an unfair advantage, a time-saver, or a creative asset they can't make themselves.

BAD niches — freely available general knowledge, nothing to sell:
- "how to use chopsticks" → trivially simple
- "how to tie a tie" → free knowledge
- "best laptop for students" → just product reviews
- "home assistant setup beginner" → generic tutorial
- "how to use chatgpt" → too broad, free tool

The REAL test: if someone watches a video on this topic, would they click a link in the description and spend money? If the answer is "no, they just wanted free info" — it's a bad niche.

## HOW TO EXPLORE

Think about ECOSYSTEMS, not keywords. Every popular platform/game/tool has an ecosystem of people who want shortcuts:
- Games → scripts, macros, configs, hacks, bots
- Creative software → presets, templates, packs, assets, LUTs, brushes
- Business tools → templates, automations, workflows, integrations
- Personal improvement → courses, coaching, transformation services
- Hardware/devices → settings, configurations, mods, accessories

When autocomplete shows many specific variations of a theme (like "fortnite macro controller" showing pickup/prefire/edit/drag edit variations), that's an ADDICTION LOOP — the same audience keeps searching for more. That's gold.

Also watch for the word "free" or "download" in autocomplete — that means people KNOW this is normally a PAID product. They're trying to get it free, which proves the market exists.

## HOW TO EXPLORE

1. Start somewhere unexpected — browse trending, pick a random autocomplete path
2. When you see an interesting PRODUCT or TOOL mentioned, explore its ecosystem
3. Look for specificity: "[product] + [specific platform] + [specific use case]"
4. Check if autocomplete shows many variations (= high search demand)
5. Look for intersections you wouldn't predict
6. Be spontaneous — jump between completely unrelated areas every 2-3 steps

Use autocomplete (FREE) to probe. Only use search_youtube (EXPENSIVE, 100 units) to validate a niche you're already excited about.

## YOUR TOOLS

{tool_descriptions}

## CURRENT STATE

Quota remaining: {quota_remaining} units
Niches found so far: {niches_found}
Steps taken: {steps_taken} / {max_steps}
Areas explored: {areas_explored}
"""

AGENT_DECIDE_PROMPT = """Based on everything you've found so far, decide your NEXT ACTION.

Your exploration history:
{history}

Last action result:
{last_result}

Return a JSON object with:
{{
  "thinking": "Your reasoning — what did you notice? What's interesting? What do you want to investigate?",
  "tool": "tool_name",
  "args": {{"arg_name": "value"}},
  "area": "brief label for what area/topic you're exploring (e.g. 'gaming peripherals', 'home automation', 'music production')"
}}

If you've found a promising niche and want to flag it for scoring:
{{
  "thinking": "Why this niche looks promising",
  "tool": "flag_niche",
  "args": {{"term": "the specific search term", "reason": "why it matches the Cronus Zen pattern"}},
  "area": "..."
}}

If you're done exploring:
{{
  "thinking": "Why you're stopping",
  "tool": "done",
  "args": {{}},
  "area": "wrap-up"
}}

REMEMBER:
- Be spontaneous! If you've been in one area for 2+ steps, jump to something COMPLETELY different.
- Use autocomplete (FREE) to probe, then search_youtube (EXPENSIVE) only to validate.
- Flag niches when you see the pattern: specific term + high autocomplete depth + small channels winning.
- You have {steps_remaining} steps left and {quota_remaining} quota units."""


class AutonomousAgent:
    """Fully autonomous YouTube market hunter."""

    def __init__(
        self,
        llm: LLMClient,
        max_steps: int = 25,
        on_step: Callable[[AgentStep], None] | None = None,
        on_niche_found: Callable[[CandidateNiche], None] | None = None,
    ):
        self.llm = llm
        self.max_steps = max_steps
        self.on_step = on_step
        self.on_niche_found = on_niche_found

        self.steps: list[AgentStep] = []
        self.flagged_niches: list[CandidateNiche] = []
        self.history: list[str] = []
        self.areas_explored: list[str] = []
        self._last_result = "No actions taken yet. Start by exploring something — browse trending, pick a random topic to autocomplete, follow your curiosity."

    def _build_system_prompt(self) -> str:
        tool_desc = "\n".join(
            f"- **{name}** ({info['cost']}): {info['description']}\n  Args: {info['args']}"
            for name, info in TOOL_DESCRIPTIONS.items()
        )
        return AGENT_IDENTITY.format(
            tool_descriptions=tool_desc,
            quota_remaining=quota_tracker.get_remaining_quota(),
            niches_found=len(self.flagged_niches),
            steps_taken=len(self.steps),
            max_steps=self.max_steps,
            areas_explored=", ".join(set(self.areas_explored[-10:])) if self.areas_explored else "none yet",
        )

    def _build_decide_prompt(self) -> str:
        # Summarize history (keep last 10 entries to avoid context overflow)
        recent_history = self.history[-10:] if len(self.history) > 10 else self.history
        history_text = "\n".join(f"Step {i+1}: {h}" for i, h in enumerate(recent_history))
        if not history_text:
            history_text = "No history yet — this is your first step."

        return AGENT_DECIDE_PROMPT.format(
            history=history_text,
            last_result=str(self._last_result)[:2000],
            steps_remaining=self.max_steps - len(self.steps),
            quota_remaining=quota_tracker.get_remaining_quota(),
        )

    async def run(self) -> list[CandidateNiche]:
        """Run the autonomous exploration loop."""
        consecutive_errors = 0

        for step_num in range(1, self.max_steps + 1):
            try:
                decision = await self.llm.complete_json(
                    self._build_system_prompt(),
                    self._build_decide_prompt()
                )
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                self._log(step_num, "error", f"LLM error: {e}", "", str(e))
                self.history.append(f"[ERROR] LLM call failed: {str(e)[:100]}")
                if consecutive_errors >= 3:
                    self._log(step_num, "abort", "Too many consecutive LLM errors", "", "")
                    break
                continue

            if not isinstance(decision, dict):
                self._log(step_num, "error", f"LLM returned non-dict: {type(decision)}", "", str(decision)[:200])
                continue

            tool_name = decision.get("tool", "done")
            args = decision.get("args") or {}
            if isinstance(args, str):
                # Claude sometimes returns args as a string instead of dict
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"query": args}
            thinking = decision.get("thinking", "")
            area = decision.get("area", "unknown")

            self.areas_explored.append(area)

            # Handle special actions
            if tool_name == "done":
                self._log(step_num, "done", thinking, "", "Agent finished exploring")
                break

            if tool_name == "flag_niche":
                term = args.get("term", "") or args.get("query", "") or args.get("niche", "")
                reason = args.get("reason", "") or args.get("reasoning", "") or thinking
                if term:
                    self._flag(term, reason, area, step_num, thinking)
                continue

            # Execute the tool
            result = execute_tool(tool_name, args)
            result_summary = self._summarize_result(tool_name, args, result)

            self.history.append(f"[{tool_name}] {area}: {result_summary[:200]}")
            self._last_result = json.dumps(result, indent=2, default=str)[:3000]

            self._log(step_num, tool_name, thinking, json.dumps(args), result_summary)

            # AUTO-FLAG: If autocomplete/alphabet_expand found a high-demand specific term,
            # automatically flag promising candidates
            if tool_name in ("autocomplete", "alphabet_expand") and "error" not in result:
                self._auto_flag_from_suggestions(result, area, step_num)

        return self.flagged_niches

    def _summarize_result(self, tool: str, args: dict, result: dict) -> str:
        """Create a human-readable summary of a tool result."""
        if "error" in result:
            return f"ERROR: {result['error']}"

        if tool == "autocomplete":
            count = result.get("count", 0)
            suggestions = result.get("suggestions", [])[:5]
            return f"'{args.get('query')}': {count} suggestions — {', '.join(suggestions)}"

        elif tool == "alphabet_expand":
            total = result.get("total_branches", 0)
            high = result.get("high_demand", False)
            top = result.get("suggestions", [])[:5]
            return f"'{args.get('query')}': {total} branches {'(HIGH DEMAND!)' if high else ''} — {', '.join(top)}"

        elif tool == "browse_trending":
            videos = result.get("videos", [])
            return f"Trending: {len(videos)} videos. Top: " + ", ".join(
                f"'{v['title'][:40]}' ({v['views']:,} views)" for v in videos[:3]
            )

        elif tool == "search_youtube":
            total = result.get("total_results", 0)
            found = result.get("videos_found", 0)
            videos = result.get("videos", [])
            return f"Search '{args.get('query')}': {total} total results, {found} recent videos. " + ", ".join(
                f"'{v['title'][:30]}' by {v['channel']}" for v in videos[:3]
            )

        elif tool == "get_video_details":
            videos = result.get("videos", [])
            return "Video stats: " + ", ".join(
                f"'{v['title'][:30]}' ({v['views']:,} views)" for v in videos[:3]
            )

        elif tool == "get_channel_info":
            channels = result.get("channels", [])
            return "Channels: " + ", ".join(
                f"{c['name']} ({c['subscribers']:,} subs)" for c in channels[:3]
            )

        elif tool == "read_comments":
            total = result.get("total_comments", 0)
            buying = result.get("buying_signal_count", 0)
            signals = result.get("buying_signals", [])
            summary = f"{total} comments, {buying} buying signals"
            if signals:
                summary += ". Examples: " + "; ".join(
                    f"\"{s['comment'][:50]}\"" for s in signals[:3]
                )
            return summary

        return json.dumps(result, default=str)[:300]

    def _flag(self, term: str, reason: str, area: str, step_num: int, thinking: str):
        """Flag a niche for scoring."""
        term = term.lower().strip()
        # Don't double-flag
        if any(n.term == term for n in self.flagged_niches):
            return
        niche = CandidateNiche(
            term=term,
            depth=0,
            word_count=len(term.split()),
            autocomplete_branch_count=0,
            parent_chain=[f"agent:{area}", term],
        )
        self.flagged_niches.append(niche)
        self.history.append(f"[FLAG] Flagged niche: '{term}' — {reason}")
        self._log(step_num, "flag_niche", thinking, term, reason)
        self._last_result = f"Flagged '{term}' as promising niche. Total flagged: {len(self.flagged_niches)}"
        if self.on_niche_found:
            self.on_niche_found(niche)

    def _auto_flag_from_suggestions(self, result: dict, area: str, step_num: int):
        """Collect specific multi-word suggestions as candidates for scoring.
        Uses loose filtering — the YouTube API scoring will validate properly.
        We want to cast a wide net here, not be picky."""
        suggestions = result.get("suggestions", [])
        for s in suggestions:
            words = s.lower().split()
            word_count = len(words)
            # Only flag 3-7 word terms (specific enough to be a micro-niche)
            if word_count < 3 or word_count > 7:
                continue

            s_lower = s.lower()

            # Skip obviously generic/useless queries
            skip = any(g in s_lower for g in [
                "what is", "who is", "when is", "where is",
                "meaning of", "definition of", "history of",
                "funny", "meme", "compilation", "reaction",
                "full movie", "full episode", "trailer",
                "news today", "live stream",
            ])
            if skip:
                continue

            # Flag it — let the AI + scoring pipeline decide if it's good
            self._flag(s, f"Candidate from autocomplete ({area})", area, step_num, "Auto-collect")

    def _log(self, step: int, action: str, reasoning: str, query: str, findings: str):
        step_obj = AgentStep(
            step_number=step,
            action=action,
            reasoning=reasoning,
            query=query,
            findings=findings,
        )
        self.steps.append(step_obj)
        if self.on_step:
            self.on_step(step_obj)
