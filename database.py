"""SQLite database layer for scan jobs and results."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from config import DATA_DIR

DB_PATH = DATA_DIR / "scanner.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                status      TEXT NOT NULL DEFAULT 'pending',
                mode        TEXT NOT NULL DEFAULT 'full',
                config      TEXT NOT NULL DEFAULT '{}',
                started_at  TEXT,
                finished_at TEXT,
                created_at  TEXT NOT NULL,
                error       TEXT
            );

            CREATE TABLE IF NOT EXISTS niche_results (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id             INTEGER NOT NULL REFERENCES scans(id),
                rank                INTEGER,
                term                TEXT NOT NULL,
                overall_score       REAL,
                liquidity_score     REAL,
                velocity_score      REAL,
                recency_score       REAL,
                competition_score   REAL,
                specificity_score   REAL,
                total_results       INTEGER,
                videos_last_30d     INTEGER,
                avg_views           REAL,
                avg_views_per_day   REAL,
                avg_channel_subs    REAL,
                view_to_sub_ratio   REAL,
                small_channels_pct  REAL,
                best_video_title    TEXT,
                best_video_views    INTEGER,
                best_video_channel_subs INTEGER,
                top_channels        TEXT,
                parent_chain        TEXT,
                scanned_at          TEXT
            );

            CREATE TABLE IF NOT EXISTS scan_progress (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id     INTEGER NOT NULL REFERENCES scans(id),
                message     TEXT NOT NULL,
                step        TEXT,
                pct         INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_analyses (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id             INTEGER NOT NULL REFERENCES scans(id),
                term                TEXT NOT NULL,
                confidence          TEXT,
                quick_rating        INTEGER,
                quick_reason        TEXT,
                opportunity_type    TEXT,
                buying_intent       TEXT,
                competition_summary TEXT,
                timing              TEXT,
                monetization        TEXT,
                risks               TEXT,
                action_plan         TEXT,
                full_briefing       TEXT,
                model_used          TEXT,
                tokens_used         INTEGER,
                analyzed_at         TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id         INTEGER REFERENCES scans(id),
                direction       TEXT NOT NULL,
                max_iterations  INTEGER,
                steps           TEXT,
                candidates_found INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'running',
                started_at      TEXT,
                finished_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS trend_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                term            TEXT NOT NULL,
                scan_id         INTEGER REFERENCES scans(id),
                overall_score   REAL,
                videos_30d      INTEGER,
                avg_views       REAL,
                avg_subs        REAL,
                ai_confidence   TEXT,
                snapshot_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trend_term ON trend_snapshots(term);
            CREATE INDEX IF NOT EXISTS idx_ai_scan ON ai_analyses(scan_id);
        """)


# --- Scans ---

def create_scan(config: dict, mode: str = "full") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO scans (status, mode, config, created_at) VALUES (?, ?, ?, ?)",
            ("pending", mode, json.dumps(config), datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def update_scan_status(scan_id: int, status: str, error: str = None):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        if status == "running":
            conn.execute(
                "UPDATE scans SET status=?, started_at=? WHERE id=?",
                (status, now, scan_id),
            )
        else:
            conn.execute(
                "UPDATE scans SET status=?, finished_at=?, error=? WHERE id=?",
                (status, now, error, scan_id),
            )


def get_scan(scan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        return dict(row) if row else None


def list_scans() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.*, COUNT(r.id) as result_count FROM scans s "
            "LEFT JOIN niche_results r ON r.scan_id = s.id "
            "GROUP BY s.id ORDER BY s.id DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]


# --- Results ---

def save_results(scan_id: int, scores):
    from models import NicheScore
    with get_conn() as conn:
        conn.execute("DELETE FROM niche_results WHERE scan_id=?", (scan_id,))
        for i, s in enumerate(scores, 1):
            conn.execute("""
                INSERT INTO niche_results (
                    scan_id, rank, term, overall_score, liquidity_score,
                    velocity_score, recency_score, competition_score, specificity_score,
                    total_results, videos_last_30d, avg_views, avg_views_per_day,
                    avg_channel_subs, view_to_sub_ratio, small_channels_pct,
                    best_video_title, best_video_views, best_video_channel_subs,
                    top_channels, parent_chain, scanned_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_id, i, s.term, s.overall_score, s.liquidity_score,
                s.velocity_score, s.recency_score, s.competition_score, s.specificity_score,
                s.total_results, s.videos_last_30d, s.avg_views, s.avg_views_per_day,
                s.avg_channel_subs, s.view_to_sub_ratio, s.small_channels_pct,
                s.best_video.title if s.best_video else "",
                s.best_video.view_count if s.best_video else 0,
                s.best_video_channel_subs,
                " | ".join(s.top_channels) if s.top_channels else "",
                " > ".join(s.parent_chain),
                s.searched_at.isoformat(),
            ))


def get_results(scan_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM niche_results WHERE scan_id=? ORDER BY rank",
            (scan_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- Progress ---

def add_progress(scan_id: int, message: str, step: str = "", pct: int = 0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scan_progress (scan_id, message, step, pct, created_at) VALUES (?,?,?,?,?)",
            (scan_id, message, step, pct, datetime.utcnow().isoformat()),
        )


def get_progress(scan_id: int, since_id: int = 0) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scan_progress WHERE scan_id=? AND id>? ORDER BY id",
            (scan_id, since_id),
        ).fetchall()
        return [dict(r) for r in rows]


# --- AI Analyses ---

def save_ai_analyses(scan_id: int, analyses):
    import json as _json
    with get_conn() as conn:
        conn.execute("DELETE FROM ai_analyses WHERE scan_id=?", (scan_id,))
        for a in analyses:
            conn.execute("""
                INSERT INTO ai_analyses (
                    scan_id, term, confidence, quick_rating, quick_reason,
                    opportunity_type, buying_intent, competition_summary,
                    timing, monetization, risks, action_plan,
                    full_briefing, model_used, tokens_used, analyzed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_id, a.term, a.confidence, a.quick_rating, a.quick_reason,
                a.opportunity_type,
                _json.dumps(a.buying_intent_signals),
                a.competition_summary,
                a.timing,
                _json.dumps(a.monetization_angles),
                _json.dumps(a.risks),
                _json.dumps(a.action_plan),
                a.full_briefing,
                a.model_used, a.tokens_used,
                a.analyzed_at.isoformat() if hasattr(a.analyzed_at, 'isoformat') else str(a.analyzed_at),
            ))


def get_ai_analyses(scan_id: int) -> list[dict]:
    import json as _json
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_analyses WHERE scan_id=? ORDER BY "
            "CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, "
            "quick_rating DESC",
            (scan_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for key in ("buying_intent", "monetization", "risks", "action_plan"):
                try:
                    d[key] = _json.loads(d[key]) if d[key] else []
                except (ValueError, TypeError):
                    d[key] = []
            result.append(d)
        return result


# --- Agent Sessions ---

def save_agent_session(scan_id: int, direction: str, steps: list, candidates_found: int, status: str = "completed"):
    import json as _json
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO agent_sessions (scan_id, direction, max_iterations, steps, candidates_found, status, started_at, finished_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            scan_id, direction, len(steps),
            _json.dumps([{"step": s.step_number, "action": s.action, "reasoning": s.reasoning,
                          "query": s.query, "findings": s.findings[:500]} for s in steps]),
            candidates_found, status,
            steps[0].timestamp.isoformat() if steps else None,
            steps[-1].timestamp.isoformat() if steps else None,
        ))


def get_agent_session(scan_id: int) -> dict | None:
    import json as _json
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agent_sessions WHERE scan_id=? ORDER BY id DESC LIMIT 1", (scan_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["steps"] = _json.loads(d["steps"]) if d["steps"] else []
        except (ValueError, TypeError):
            d["steps"] = []
        return d


# --- Trend Snapshots ---

def save_trend_snapshot(scan_id: int, term: str, overall_score: float, videos_30d: int,
                        avg_views: float, avg_subs: float, ai_confidence: str = ""):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO trend_snapshots (term, scan_id, overall_score, videos_30d, avg_views, avg_subs, ai_confidence, snapshot_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (term, scan_id, overall_score, videos_30d, avg_views, avg_subs, ai_confidence,
              datetime.utcnow().isoformat()))


def get_trend_history(term: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trend_snapshots WHERE term=? ORDER BY snapshot_at DESC LIMIT ?",
            (term, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_trends(min_snapshots: int = 2) -> list[dict]:
    """Get terms with multiple snapshots for trend analysis."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT term, COUNT(*) as snapshot_count,
                   MAX(overall_score) as peak_score,
                   MIN(snapshot_at) as first_seen,
                   MAX(snapshot_at) as last_seen
            FROM trend_snapshots
            GROUP BY term
            HAVING COUNT(*) >= ?
            ORDER BY peak_score DESC
        """, (min_snapshots,)).fetchall()
        return [dict(r) for r in rows]
