from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

_current_db_path: str = "edgedash.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT NOT NULL,
    location TEXT, url TEXT NOT NULL, description TEXT, source TEXT NOT NULL,
    posted_at TEXT, fetched_at TEXT NOT NULL, fit_score INTEGER, fit_reason TEXT,
    scored_at TEXT, fit_components TEXT
);
CREATE TABLE IF NOT EXISTS extraction_cache (
    description_hash TEXT PRIMARY KEY, extracted_data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_gaps (
    skill TEXT PRIMARY KEY, frequency INTEGER NOT NULL DEFAULT 1, last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL, records_touched INTEGER NOT NULL, status TEXT NOT NULL, notes TEXT
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
        # Safe migration for existing tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
        if "scored_at" not in cols:
            conn.execute("ALTER TABLE listings ADD COLUMN scored_at TEXT")
        if "fit_components" not in cols:
            conn.execute("ALTER TABLE listings ADD COLUMN fit_components TEXT")


def upsert_listings(rows: list[dict[str, Any]], db_path: str | None = None) -> int:
    new_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    sql = """
    INSERT OR IGNORE INTO listings (
        id, title, company, location, url, description, source, posted_at, fetched_at, fit_score, fit_reason
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _get_connection(db_path) as conn:
        cur = conn.cursor()
        for r in rows:
            lid = r.get("id") or generate_listing_id(r["source"], r["url"])
            cur.execute(sql, (
                lid, r["title"], r["company"], r.get("location"), r["url"],
                r.get("description"), r["source"], r.get("posted_at"),
                r.get("fetched_at") or now_iso, r.get("fit_score"), r.get("fit_reason")
            ))
            new_count += cur.rowcount
    return new_count


def count_unscored(db_path: str | None = None) -> int:
    with _get_connection(db_path) as conn:
        res = conn.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NULL").fetchone()
        return int(res[0]) if res else 0


def last_fetch_time(db_path: str | None = None) -> str | None:
    with _get_connection(db_path) as conn:
        res = conn.execute("SELECT MAX(fetched_at) FROM listings").fetchone()
        return str(res[0]) if (res and res[0] is not None) else None


def log_cycle(agent: str, started_at: str, finished_at: str, records_touched: int, status: str, notes: str | None = None, db_path: str | None = None) -> None:
    sql = "INSERT INTO cycle_log (agent, started_at, finished_at, records_touched, status, notes) VALUES (?, ?, ?, ?, ?, ?)"
    with _get_connection(db_path) as conn:
        conn.execute(sql, (agent, started_at, finished_at, records_touched, status, notes))


def get_listings(limit: int = 50, min_score: int | None = None, db_path: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM listings"
    params: list[Any] = []
    if min_score is not None:
        query += " WHERE fit_score >= ?"
        params.append(min_score)
    query += " ORDER BY posted_at DESC, fetched_at DESC LIMIT ?"
    params.append(limit)
    with _get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]


def get_unscored_listings(limit: int = 25, db_path: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM listings WHERE fit_score IS NULL ORDER BY fetched_at DESC LIMIT ?"
    with _get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, (limit,)).fetchall()]


def update_listing_score(listing_id: str, score: int, reason: str, components: dict[str, Any] | None = None, scored_at: str | None = None, db_path: str | None = None) -> None:
    now_iso = scored_at or datetime.now(timezone.utc).isoformat()
    comp_json = json.dumps(components) if components else None
    query = "UPDATE listings SET fit_score = ?, fit_reason = ?, fit_components = ?, scored_at = ? WHERE id = ?"
    with _get_connection(db_path) as conn:
        conn.execute(query, (score, reason, comp_json, now_iso, listing_id))


def clear_scores(listing_id: str | None = None, db_path: str | None = None) -> int:
    sql = "UPDATE listings SET fit_score = NULL, fit_reason = NULL, scored_at = NULL, fit_components = NULL"
    params: tuple[Any, ...] = ()
    if listing_id:
        sql += " WHERE id = ? AND fit_score IS NOT NULL"
        params = (listing_id,)
    else:
        sql += " WHERE fit_score IS NOT NULL"
    with _get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.rowcount


def get_cached_extraction(desc_hash: str, db_path: str | None = None) -> dict[str, Any] | None:
    with _get_connection(db_path) as conn:
        row = conn.execute("SELECT extracted_data FROM extraction_cache WHERE description_hash = ?", (desc_hash,)).fetchone()
        return json.loads(row[0]) if (row and row[0]) else None


def save_cached_extraction(desc_hash: str, data: dict[str, Any], db_path: str | None = None) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    sql = "INSERT OR REPLACE INTO extraction_cache (description_hash, extracted_data, created_at) VALUES (?, ?, ?)"
    with _get_connection(db_path) as conn:
        conn.execute(sql, (desc_hash, json.dumps(data), now_iso))


def get_diagnostics(db_path: str | None = None) -> dict[str, Any]:
    with _get_connection(db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
        per_src = {r[0]: int(r[1]) for r in conn.execute("SELECT source, COUNT(*) FROM listings GROUP BY source ORDER BY COUNT(*) DESC").fetchall()}
        dupes_sql = "SELECT LOWER(TRIM(title)) AS title, LOWER(TRIM(company)) AS company, COUNT(DISTINCT source) AS src_count, COUNT(*) AS total_count FROM listings GROUP BY LOWER(TRIM(title)), LOWER(TRIM(company)) HAVING COUNT(DISTINCT source) > 1"
        cross_dupes = [dict(r) for r in conn.execute(dupes_sql).fetchall()]
        recent = [dict(r) for r in conn.execute("SELECT source, title, company, location, posted_at, fetched_at FROM listings ORDER BY fetched_at DESC, posted_at DESC LIMIT 5").fetchall()]
        quality = [dict(r) for r in conn.execute("SELECT id, source, title, company, url FROM listings WHERE url IS NULL OR TRIM(url) = '' OR title IS NULL OR TRIM(title) = '' OR company IS NULL OR TRIM(company) = ''").fetchall()]
        return {"total_listings": total, "per_source": per_src, "cross_source_duplicates": cross_dupes, "recent_listings": recent, "quality_issues": quality}
