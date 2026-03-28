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

# High-intent prefixes that surface what people are actively searching for RIGHT NOW
# These are generic enough to hit any niche/category
HIGH_INTENT_PREFIXES = [
    # Making money / selling
    "how to make money with",
    "how to sell",
    "how to earn",
    "passive income with",
    "make money online",
    # Fixing / solving problems
    "how to fix",
    "how to get rid of",
    "how to stop",
    "why is my",
    # Learning / getting better
    "how to get better at",
    "how to learn",
    "beginner guide to",
    "how to start",
    # Best / cheapest
    "best cheap",
    "best budget",
    "best free",
    "best alternative to",
    # Tools / software / apps
    "best app for",
    "best software for",
    "best tool for",
    "best ai tool for",
    # Specific product searches
    "vs which is better",
    "honest review",
    "is it worth it",
    "unboxing",
    # Settings & configurations (high buying intent)
    "best settings for",
    "best script for",
    "best mod for",
    "best preset for",
    "best template for",
    "best config for",
    "how to setup",
    "how to configure",
    "how to install",
    "step by step",
    # Troubleshooting
    "not working fix",
    "error fix",
    "problem solution",
    "keeps crashing",
]

# Broad category seeds - one or two words per major YouTube category.
# These are intentionally generic so autocomplete + alphabet expansion
# discovers the specific micro-niches organically.
EVERGREEN_SEEDS = [
    # Gaming & esports
    "gaming setup", "game controller", "gaming chair", "fps settings",
    "warzone", "fortnite", "minecraft", "roblox", "gta online",
    "nba 2k", "ea fc", "elden ring", "valorant", "apex legends",
    # Music
    "music production", "beat making", "guitar tabs", "piano tutorial",
    "music theory", "vocal training", "fl studio", "ableton",
    "how to mix", "sample pack",
    # Health & fitness
    "home workout", "gym routine", "weight loss", "meal prep",
    "protein shake", "supplement stack", "running tips", "yoga for",
    "intermittent fasting", "creatine",
    # Beauty & skincare
    "skincare routine", "acne treatment", "hair growth", "nail art",
    "makeup tutorial", "anti aging", "hair loss", "beard growth",
    # Finance & investing
    "stock trading", "options trading", "crypto trading", "forex trading",
    "passive income", "dividend stocks", "real estate investing",
    "side hustle", "dropshipping", "amazon fba",
    # Food & cooking
    "easy recipe", "air fryer", "meal prep", "budget meals",
    "high protein meal", "keto recipe", "slow cooker",
    # Tech & gadgets
    "best phone", "laptop review", "smart home", "budget earphones",
    "3d printing", "raspberry pi", "home server", "vpn",
    # AI & software tools
    "chatgpt", "midjourney", "ai video", "ai voice", "ai music",
    "stable diffusion", "automation tool", "no code",
    # Creator economy
    "youtube growth", "faceless youtube", "youtube shorts strategy",
    "tiktok viral", "instagram reels", "digital product",
    "online course", "notion template", "canva template",
    # Education & skills
    "learn python", "learn spanish", "public speaking",
    "speed reading", "memory technique", "productivity system",
    # Relationships & lifestyle
    "dating advice", "confidence tips", "morning routine",
    "minimalism", "van life", "tiny house",
    # Pets
    "dog training", "cat behavior", "pet care", "aquarium setup",
    # Hobbies & DIY
    "woodworking beginner", "painting tutorial", "knitting beginner",
    "rc car", "drone flying", "photography tips",
    # Travel
    "budget travel", "travel hacks", "digital nomad", "visa free",
    # Automotive
    "car modification", "car maintenance", "electric vehicle",
    "dashcam", "car insurance tips",
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
