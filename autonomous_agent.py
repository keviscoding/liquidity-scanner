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

The key test: if someone watches a video on this topic, would they CLICK A LINK in the description and SPEND $20-100? If "no, they just wanted free info" — skip it.

Signs of a GOOD micro-niche:
- Small channels (under 10K subs) getting 10K-100K views on the topic
- Many autocomplete variations of the same theme (people keep searching different angles)
- The word "free" or "download" appearing (means people know it's normally paid)
- Comments asking "where do I get this?", "link?", "does this work?"
- Multiple new channels ALL posting about the SAME specific topic (feeding frenzy)
- It's SPECIFIC — not "gaming" but a specific device + specific game + specific mechanic

Signs of a BAD "niche":
- Generic tutorials anyone can learn free ("how to use chopsticks", "tutorial for beginners")
- Just product reviews ("best laptop for students")
- Too broad ("how to use chatgpt", "ai video editing")
- Pure entertainment with no product angle ("funny fails", "reaction videos")
- Dominated by huge channels — small channels can't compete

## CRITICAL: DIVERSITY REQUIREMENT

You MUST explore AT LEAST 5 COMPLETELY DIFFERENT WORLDS in every scan. After exploring one area for 2-3 steps, you MUST jump to something TOTALLY UNRELATED. The goal is to scan ACROSS YouTube, not drill into one corner.

Examples of different worlds (explore at least 5 of these):
- Gaming peripherals & mods (every game has its own ecosystem)
- Photography/videography gear & software (presets, LUTs, overlays)
- Music production (sample packs, plugins, presets)
- E-commerce & side hustles (specific platforms + specific methods)
- Crafting/DIY machines (Cricut, 3D printers, laser cutters + specific projects)
- Beauty/skincare devices & treatments (LED masks, microneedling, specific routines)
- Fitness tech & programs (specific apps, wearables, workout plans)
- Smart home & automation (specific devices, specific configurations)
- AI tools for specific professions (not general "AI tools" — specific use cases)
- Vehicle mods & tuning (specific cars, specific mods, specific tools)
- Pet care products & training (specific breeds, specific issues)
- Education tech (specific exam prep, specific courses, specific certifications)
- Dating/social media growth (specific platforms, specific strategies)
- Cooking/kitchen gadgets (specific devices, specific cuisines)
- Financial tools (specific trading platforms, specific strategies)

DO NOT spend more than 3 steps in ANY single world. Jump aggressively.

## HOW TO EXPLORE

1. Start somewhere RANDOM — don't default to gaming or tech. Pick something surprising.
2. Use autocomplete to probe: type 2-3 words and see what YouTube suggests.
3. If suggestions are specific and numerous (8+ suggestions), that's high demand — explore deeper.
4. If suggestions are generic or few, PIVOT immediately to a different world.
5. When you see a promising specific term, flag it for scoring.
6. Every 2-3 steps, JUMP to a completely different world — even if current one is interesting.

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

        # MONETIZABILITY FILTER: Ask AI to remove terms with no product angle
        if self.flagged_niches:
            self.flagged_niches = await self._filter_monetizable(self.flagged_niches)

        return self.flagged_niches

    async def _filter_monetizable(self, niches: list[CandidateNiche]) -> list[CandidateNiche]:
        """Use AI to filter out terms where there's nothing to sell.
        This is the 'does this make sense' filter — removes workout routines,
        product reviews, generic tutorials, and pure entertainment."""
        terms = [n.term for n in niches]

        # Batch them (max 50 per AI call)
        kept_terms = set()
        for i in range(0, len(terms), 50):
            batch = terms[i:i+50]
            prompt = f"""Below is a list of YouTube search terms. For each one, decide: could someone CREATE and SELL a digital product (script, template, preset pack, course, tool, service, config, guide) to people searching this term?

KEEP terms where there's a clear sellable digital product angle.
REMOVE terms that are just:
- Free workout/exercise content (e.g. "resistance bands chest workout")
- Physical product reviews you can't sell yourself (e.g. "gaming mouse for small hands")
- Generic tutorials with no product (e.g. "how to cook pasta")
- Pure entertainment/information (e.g. "funny dog videos")
- Hardware reviews where you're not the manufacturer (e.g. "nd filter for iphone")

Terms:
{json.dumps(batch, indent=2)}

Return JSON: {{"keep": ["term1", "term2", ...], "remove": ["term3", "term4", ...]}}"""

            try:
                result = await self.llm.complete_json(
                    "You are a digital product monetization expert. You evaluate whether YouTube search terms represent markets where someone could sell a digital product.",
                    prompt
                )
                keep = result.get("keep", [])
                for t in keep:
                    kept_terms.add(t.lower().strip())
            except Exception:
                # On error, keep everything (don't lose data)
                for t in batch:
                    kept_terms.add(t.lower().strip())

        filtered = [n for n in niches if n.term.lower().strip() in kept_terms]

        removed_count = len(niches) - len(filtered)
        if removed_count > 0:
            self._log(0, "filter", f"Monetizability filter removed {removed_count}/{len(niches)} terms with no product angle", "", "")
            self.history.append(f"[FILTER] Removed {removed_count} terms with no sellable product angle. Kept {len(filtered)}.")

        return filtered

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
