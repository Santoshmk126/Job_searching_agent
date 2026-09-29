from datetime import datetime, timezone
import hashlib, json, sqlite3
from pathlib import Path
from typing import Any

_current_db_path: str = "edgedash.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, url TEXT NOT NULL,
    description TEXT, source TEXT NOT NULL, posted_at TEXT, fetched_at TEXT NOT NULL, fit_score INTEGER,
    fit_reason TEXT, scored_at TEXT, fit_components TEXT
);
CREATE TABLE IF NOT EXISTS extraction_cache (
    description_hash TEXT PRIMARY KEY, extracted_data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, computed_at TEXT NOT NULL,
    skill TEXT NOT NULL, listings_blocked INTEGER NOT NULL, opportunity_cost REAL NOT NULL,
    mean_score REAL NOT NULL, top_score INTEGER NOT NULL, example_ids TEXT NOT NULL,
    also_nice_to_have INTEGER NOT NULL DEFAULT 0, low_confidence BOOLEAN NOT NULL DEFAULT 0
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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _get_connection(path) as conn:
        conn.executescript(_SCHEMA)
        cols_gaps = {r[1] for r in conn.execute("PRAGMA table_info(skill_gaps)").fetchall()}
        if "run_id" not in cols_gaps:
            conn.execute("DROP TABLE IF EXISTS skill_gaps")
            conn.executescript(_SCHEMA)


def upsert_listings(rows: list[dict[str, Any]], db_path: str | None = None) -> int:
    new_count, now_iso = 0, datetime.now(timezone.utc).isoformat()
    sql = "INSERT OR IGNORE INTO listings (id, title, company, location, url, description, source, posted_at, fetched_at, fit_score, fit_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    with _get_connection(db_path) as conn:
        cur = conn.cursor()
        for r in rows:
            lid = r.get("id") or generate_listing_id(r["source"], r["url"])
            cur.execute(sql, (lid, r["title"], r["company"], r.get("location"), r["url"], r.get("description"), r["source"], r.get("posted_at"), r.get("fetched_at") or now_iso, r.get("fit_score"), r.get("fit_reason")))
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
    with _get_connection(db_path) as conn:
        conn.execute("INSERT INTO cycle_log (agent, started_at, finished_at, records_touched, status, notes) VALUES (?, ?, ?, ?, ?, ?)", (agent, started_at, finished_at, records_touched, status, notes))


def get_listings(limit: int = 50, min_score: int | None = None, db_path: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM listings" + (" WHERE fit_score >= ?" if min_score is not None else "") + " ORDER BY posted_at DESC, fetched_at DESC LIMIT ?"
    params = [min_score, limit] if min_score is not None else [limit]
    with _get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]


def get_unscored_listings(limit: int = 25, db_path: str | None = None) -> list[dict[str, Any]]:
    with _get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM listings WHERE fit_score IS NULL ORDER BY fetched_at DESC LIMIT ?", (limit,)).fetchall()]


def update_listing_score(listing_id: str, score: int, reason: str, components: dict[str, Any] | None = None, scored_at: str | None = None, db_path: str | None = None) -> None:
    now_iso, comp_json = scored_at or datetime.now(timezone.utc).isoformat(), json.dumps(components) if components else None
    with _get_connection(db_path) as conn:
        conn.execute("UPDATE listings SET fit_score = ?, fit_reason = ?, fit_components = ?, scored_at = ? WHERE id = ?", (score, reason, comp_json, now_iso, listing_id))


def clear_scores(listing_id: str | None = None, db_path: str | None = None) -> int:
    sql = "UPDATE listings SET fit_score = NULL, fit_reason = NULL, scored_at = NULL, fit_components = NULL"
    params = (listing_id,) if listing_id else ()
    sql += " WHERE id = ? AND fit_score IS NOT NULL" if listing_id else " WHERE fit_score IS NOT NULL"
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
    with _get_connection(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO extraction_cache (description_hash, extracted_data, created_at) VALUES (?, ?, ?)", (desc_hash, json.dumps(data), now_iso))


def get_all_extracted_skills(db_path: str | None = None) -> list[str]:
    skills: list[str] = []
    with _get_connection(db_path) as conn:
        for r in conn.execute("SELECT extracted_data FROM extraction_cache").fetchall():
            try:
                skills.extend(json.loads(r[0]).get("required_skills", []))
            except Exception:
                continue
    return skills


def get_scored_listings_with_facts(db_path: str | None = None) -> list[dict[str, Any]]:
    with _get_connection(db_path) as conn:
        rows = conn.execute("SELECT id, title, fit_score, description FROM listings WHERE fit_score IS NOT NULL").fetchall()
        result = []
        for r in rows:
            h = hashlib.sha256((r["description"] or "").strip().encode("utf-8")).hexdigest()
            crow = conn.execute("SELECT extracted_data FROM extraction_cache WHERE description_hash = ?", (h,)).fetchone()
            if crow and crow[0]:
                try:
                    result.append({"id": r["id"], "title": r["title"], "score": int(r["fit_score"]), "facts": json.loads(crow[0])})
                except Exception:
                    continue
        return result


def save_skill_gaps_snapshot(run_id: str, computed_at: str, gaps: list[dict[str, Any]], db_path: str | None = None) -> int:
    sql = "INSERT INTO skill_gaps (run_id, computed_at, skill, listings_blocked, opportunity_cost, mean_score, top_score, example_ids, also_nice_to_have, low_confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    with _get_connection(db_path) as conn:
        cur = conn.cursor()
        for g in gaps:
            cur.execute(sql, (run_id, computed_at, g["skill"], g["listings_blocked"], g["opportunity_cost"], g["mean_score"], g["top_score"], json.dumps(g.get("example_ids", [])), g.get("also_nice_to_have", 0), 1 if g.get("low_confidence") else 0))
        return len(gaps)


def get_latest_skill_gaps(limit: int = 10, db_path: str | None = None) -> list[dict[str, Any]]:
    with _get_connection(db_path) as conn:
        latest = conn.execute("SELECT run_id FROM skill_gaps ORDER BY id DESC LIMIT 1").fetchone()
        if not latest:
            return []
        return get_snapshot_gaps(latest[0], limit=limit, db_path=db_path)


def get_snapshot_runs(db_path: str | None = None) -> list[dict[str, Any]]:
    """Return distinct snapshot runs in chronological order."""
    with _get_connection(db_path) as conn:
        sql = "SELECT run_id, computed_at, COUNT(*) as gap_count FROM skill_gaps GROUP BY run_id, computed_at ORDER BY MIN(id) ASC"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_snapshot_gaps(run_id: str, limit: int = 10, db_path: str | None = None) -> list[dict[str, Any]]:
    """Return gap records for a specific snapshot run."""
    with _get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM skill_gaps WHERE run_id = ? ORDER BY opportunity_cost DESC, listings_blocked DESC LIMIT ?", (run_id, limit)).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            try:
                d["example_ids"] = json.loads(d["example_ids"])
            except Exception:
                pass
            res.append(d)
        return res


def get_diagnostics(db_path: str | None = None) -> dict[str, Any]:
    with _get_connection(db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
        per_src = {r[0]: int(r[1]) for r in conn.execute("SELECT source, COUNT(*) FROM listings GROUP BY source ORDER BY COUNT(*) DESC").fetchall()}
        dupes_sql = "SELECT LOWER(TRIM(title)) AS title, LOWER(TRIM(company)) AS company, COUNT(DISTINCT source) AS src_count, COUNT(*) AS total_count FROM listings GROUP BY LOWER(TRIM(title)), LOWER(TRIM(company)) HAVING COUNT(DISTINCT source) > 1"
        cross_dupes = [dict(r) for r in conn.execute(dupes_sql).fetchall()]
        recent = [dict(r) for r in conn.execute("SELECT source, title, company, location, posted_at, fetched_at FROM listings ORDER BY fetched_at DESC, posted_at DESC LIMIT 5").fetchall()]
        quality = [dict(r) for r in conn.execute("SELECT id, source, title, company, url FROM listings WHERE url IS NULL OR TRIM(url) = '' OR title IS NULL OR TRIM(title) = '' OR company IS NULL OR TRIM(company) = ''").fetchall()]
        return {"total_listings": total, "per_source": per_src, "cross_source_duplicates": cross_dupes, "recent_listings": recent, "quality_issues": quality}


def latest_gap_snapshot_time(db_path: str | None = None) -> str | None:
    with _get_connection(db_path) as conn:
        res = conn.execute("SELECT MAX(computed_at) FROM skill_gaps").fetchone()
        return str(res[0]) if (res and res[0] is not None) else None


def has_scores_newer_than(iso_timestamp: str, db_path: str | None = None) -> bool:
    with _get_connection(db_path) as conn:
        res = conn.execute(
            "SELECT 1 FROM listings WHERE fit_score IS NOT NULL AND scored_at > ? LIMIT 1",
            (iso_timestamp,)
        ).fetchone()
        return bool(res)


def last_cycle_info(db_path: str | None = None) -> tuple[str | None, str | None]:
    with _get_connection(db_path) as conn:
        res = conn.execute(
            "SELECT status, finished_at FROM cycle_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if res:
            return str(res[0]), str(res[1])
        return None, None
