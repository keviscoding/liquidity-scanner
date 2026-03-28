import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
RESULTS_DIR = DATA_DIR / "results"

load_dotenv(BASE_DIR / ".env")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# LLM (Claude) settings
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "claude-sonnet-4-20250514")
LLM_MODEL_DEEP = os.getenv("LLM_MODEL_DEEP", "claude-sonnet-4-20250514")
LLM_MAX_CONCURRENT = int(os.getenv("LLM_MAX_CONCURRENT", "5"))
AI_SCORING_ENABLED = os.getenv("AI_SCORING_ENABLED", "true").lower() == "true"

DAILY_QUOTA_LIMIT = 10_000
SEARCH_QUOTA_COST = 100
MAX_SEARCHES_PER_RUN = 75
AUTOCOMPLETE_DELAY = 0.3
AUTOCOMPLETE_MAX_DEPTH = 3
MIN_WORD_COUNT_FOR_CANDIDATE = 3
CACHE_TTL_HOURS = 24

# ═══════════════════════════════════════════════════════════════════════════════
# INTENT TEMPLATES — The core innovation.
#
# Instead of seeding by TOPIC ("gaming", "fitness"), we seed by INTENT PATTERN.
# Each template encodes buyer intent and is domain-agnostic. When fed into
# YouTube autocomplete, the MARKET fills in the domains automatically.
#
# "best script for" → autocomplete → "best script for nba 2k26", "best script
# for roblox", "best script for google sheets" — touching gaming, productivity,
# automation without us having to know those niches exist.
#
# Structure: [specific context] + [desired outcome] + [purchasable bridge]
# ═══════════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES = {
    # ─── TOOL-SEEKING: "I need a specific tool/product to do X" ───────────────
    "tool_seeking": [
        "best script for",
        "best settings for",
        "best preset for",
        "best template for",
        "best config for",
        "best plugin for",
        "best mod for",
        "best extension for",
        "best app for",
        "best software for",
        "best tool for",
        "best device for",
    ],

    # ─── CONFIGURATION-SEEKING: "I have the tool, how do I set it up" ─────────
    "configuration_seeking": [
        "setup guide for",
        "how to configure",
        "how to setup",
        "how to install",
        "settings tutorial",
        "best loadout for",
        "best layout for",
        "best build for",
    ],

    # ─── OUTCOME-SEEKING: "I want a specific result" ─────────────────────────
    "outcome_seeking": [
        "how to make money with",
        "how to automate",
        "how to grow",
        "how to get more",
        "how to boost",
        "how to speed up",
        "how to improve",
        "how to get better at",
    ],

    # ─── PROBLEM-SOLVING: "Something is broken / not working" ─────────────────
    "problem_solving": [
        "how to fix",
        "not working fix",
        "why is my",
        "how to stop",
        "how to remove",
        "how to get rid of",
        "keeps crashing",
        "error fix",
    ],

    # ─── SHORTCUT-SEEKING: "I want the cheat code / faster way" ──────────────
    "shortcut_seeking": [
        "hack for",
        "cheat for",
        "trick for",
        "bot for",
        "script for",
        "macro for",
        "auto",
        "glitch",
    ],

    # ─── COMPARISON-SEEKING: "Which one should I buy/use" ─────────────────────
    "comparison_seeking": [
        "vs which is better",
        "best alternative to",
        "is it worth it",
        "honest review",
        "vs for",
    ],

    # ─── PURCHASE-ADJACENT: "I'm about to buy, convince me" ──────────────────
    "purchase_adjacent": [
        "best cheap",
        "best budget",
        "best free",
        "cheapest",
        "discount code for",
        "where to buy",
    ],
}

# Flatten for easy iteration
ALL_INTENT_TEMPLATES = []
for category, templates in INTENT_TEMPLATES.items():
    for t in templates:
        ALL_INTENT_TEMPLATES.append((t, category))

# ─── URGENCY SIGNAL WORDS ────────────────────────────────────────────────────
# Terms containing these words get a scoring boost — they indicate the searcher
# needs a solution NOW (not idle browsing)
URGENCY_WORDS = {
    "fix", "broken", "error", "crash", "not working", "help", "urgent",
    "asap", "fast", "quick", "now", "today", "immediately", "emergency",
    "best", "settings", "setup", "configure", "script", "hack", "mod",
    "how to", "tutorial", "guide", "step by step",
}

# ─── BUYING SIGNAL WORDS (for comment analysis) ──────────────────────────────
BUYING_SIGNAL_PATTERNS = [
    "where do i get",
    "where can i buy",
    "where can i get",
    "how do i buy",
    "how much",
    "is this free",
    "link please",
    "link?",
    "send link",
    "drop the link",
    "where to buy",
    "does this work",
    "does it work",
    "is this legit",
    "can you share",
    "can you send",
    "i need this",
    "i want this",
    "take my money",
    "shut up and take",
    "how to download",
    "where to download",
    "discount",
    "coupon",
    "promo code",
    "worth it",
    "price",
]

# ─── LEGACY: Broad category seeds (kept as supplementary, not primary) ────────
# These supplement intent templates for cases where a broad topic seed
# catches something the intent templates miss.
EVERGREEN_SEEDS = [
    "gaming setup", "fps settings", "nba 2k", "valorant", "minecraft",
    "music production", "fl studio", "sample pack",
    "home workout", "supplement stack", "creatine",
    "skincare routine", "hair growth",
    "crypto trading", "dropshipping", "amazon fba",
    "air fryer", "meal prep",
    "smart home", "3d printing", "raspberry pi",
    "chatgpt", "midjourney", "ai video", "stable diffusion",
    "faceless youtube", "notion template", "canva template",
    "dog training", "aquarium setup",
    "drone flying", "photography tips",
    "car modification", "electric vehicle",
]

# Keywords used to filter Google Trends results toward monetizable niches
MONETIZABLE_KEYWORDS = [
    "how", "best", "free", "make", "get", "earn", "money", "income",
    "tips", "guide", "tutorial", "review", "vs", "cheap", "budget",
    "top", "hack", "trick", "secret", "fast", "easy", "beginner",
    "tool", "app", "software", "script", "bot", "template", "preset",
]


def ensure_dirs():
    """Create required directories if they don't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
