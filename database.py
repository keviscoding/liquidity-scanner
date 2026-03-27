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
                    parent_chain, scanned_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_id, i, s.term, s.overall_score, s.liquidity_score,
                s.velocity_score, s.recency_score, s.competition_score, s.specificity_score,
                s.total_results, s.videos_last_30d, s.avg_views, s.avg_views_per_day,
                s.avg_channel_subs, s.view_to_sub_ratio, s.small_channels_pct,
                s.best_video.title if s.best_video else "",
                s.best_video.view_count if s.best_video else 0,
                s.best_video_channel_subs,
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
