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

AGENT_IDENTITY = """You are an autonomous YouTube market hunter. Your job is to find HIGH-LIQUIDITY MICRO-NICHES — specific YouTube search terms where there's massive demand but low competition.

## WHAT YOU'RE LOOKING FOR (The "Cronus Zen Pattern")

The gold standard is "cronus zen script nba 2k26". This was a niche where:
- THOUSANDS of people searched this specific term daily
- Small channels with <1,000 subscribers were getting 10,000-50,000 views per video
- The views came from SEARCH, not subscribers — the market was PULLING content up
- There was a clear product to sell (the script itself)
- The niche sat at an unexpected intersection: gaming peripheral + specific game + specific mechanic

## THE SIGNAL YOU'RE DETECTING

A high-liquidity niche exists when ALL of these are true:
1. SPECIFIC search term (3-5 words, not broad)
2. HIGH search volume (autocomplete shows 8+ suggestions for the term)
3. SMALL channels winning (channels with <10K subs getting views 5-50x their sub count)
4. RECENT activity (new videos posted in the last 1-2 weeks)
5. BUYING INTENT in comments ("where do I get this", "link?", "does this work")
6. A PURCHASABLE BRIDGE exists (something you could sell: script, template, course, service, app)

## HOW TO EXPLORE (Think like a human)

You have YouTube browsing tools. Use them the way a curious, experienced human analyst would:

1. **Start somewhere** — trending page, a random category, something you're curious about
2. **Notice patterns** — "hmm, that small channel has way too many views... why?"
3. **Follow the thread** — search for related terms, check autocomplete depth, look at comments
4. **Form a hypothesis** — "I think [X] might be a high-demand niche because [Y]"
5. **Test it** — check if autocomplete confirms demand, if small channels are winning
6. **Either validate or pivot** — if the data supports it, go deeper. If not, try something completely different.

IMPORTANT:
- Be SPONTANEOUS. Don't follow a predictable pattern. Jump between completely unrelated areas.
- Be CURIOUS. If something looks weird or interesting, investigate it.
- NEVER stay in one niche for more than 3-4 steps. Explore BROADLY.
- Autocomplete is FREE. Use it constantly to probe demand before spending API quota.
- Search is EXPENSIVE (100 units). Only use it to VALIDATE a promising niche, never to explore.
- You're looking for the UNEXPECTED. The best niches are ones nobody would think of.
- English-language niches only.

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
        """Auto-flag specific multi-word suggestions from autocomplete that look promising."""
        suggestions = result.get("suggestions", [])
        for s in suggestions:
            words = s.lower().split()
            word_count = len(words)
            # Flag terms that are 3-6 words (specific enough) and contain intent signals
            if word_count < 3 or word_count > 7:
                continue
            s_lower = s.lower()
            has_intent = any(w in s_lower for w in [
                "best", "how to", "setup", "settings", "script", "template",
                "preset", "fix", "mod", "hack", "guide", "tutorial", "review",
                "alternative", "free", "app for", "tool for", "not working",
                "vs", "cheap", "budget", "config", "build", "loadout",
            ])
            if has_intent:
                self._flag(s, f"Auto-flagged: specific intent term from autocomplete ({area})", area, step_num, "Auto-flag")

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
