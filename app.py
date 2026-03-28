"""FastAPI web application for the YouTube Liquidity Scanner."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

import database as db
import jobs
import quota as quota_tracker
from config import ensure_dirs, YOUTUBE_API_KEY, LLM_API_KEY

ensure_dirs()
db.init_db()

app = FastAPI(title="YouTube Liquidity Scanner")


def _score_class(v):
    if v is None: return "score-none"
    if v >= 75: return "score-great"
    if v >= 55: return "score-good"
    if v >= 35: return "score-ok"
    if v >= 10: return "score-low"
    return "score-none"

def _format_number(v):
    try: return f"{int(v):,}"
    except: return str(v)

BASE = Path(__file__).parent

# Use Jinja2 directly (bypasses Starlette/Jinja2 Python 3.14 compat issue)
_jinja = Environment(loader=FileSystemLoader(str(BASE / "templates")), autoescape=True)
_jinja.filters["score_class"] = _score_class
_jinja.filters["format_number"] = _format_number

def render(name: str, ctx: dict) -> HTMLResponse:
    return HTMLResponse(_jinja.get_template(name).render(**ctx))

app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    scans = db.list_scans()
    usage = quota_tracker.get_usage()
    return render("index.html", {
        "scans": scans,
        "quota_used": usage.get("units_used", 0),
        "quota_remaining": quota_tracker.get_remaining_quota(),
        "quota_total": 10000,
        "searches_remaining": quota_tracker.get_remaining_searches(),
        "has_api_key": bool(YOUTUBE_API_KEY and YOUTUBE_API_KEY != "your_api_key_here"),
    })



# ── API ───────────────────────────────────────────────────────────────────────

class StartScanRequest(BaseModel):
    dry_run: bool = False
    max_searches: int = 50
    max_seeds: int = 25
    max_depth: int = 3
    extra_seeds: list[str] = []
    scan_type: str = "standard"  # standard, agent, rescan, autonomous
    agent_direction: str = ""
    agent_max_iterations: int = 8
    agent_max_youtube: int = 5
    agent_max_steps: int = 25  # for autonomous mode


@app.post("/api/scans")
async def start_scan(req: StartScanRequest):
    if req.scan_type == "agent" and not req.agent_direction:
        raise HTTPException(400, "Agent mode requires a direction")
    if not req.dry_run and req.scan_type not in ("rescan",) and not YOUTUBE_API_KEY:
        raise HTTPException(400, "No YouTube API key configured")
    if not req.dry_run and not quota_tracker.can_afford(200):
        raise HTTPException(400, f"Insufficient quota: {quota_tracker.get_remaining_quota()} units left")
    if req.scan_type == "autonomous" and not LLM_API_KEY:
        raise HTTPException(400, "Autonomous mode requires LLM_API_KEY")

    config = req.model_dump()
    mode = "dry_run" if req.dry_run else req.scan_type
    scan_id = db.create_scan(config, mode=mode)
    jobs.start_scan(scan_id, config)
    return {"scan_id": scan_id, "status": "started"}


@app.get("/api/scans")
async def list_scans():
    return db.list_scans()


@app.get("/api/scans/{scan_id}")
async def get_scan(scan_id: int):
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(404)
    return {
        "scan": scan,
        "results": db.get_results(scan_id),
        "is_running": jobs.is_running(scan_id),
    }


@app.delete("/api/scans/{scan_id}")
async def delete_scan(scan_id: int):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM niche_results WHERE scan_id=?", (scan_id,))
        conn.execute("DELETE FROM scan_progress WHERE scan_id=?", (scan_id,))
        conn.execute("DELETE FROM scans WHERE id=?", (scan_id,))
    return {"ok": True}


@app.get("/api/scans/{scan_id}/stream")
async def stream_progress(scan_id: int):
    """Server-Sent Events stream for live scan progress."""
    async def event_gen():
        last_id = 0
        while True:
            events = db.get_progress(scan_id, since_id=last_id)
            for e in events:
                last_id = e["id"]
                data = json.dumps({"message": e["message"], "step": e["step"], "pct": e["pct"]})
                yield f"data: {data}\n\n"

            scan = db.get_scan(scan_id)
            if scan and scan["status"] in ("completed", "failed"):
                yield f"data: {json.dumps({'done': True, 'status': scan['status']})}\n\n"
                break

            if not events:
                await asyncio.sleep(1)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/quota")
async def get_quota():
    usage = quota_tracker.get_usage()
    return {
        "units_used": usage.get("units_used", 0),
        "units_remaining": quota_tracker.get_remaining_quota(),
        "searches_remaining": quota_tracker.get_remaining_searches(),
        "searches_made": usage.get("searches_made", 0),
        "date": usage.get("date", ""),
    }


@app.get("/api/results/{scan_id}/export")
async def export_results(scan_id: int):
    """Download results as CSV."""
    import csv, io
    results = db.get_results(scan_id)
    if not results:
        raise HTTPException(404, "No results found")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(results[0].keys()))
    writer.writeheader()
    writer.writerows(results)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=scan_{scan_id}_results.csv"},
    )


# ── AI / Agent / Trends Routes ────────────────────────────────────────────────

@app.get("/api/scans/{scan_id}/ai")
async def get_ai_analyses(scan_id: int):
    return db.get_ai_analyses(scan_id)


@app.get("/api/scans/{scan_id}/agent-log")
async def get_agent_log(scan_id: int):
    session = db.get_agent_session(scan_id)
    if not session:
        return {"steps": [], "direction": "", "status": "none"}
    return session


@app.get("/api/trends")
async def get_trends():
    from trend_tracker import detect_risers, detect_newcomers
    trends = db.get_all_trends()
    risers = detect_risers()
    return {"trends": trends, "risers": risers}


@app.get("/api/trends/{term}")
async def get_trend_detail(term: str):
    history = db.get_trend_history(term)
    return {"term": term, "history": history}


@app.get("/scan/{scan_id}", response_class=HTMLResponse)
async def scan_page(scan_id: int):
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    results = db.get_results(scan_id)
    config = json.loads(scan.get("config", "{}"))
    ai_analyses = db.get_ai_analyses(scan_id)
    agent_session = db.get_agent_session(scan_id)

    # Build AI lookup by term
    ai_map = {}
    for a in ai_analyses:
        ai_map[a["term"].lower()] = a

    return render("scan.html", {
        "scan": scan,
        "results": results,
        "config": config,
        "is_running": jobs.is_running(scan_id),
        "ai_analyses": ai_analyses,
        "ai_map": ai_map,
        "agent_session": agent_session,
    })
