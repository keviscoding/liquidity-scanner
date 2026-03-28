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

GOOD niches (have a sellable product):
- "obs stream overlay template" → sell premium overlays
- "capcut template pack viral" → sell template packs
- "shopify theme customization" → sell custom themes or a course
- "midjourney prompt pack" → sell prompt collections
- "cricut svg files free" → sell premium SVG bundles
- "fl studio drum kit" → sell drum kits/sample packs
- "notion budget template" → sell premium templates
- "cronus zen script nba 2k26" → sell scripts
- "tinder ai photo generator" → sell AI photo service

BAD niches (nothing to sell, just general knowledge):
- "how to use chopsticks" → free knowledge, no product
- "how to tie a tie" → everyone knows, no product
- "how to use a can opener" → trivially simple, no product
- "how to use ratchet straps" → basic DIY, no product
- "best pokemon vgc teams" → just entertainment/info
- "how to use blender" → way too broad
- "home assistant setup beginner" → just a tutorial, no clear product

The key difference: GOOD niches involve a specific DIGITAL PRODUCT or SERVICE that solves a specific problem for a specific audience. BAD niches are just general "how to" information that's freely available everywhere.

## WHAT TO LOOK FOR IN AUTOCOMPLETE

When you explore autocomplete, look for terms that suggest people want something SPECIFIC and PURCHASABLE:
- "[product] template" / "[product] preset" / "[product] script" / "[product] pack"
- "[product] settings for [specific thing]" (configurations people pay for)
- "[product] alternative free" (they want something but can't afford the paid version — you can sell a cheaper one)
- "[product] not working" / "[product] fix" (frustration = buying intent if a solution exists)
- "[tool] for [specific profession/hobby]" (specialized = willing to pay)

DO NOT flag terms that are just "how to use [common item]" or "best [broad category]". Those are NOT micro-niches. They're basic queries with zero buying intent.

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
        """Auto-flag suggestions that indicate a SELLABLE PRODUCT exists.
        Very selective — only flag terms where there's clearly something to sell."""
        suggestions = result.get("suggestions", [])
        for s in suggestions:
            words = s.lower().split()
            word_count = len(words)
            if word_count < 3 or word_count > 7:
                continue
            s_lower = s.lower()

            # MUST contain a product/digital-goods indicator
            has_product_signal = any(w in s_lower for w in [
                "template", "preset", "script", "pack", "kit", "bundle",
                "plugin", "extension", "mod", "theme", "overlay", "svg",
                "font", "lut", "brush", "sample", "drum kit", "sound pack",
                "prompt", "workflow", "automation", "bot", "macro",
                "config", "loadout", "settings for",
            ])

            if not has_product_signal:
                continue

            # MUST NOT be too generic
            too_generic = any(g in s_lower for g in [
                "how to use", "what is", "how does", "tutorial for beginners",
                "for dummies", "explained",
            ])

            if too_generic:
                continue

            self._flag(s, f"Auto-flagged: product-signal term ({area})", area, step_num, "Auto-flag")

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
