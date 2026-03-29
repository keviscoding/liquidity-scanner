"""Browser-based YouTube scraping tools using dev-browser.

These tools give the autonomous agent FREE, unlimited YouTube browsing —
no API quota consumed. The agent can search, visit videos, read comments,
check channels, and browse the homepage like a real person.

Requires: npm install -g dev-browser && dev-browser install
"""
import json
import re
import shutil
import subprocess
from urllib.parse import quote_plus, urlparse

from config import BUYING_SIGNAL_PATTERNS

# ─── Availability check ──────────────────────────────────────────────────────

_DEV_BROWSER_AVAILABLE: bool | None = None


def is_dev_browser_available() -> bool:
    """Check if dev-browser CLI is installed and working. Cached after first call."""
    global _DEV_BROWSER_AVAILABLE
    if _DEV_BROWSER_AVAILABLE is not None:
        return _DEV_BROWSER_AVAILABLE
    if not shutil.which("dev-browser"):
        _DEV_BROWSER_AVAILABLE = False
        return False
    try:
        result = subprocess.run(
            ["dev-browser", "--help"],
            capture_output=True, text=True, timeout=10
        )
        _DEV_BROWSER_AVAILABLE = result.returncode == 0
    except Exception:
        _DEV_BROWSER_AVAILABLE = False
    return _DEV_BROWSER_AVAILABLE


# ─── Bridge: Python → dev-browser ────────────────────────────────────────────

def _run_browser_script(script: str, timeout: int = 45) -> dict:
    """Execute a JavaScript script via dev-browser and return parsed JSON output.

    The script should console.log() a JSON object as its last output.
    Returns {"error": "..."} on failure.
    """
    try:
        result = subprocess.run(
            ["dev-browser", "--headless"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return {"error": f"dev-browser exited with code {result.returncode}: {stderr[:500]}"}

        if not stdout:
            return {"error": "dev-browser returned empty output"}

        # Find the last JSON line in stdout (scripts may log other stuff first)
        lines = stdout.split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        # Try parsing the entire stdout as JSON
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"error": f"Could not parse JSON from dev-browser output: {stdout[:500]}"}

    except subprocess.TimeoutExpired:
        return {"error": f"dev-browser timed out after {timeout}s"}
    except Exception as e:
        return {"error": f"dev-browser execution failed: {str(e)[:300]}"}


# ─── Utilities ────────────────────────────────────────────────────────────────

def _parse_view_count(text: str) -> int:
    """Parse YouTube view count text into integer.
    Handles: '1.2M views', '45K views', '1,234 views', '1234', 'No views'
    """
    if not text:
        return 0
    text = text.lower().replace(",", "").replace("views", "").replace("view", "").strip()
    if not text or text == "no":
        return 0

    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if text.endswith(suffix):
            try:
                return int(float(text[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _parse_sub_count(text: str) -> int:
    """Parse subscriber count text. Same format as views but may say 'subscribers'."""
    if not text:
        return 0
    text = text.lower().replace("subscribers", "").replace("subscriber", "").strip()
    return _parse_view_count(text)


# Common JS snippet to dismiss YouTube's cookie consent
_COOKIE_DISMISS = """
try {
  const btns = await page.locator('button:has-text("Accept all"), button:has-text("Reject all")').all();
  if (btns.length > 0) { await btns[0].click(); await page.waitForTimeout(1000); }
} catch(e) {}
"""

# Product link patterns to detect in video descriptions
PRODUCT_LINK_DOMAINS = [
    "gumroad.com", "whop.com", "etsy.com", "discord.gg", "discord.com/invite",
    "ko-fi.com", "patreon.com", "sellfy.com", "shopify.com", "linktree",
    "beacons.ai", "stan.store", "buymeacoffee.com", "podia.com",
    "teachable.com", "kajabi.com", "thinkific.com", "skool.com",
    "gum.co", "lemonsqueezy.com", "stripe.com/pay", "paypal.me",
    "yew.gg", "linktr.ee",
]


# ─── Tool: Browse YouTube Search ─────────────────────────────────────────────

def tool_browse_youtube_search(query: str) -> dict:
    """Search YouTube and scrape the results page. FREE — no API quota.
    Returns video titles, URLs, channel names, view counts, and upload dates.
    """
    encoded = quote_plus(query)
    script = f"""
const page = await browser.getPage("yt");
await page.goto("https://www.youtube.com/results?search_query={encoded}", {{waitUntil: "domcontentloaded"}});
await page.waitForTimeout(3000);
{_COOKIE_DISMISS}

// Extract video results from the page
const results = await page.evaluate(() => {{
  const videos = [];
  const renderers = document.querySelectorAll("ytd-video-renderer");
  for (const r of renderers) {{
    try {{
      const titleEl = r.querySelector("#video-title");
      const metaLine = r.querySelectorAll("#metadata-line span");
      const channelEl = r.querySelector("ytd-channel-name a, ytd-channel-name #text");
      const thumbEl = r.querySelector("a#thumbnail");
      const durationEl = r.querySelector("ytd-thumbnail-overlay-time-status-renderer span");

      const title = titleEl?.textContent?.trim() || "";
      const href = thumbEl?.getAttribute("href") || "";
      const videoId = href.match(/v=([^&]+)/)?.[1] || "";
      const channel = channelEl?.textContent?.trim() || "";
      const views = metaLine[0]?.textContent?.trim() || "";
      const age = metaLine[1]?.textContent?.trim() || "";
      const duration = durationEl?.textContent?.trim() || "";

      if (title && videoId) {{
        videos.push({{ title, videoId, channel, views, age, duration, url: "https://www.youtube.com/watch?v=" + videoId }});
      }}
    }} catch(e) {{}}
  }}
  return videos;
}});

console.log(JSON.stringify({{
  query: "{query.replace('"', '\\"')}",
  videos_found: results.length,
  videos: results.slice(0, 25)
}}));
"""
    result = _run_browser_script(script)
    if "error" not in result:
        # Parse view counts into integers
        for v in result.get("videos", []):
            v["views_int"] = _parse_view_count(v.get("views", ""))
    return result


# ─── Tool: Browse Video Page ──────────────────────────────────────────────────

def tool_browse_video_page(video_url: str) -> dict:
    """Visit a YouTube video page and extract detailed info.
    Returns title, views, channel, subscriber count, description, and product links.
    """
    if not video_url.startswith("http"):
        video_url = f"https://www.youtube.com/watch?v={video_url}"

    script = f"""
const page = await browser.getPage("yt");
await page.goto("{video_url}", {{waitUntil: "domcontentloaded"}});
await page.waitForTimeout(3000);
{_COOKIE_DISMISS}

// Click "...more" to expand description
try {{
  const moreBtn = page.locator('tp-yt-paper-button#expand, [id="expand"]');
  if (await moreBtn.isVisible({{timeout: 2000}})) {{ await moreBtn.click(); await page.waitForTimeout(500); }}
}} catch(e) {{}}

const data = await page.evaluate(() => {{
  const title = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.ytd-video-primary-info-renderer")?.textContent?.trim() || "";
  const viewsEl = document.querySelector("span.view-count, ytd-video-view-count-renderer span");
  const views = viewsEl?.textContent?.trim() || "";
  const channelEl = document.querySelector("ytd-channel-name a, #channel-name a");
  const channel = channelEl?.textContent?.trim() || "";
  const channelUrl = channelEl?.getAttribute("href") || "";
  const subsEl = document.querySelector("#owner-sub-count, yt-formatted-string#owner-sub-count");
  const subs = subsEl?.textContent?.trim() || "";
  const descEl = document.querySelector("#description-inner, ytd-text-inline-expander #plain-snippet-text, #description .content");
  const description = descEl?.textContent?.trim()?.substring(0, 2000) || "";

  // Extract all links from description
  const linkEls = document.querySelectorAll("#description a, ytd-text-inline-expander a");
  const links = Array.from(linkEls).map(a => a.href).filter(h => h && !h.includes("youtube.com/hashtag"));

  return {{ title, views, channel, channelUrl, subs, description, links }};
}});

// Detect product links
const productDomains = {json.dumps(PRODUCT_LINK_DOMAINS)};
const productLinks = data.links.filter(link => productDomains.some(d => link.toLowerCase().includes(d)));

console.log(JSON.stringify({{
  video_url: "{video_url}",
  title: data.title,
  views: data.views,
  views_int: 0,  // will be parsed in Python
  channel: data.channel,
  channel_url: data.channelUrl ? "https://www.youtube.com" + data.channelUrl : "",
  channel_subs: data.subs,
  channel_subs_int: 0,
  description_preview: data.description.substring(0, 500),
  all_links: data.links.slice(0, 20),
  product_links: productLinks,
  has_product_links: productLinks.length > 0
}}));
"""
    result = _run_browser_script(script)
    if "error" not in result:
        result["views_int"] = _parse_view_count(result.get("views", ""))
        result["channel_subs_int"] = _parse_sub_count(result.get("channel_subs", ""))
    return result


# ─── Tool: Browse Video Comments ──────────────────────────────────────────────

def tool_browse_video_comments(video_url: str) -> dict:
    """Read top comments from a YouTube video. Detects buying signals.
    Returns comments with text and buying signal indicators.
    """
    if not video_url.startswith("http"):
        video_url = f"https://www.youtube.com/watch?v={video_url}"

    script = f"""
const page = await browser.getPage("yt");
await page.goto("{video_url}", {{waitUntil: "domcontentloaded"}});
await page.waitForTimeout(2000);
{_COOKIE_DISMISS}

// Scroll down to load comments
for (let i = 0; i < 5; i++) {{
  await page.evaluate(() => window.scrollBy(0, 800));
  await page.waitForTimeout(1000);
}}

const comments = await page.evaluate(() => {{
  const items = document.querySelectorAll("ytd-comment-thread-renderer");
  return Array.from(items).slice(0, 30).map(item => {{
    const textEl = item.querySelector("#content-text");
    const likesEl = item.querySelector("#vote-count-middle");
    return {{
      text: textEl?.textContent?.trim()?.substring(0, 300) || "",
      likes: likesEl?.textContent?.trim() || "0",
    }};
  }}).filter(c => c.text.length > 0);
}});

console.log(JSON.stringify({{
  video_url: "{video_url}",
  total_comments: comments.length,
  comments: comments
}}));
"""
    result = _run_browser_script(script, timeout=60)
    if "error" not in result:
        # Detect buying signals in comments
        buying_signals = []
        for comment in result.get("comments", []):
            text_lower = comment["text"].lower()
            for pattern in BUYING_SIGNAL_PATTERNS:
                if re.search(pattern, text_lower):
                    buying_signals.append({
                        "comment": comment["text"][:150],
                        "pattern": pattern,
                    })
                    break
        result["buying_signals"] = buying_signals
        result["buying_signal_count"] = len(buying_signals)
    return result


# ─── Tool: Browse Channel Page ────────────────────────────────────────────────

def tool_browse_channel_page(channel_url: str) -> dict:
    """Visit a YouTube channel and extract subscriber count + recent videos."""
    if not channel_url.startswith("http"):
        channel_url = f"https://www.youtube.com/{channel_url}"

    # Ensure we go to the videos tab
    videos_url = channel_url.rstrip("/")
    if "/videos" not in videos_url:
        videos_url += "/videos"

    script = f"""
const page = await browser.getPage("yt");
await page.goto("{videos_url}", {{waitUntil: "domcontentloaded"}});
await page.waitForTimeout(3000);
{_COOKIE_DISMISS}

const data = await page.evaluate(() => {{
  const nameEl = document.querySelector("ytd-channel-name yt-formatted-string#text, #channel-header ytd-channel-name");
  const subsEl = document.querySelector("#subscriber-count, yt-formatted-string#subscriber-count");
  const name = nameEl?.textContent?.trim() || "";
  const subs = subsEl?.textContent?.trim() || "";

  const videoEls = document.querySelectorAll("ytd-rich-item-renderer, ytd-grid-video-renderer");
  const videos = Array.from(videoEls).slice(0, 12).map(el => {{
    const titleEl = el.querySelector("#video-title, a#video-title-link, h3 a");
    const metaEl = el.querySelectorAll("#metadata-line span, .inline-metadata-item");
    return {{
      title: titleEl?.textContent?.trim() || "",
      href: titleEl?.getAttribute("href") || "",
      views: metaEl[0]?.textContent?.trim() || "",
      age: metaEl[1]?.textContent?.trim() || "",
    }};
  }}).filter(v => v.title.length > 0);

  return {{ name, subs, videos }};
}});

console.log(JSON.stringify({{
  channel_url: "{channel_url}",
  name: data.name,
  subscribers: data.subs,
  subscribers_int: 0,
  recent_videos: data.videos
}}));
"""
    result = _run_browser_script(script)
    if "error" not in result:
        result["subscribers_int"] = _parse_sub_count(result.get("subscribers", ""))
        for v in result.get("recent_videos", []):
            v["views_int"] = _parse_view_count(v.get("views", ""))
    return result


# ─── Tool: Browse YouTube Home ────────────────────────────────────────────────

def tool_browse_youtube_home() -> dict:
    """Browse YouTube homepage to see trending/recommended videos."""
    script = f"""
const page = await browser.getPage("yt");
await page.goto("https://www.youtube.com", {{waitUntil: "domcontentloaded"}});
await page.waitForTimeout(3000);
{_COOKIE_DISMISS}

// Scroll to load more
for (let i = 0; i < 3; i++) {{
  await page.evaluate(() => window.scrollBy(0, 1000));
  await page.waitForTimeout(1000);
}}

const videos = await page.evaluate(() => {{
  const items = document.querySelectorAll("ytd-rich-item-renderer");
  return Array.from(items).slice(0, 20).map(item => {{
    const titleEl = item.querySelector("#video-title, #video-title-link");
    const channelEl = item.querySelector("ytd-channel-name a, ytd-channel-name #text");
    const metaEl = item.querySelectorAll("#metadata-line span");
    const thumbEl = item.querySelector("a#thumbnail");
    return {{
      title: titleEl?.textContent?.trim() || "",
      channel: channelEl?.textContent?.trim() || "",
      views: metaEl[0]?.textContent?.trim() || "",
      age: metaEl[1]?.textContent?.trim() || "",
      href: thumbEl?.getAttribute("href") || "",
    }};
  }}).filter(v => v.title.length > 0);
}});

console.log(JSON.stringify({{
  source: "youtube_home",
  videos_found: videos.length,
  videos: videos
}}));
"""
    result = _run_browser_script(script, timeout=60)
    if "error" not in result:
        for v in result.get("videos", []):
            v["views_int"] = _parse_view_count(v.get("views", ""))
    return result


# ─── Tool: Browse Related Videos ──────────────────────────────────────────────

def tool_browse_related_videos(video_url: str) -> dict:
    """Extract related/suggested videos from a YouTube video sidebar."""
    if not video_url.startswith("http"):
        video_url = f"https://www.youtube.com/watch?v={video_url}"

    script = f"""
const page = await browser.getPage("yt");
await page.goto("{video_url}", {{waitUntil: "domcontentloaded"}});
await page.waitForTimeout(3000);
{_COOKIE_DISMISS}

const related = await page.evaluate(() => {{
  const items = document.querySelectorAll("ytd-compact-video-renderer");
  return Array.from(items).slice(0, 15).map(item => {{
    const titleEl = item.querySelector("#video-title");
    const channelEl = item.querySelector("ytd-channel-name #text, .ytd-channel-name");
    const metaEl = item.querySelector("#metadata-line span");
    const thumbEl = item.querySelector("a");
    return {{
      title: titleEl?.textContent?.trim() || "",
      channel: channelEl?.textContent?.trim() || "",
      views: metaEl?.textContent?.trim() || "",
      href: thumbEl?.getAttribute("href") || "",
    }};
  }}).filter(v => v.title.length > 0);
}});

console.log(JSON.stringify({{
  source_video: "{video_url}",
  related_count: related.length,
  related_videos: related
}}));
"""
    result = _run_browser_script(script)
    if "error" not in result:
        for v in result.get("related_videos", []):
            v["views_int"] = _parse_view_count(v.get("views", ""))
    return result


# ─── Tool Registry ────────────────────────────────────────────────────────────

# Note: execute_tool() in browser_tools.py calls fn(**kwargs), so these must accept keyword args
def _wrap_browse_youtube_search(query="", **kw):
    return tool_browse_youtube_search(query)

def _wrap_browse_video_page(video_url="", url="", **kw):
    return tool_browse_video_page(video_url or url)

def _wrap_browse_video_comments(video_url="", url="", **kw):
    return tool_browse_video_comments(video_url or url)

def _wrap_browse_channel_page(channel_url="", url="", **kw):
    return tool_browse_channel_page(channel_url or url)

def _wrap_browse_youtube_home(**kw):
    return tool_browse_youtube_home()

def _wrap_browse_related_videos(video_url="", url="", **kw):
    return tool_browse_related_videos(video_url or url)


BROWSER_TOOL_MAP = {
    "browse_youtube_search": _wrap_browse_youtube_search,
    "browse_video_page": _wrap_browse_video_page,
    "browse_video_comments": _wrap_browse_video_comments,
    "browse_channel_page": _wrap_browse_channel_page,
    "browse_youtube_home": _wrap_browse_youtube_home,
    "browse_related_videos": _wrap_browse_related_videos,
}

BROWSER_TOOL_DESCRIPTIONS = {
    "browse_youtube_search": {
        "description": "Search YouTube and scrape the results page. Returns video titles, URLs, channel names, view counts, and upload dates. COMPLETELY FREE — no API quota!",
        "cost": "FREE",
        "args": "query (str): YouTube search query",
    },
    "browse_video_page": {
        "description": "Visit a YouTube video page. Returns title, view count, channel name, subscriber count, description text, and detected product links (gumroad, whop, etsy, discord, etc.). Use this to check if there's something to SELL.",
        "cost": "FREE",
        "args": "video_url (str): YouTube video URL or video ID",
    },
    "browse_video_comments": {
        "description": "Read top 30 comments from a YouTube video. Detects buying signals like 'where do I get this?', 'link?', 'does this work?'. This is the STRONGEST indicator of monetizable demand.",
        "cost": "FREE",
        "args": "video_url (str): YouTube video URL or video ID",
    },
    "browse_channel_page": {
        "description": "Visit a YouTube channel's videos tab. Returns channel name, subscriber count, and recent videos with view counts. Use to verify if a SMALL channel is getting outsized views.",
        "cost": "FREE",
        "args": "channel_url (str): YouTube channel URL",
    },
    "browse_youtube_home": {
        "description": "Browse YouTube's homepage to see what's trending and recommended. Good for discovering unexpected topics.",
        "cost": "FREE",
        "args": "none",
    },
    "browse_related_videos": {
        "description": "Extract related/suggested videos from a YouTube video's sidebar. Follow the rabbit hole to discover adjacent niches.",
        "cost": "FREE",
        "args": "video_url (str): YouTube video URL or video ID",
    },
}
