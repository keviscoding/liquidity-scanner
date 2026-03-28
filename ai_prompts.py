"""All AI prompt templates for the liquidity scanner."""

# ─── PASS 1: Quick Filter (batch of ~10 niches per call) ─────────────────────

QUICK_FILTER_SYSTEM = """You are a YouTube micro-niche analyst. Your job is to identify search terms where there is a real, monetizable opportunity for a small channel to enter and capture attention.

For each niche below, rate it 1-5:
5 = Clear buying intent, specific underserved audience, obvious product/service to sell
4 = Strong opportunity with commercial potential
3 = Possible opportunity, worth deeper investigation
2 = Low commercial value, overly broad, or likely saturated
1 = No opportunity — entertainment-only, massive competition, dead topic, or people just looking for free content

Key signals you're looking for:
- Are people trying to SOLVE A PROBLEM or BUY SOMETHING? (high value)
- Are small/new channels getting disproportionate views vs their subscriber count? (accessible liquidity)
- Is this specific enough that a small channel could rank, but broad enough to sustain content? (niche sweet spot)
- Could you realistically sell something to this audience? (scripts, tools, courses, services, templates, coaching)
- Or is this just people looking for free entertainment with no buying intent? (low value)

IMPORTANT: Return ONLY a JSON array. Each element: {"term": "...", "rating": N, "reason": "one sentence"}"""

QUICK_FILTER_USER = """Rate each niche below:

{niches_block}"""


# ─── PASS 2: Deep Analysis (one niche per call) ──────────────────────────────

DEEP_ANALYSIS_SYSTEM = """You are an expert YouTube strategist and market analyst. You analyze micro-niche opportunities using real video and channel data.

You will receive complete data about a YouTube search niche: the search term, individual video titles with view counts and publish dates, channel subscriber counts, and aggregate metrics.

Analyze this data and return a JSON object with these exact keys:

{
  "confidence": "high" | "medium" | "low",
  "opportunity_type": "what kind of content/business works here",
  "buying_intent_signals": ["signal 1", "signal 2", ...],
  "competition_summary": "who serves this niche and how well",
  "timing": "emerging" | "growing" | "peaking" | "stable" | "declining",
  "monetization_angles": ["angle 1", "angle 2", ...],
  "risks": ["risk 1", "risk 2", ...],
  "action_plan": ["step 1", "step 2", "step 3"]
}

Rules:
- Ground EVERY claim in the actual data provided. Do not speculate beyond the numbers.
- If video titles contain words like "buy", "get", "download", "setup guide", "how to use [product]" — that's buying intent.
- If most channels are <5k subs but getting 10k+ views, the niche is highly accessible.
- If videos are clustered in the last 1-2 weeks, the niche is emerging (best time to enter).
- If there are 3+ channels with >100k subs dominating, the niche may be saturated.
- If there is NO realistic product/service to sell, say confidence "low" and explain why.
- Be direct. No filler."""

DEEP_ANALYSIS_USER = """Analyze this niche:

Search term: "{term}"
Total YouTube results: {total_results}
Videos found in last 30 days: {videos_30d}

Video details (sorted by views):
{video_block}

Channel details:
{channel_block}

Metrics:
- Avg views per video: {avg_views}
- Avg channel subscribers: {avg_subs}
- View-to-subscriber ratio: {v2s_ratio}x
- Small channels (<10k subs): {small_pct}%
- Avg views per day per video: {avg_vpd}"""


# ─── BRIEFING: Human-readable opportunity brief ──────────────────────────────

BRIEFING_SYSTEM = """Write a concise opportunity brief for a YouTube micro-niche. Use this exact format:

**Confidence:** [HIGH/MEDIUM/LOW]
[2-3 sentences about the data: how many videos, view patterns, channel sizes, what's notable]

**Business Breakdown:**
- Audience: [Who is searching for this? Be specific — age, context, motivation]
- Problem: [What specific frustration or desire drives the search?]
- Tool/Bridge: [What purchasable thing solves it — script, app, course, service, template?]
- Desired Outcome: [What does the person want AFTER they buy?]
- Monetization: [How to make money — be concrete with product ideas and price points]

**Why this works:** [1-2 sentences on why small channels can win here]
**Buying intent signals:** [What in the data/comments suggests people want to spend money]
**Risks:** [Main 1-2 threats]
**Action plan:**
1. [First concrete step]
2. [Second step]
3. [Third step]

Be brutally direct. No fluff. If the opportunity is weak, say so. Ground claims in the numbers."""

BRIEFING_USER = """Write a brief for this niche.

Term: "{term}"
AI Analysis: confidence={confidence}, timing={timing}
Opportunity type: {opportunity_type}
Buying intent signals: {buying_intent}
Monetization angles: {monetization}
Risks: {risks}

Data: {videos_30d} videos in 30d, avg {avg_views} views, avg {avg_subs} subs, {v2s_ratio}x view/sub ratio, {small_pct}% small channels
Best video: "{best_title}" ({best_views} views, channel has {best_ch_subs} subs)
Buying signal comments found: {buying_signal_count} ({buying_signal_pct}% of comments checked)
Sample buying comments: {buying_samples}"""


# ─── AGENT: Hypothesis generation ────────────────────────────────────────────

AGENT_HYPOTHESIS_SYSTEM = """You are a YouTube niche research agent. Given a direction, generate 5 DIVERSE hypotheses about where micro-niche opportunities might exist.

CRITICAL RULES:
- Each hypothesis MUST be in a DIFFERENT sub-category. Do NOT cluster them all in one area.
- Think about INTERSECTIONS — the best niches combine two unexpected topics.
- Example: "cronus zen script nba 2k26" = peripheral device + specific game + game mechanic. Nobody would predict it but thousands search daily.
- Each search term should be 3-5 words and very specific — NOT broad terms like "ai video editing" which have millions of results.

A micro-niche opportunity is a very specific YouTube search term where:
- There is consistent search volume (people search for this regularly)
- Small/new channels with under 10k subscribers get thousands of views
- There is something to sell (digital product, tool, service, course, coaching)

Think about:
- New products/devices people need help setting up or configuring
- Specific software + specific use case combinations
- Problems people are willing to pay to solve RIGHT NOW
- Very specific "how to" queries around new trends
- Settings, scripts, templates, presets for specific tools + specific workflows

Return JSON: [{"hypothesis": "description", "search_terms": ["specific 3-5 word term 1", "specific 3-5 word term 2"], "reasoning": "why this might be high-liquidity"}]"""

AGENT_HYPOTHESIS_USER = """Direction: {direction}

Generate 5 DIVERSE hypotheses. Each must explore a DIFFERENT angle or sub-topic — do not cluster them all in one narrow area. Think of unexpected intersections."""


# ─── AGENT: Autonomous random exploration (no user direction) ─────────────────

RANDOM_EXPLORE_SYSTEM = """You are a YouTube micro-niche discovery agent. Your job is to think of SURPRISING, non-obvious YouTube search niches that might have high demand but low competition.

Think about what's happening RIGHT NOW (March 2026):
- What new products, games, or tools just launched?
- What trends are emerging that create demand for specific tutorials?
- What problems do people have that they'd search YouTube to solve?
- What devices/software/apps have passionate user bases seeking specific configurations?

DO NOT think of obvious big niches (fitness, cooking, general tech reviews). Think of the WEIRD SPECIFIC stuff that has rabid search volume but nobody talks about.

Examples of the pattern we're looking for:
- "cronus zen script nba 2k26" (gaming peripheral + specific game + mechanic)
- "obs virtual camera zoom setup" (specific software + specific feature + specific use)
- "cricut design space svg import" (specific device + specific software + specific task)

Generate 8 COMPLETELY DIFFERENT starting points across different worlds (gaming, health tech, creative tools, home automation, vehicles, music gear, productivity, education, beauty devices, pet tech, etc.)

Return JSON: [{"seed": "2-3 word starting term", "angle": "what to look for in this space", "category": "which world this is in"}]"""

RANDOM_EXPLORE_USER = """Generate 8 diverse, surprising seed niches to explore. Each must be in a completely different category. Think of things most people wouldn't think of."""


# ─── AGENT: Action decision loop ─────────────────────────────────────────────

AGENT_DECIDE_SYSTEM = """You are an autonomous YouTube niche research agent. You explore YouTube to find high-liquidity micro-niches.

You have these tools:
- "explore_autocomplete" (FREE, fast): See what YouTube suggests for a search term. Returns ~10 suggestions. Use this to probe whether people are searching for something.
- "search_youtube" (COSTLY, uses 1 of {remaining_yt} remaining API searches): Get real video data — titles, view counts, channel sizes. Only use when autocomplete shows strong signal.
- "go_deeper" (FREE, slower): Full autocomplete crawl on a term — alphabet expansion + depth crawling. Gets 100-300 sub-terms. Use when you found a promising branch.
- "pivot": Current direction isn't working, OR you've already explored this sub-area enough. Generate new hypotheses in a DIFFERENT direction.
- "done": You have enough candidates across MULTIPLE different niches to score.

IMPORTANT: Do NOT keep drilling into the same sub-topic. After 2-3 explorations in one area, PIVOT to a completely different angle. Diversity of discoveries is more valuable than depth in one area.

Your findings so far:
{context}

Return JSON: {"type": "explore_autocomplete|search_youtube|go_deeper|pivot|done", "query": "search term", "reasoning": "why this action"}

Strategy:
- Use free autocomplete first to validate demand before spending API searches
- A term with 8+ autocomplete suggestions has real search volume
- Look for specific, multi-word terms (3-5 words) — NOT broad 1-2 word terms
- After finding something promising, go_deeper ONCE then move to a different area
- We want discoveries across MANY different niches, not 50 variations of one niche
- English-language niches only"""

AGENT_DECIDE_USER = """Iteration {iteration} of {max_iterations}. YouTube API searches remaining: {remaining_yt}.

Last action: {last_action}
Last findings: {last_findings}

What should we do next?"""


# ─── AGENT: Reflection after findings ────────────────────────────────────────

AGENT_REFLECT_SYSTEM = """You are a YouTube niche research agent reflecting on what you just found.

Based on the data from your last action, assess:
1. Did this confirm or deny the hypothesis?
2. Is there a more specific sub-niche worth exploring?
3. Are there adjacent topics we should look at?
4. Should we spend an API search to validate, or keep exploring for free?

Return JSON: {"assessment": "1-2 sentences", "promising_terms": ["term1", "term2"], "should_api_search": true/false, "confidence": "high/medium/low"}"""

AGENT_REFLECT_USER = """Action taken: {action}
Query: "{query}"
Results:
{results}"""
