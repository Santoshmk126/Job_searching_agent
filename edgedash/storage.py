from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

_current_db_path: str = "edgedash.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT,
    source TEXT NOT NULL,
    posted_at TEXT,
    fetched_at TEXT NOT NULL,
    fit_score INTEGER,
    fit_reason TEXT
);
CREATE TABLE IF NOT EXISTS skill_gaps (
    skill TEXT PRIMARY KEY,
    frequency INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    records_touched INTEGER NOT NULL,
    status TEXT NOT NULL,
    notes TEXT
);
"""


def _get_connection(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or _current_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def generate_listing_id(source: str, url: str) -> str:
    return hashlib.sha256(f"{source.strip().lower()}:{url.strip()}".encode()).hexdigest()


def init_db(path: str = "edgedash.db") -> None:
    global _current_db_path
    _current_db_path = path
    db_file = Path(path)
    if db_file.parent and not db_file.parent.exists():
        db_file.parent.mkdir(parents=True, exist_ok=True)
    with _get_connection(path) as conn:
        conn.executescript(_SCHEMA)


def upsert_listings(rows: list[dict[str, Any]], db_path: str | None = None) -> int:
    new_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    sql = """
    INSERT OR IGNORE INTO listings (
        id, title, company, location, url, description,
        source, posted_at, fetched_at, fit_score, fit_reason
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _get_connection(db_path) as conn:
        cursor = conn.cursor()
        for r in rows:
            lid = r.get("id") or generate_listing_id(r["source"], r["url"])
            cursor.execute(
                sql,
                (
                    lid, r["title"], r["company"], r.get("location"),
                    r["url"], r.get("description"), r["source"],
                    r.get("posted_at"), r.get("fetched_at") or now_iso,
                    r.get("fit_score"), r.get("fit_reason"),
                ),
            )
            new_count += cursor.rowcount
    return new_count


def count_unscored(db_path: str | None = None) -> int:
    with _get_connection(db_path) as conn:
        res = conn.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NULL").fetchone()
        return int(res[0]) if res else 0


def last_fetch_time(db_path: str | None = None) -> str | None:
    with _get_connection(db_path) as conn:
        res = conn.execute("SELECT MAX(fetched_at) FROM listings").fetchone()
        return str(res[0]) if (res and res[0] is not None) else None


def log_cycle(
    agent: str, started_at: str, finished_at: str,
    records_touched: int, status: str, notes: str | None = None,
    db_path: str | None = None,
) -> None:
    sql = """
    INSERT INTO cycle_log (agent, started_at, finished_at, records_touched, status, notes)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    with _get_connection(db_path) as conn:
        conn.execute(sql, (agent, started_at, finished_at, records_touched, status, notes))


def get_listings(
    limit: int = 50, min_score: int | None = None, db_path: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM listings"
    params: list[Any] = []
    if min_score is not None:
        query += " WHERE fit_score >= ?"
        params.append(min_score)
    query += " ORDER BY posted_at DESC, fetched_at DESC LIMIT ?"
    params.append(limit)
    with _get_connection(db_path) as conn:
        return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
