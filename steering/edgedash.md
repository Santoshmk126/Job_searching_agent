# EdgeDash Steering Document

## Project Overview
**EdgeDash** is an autonomous AI career intelligence agent. It runs a scheduled loop that fetches live job listings, scores them for fit against a user profile, surfaces skill gaps, verifies its own output, and publishes a Streamlit dashboard.

---

## Architecture (Do Not Deviate Without Explicit Permission)
```
Trigger (scheduled)
       │
       ▼
Orchestrator (the brain)
  ├──> Fetcher (sub-agent)
  ├──> Scorer (sub-agent)
  └──> GapAnalyzer (sub-agent)
       │
       ▼
    Verifier (evaluates results; reruns orchestrator loop on failure)
       │
      Pass
       ▼
Storage (SQLite / interface)
       │
       ▼
Dashboard (Streamlit, read-only)
```

- **Orchestrator**: Reads state and delegates; it **never** fetches or scores directly.
- **Sub-agents**: Each sub-agent has exactly **one goal** and **one stop condition**.
- **Dashboard**: Read-only interface consuming from Storage.

---

## Hard Rules

1. **Python 3.11+ & Standard Library First**: 
   - Prefer standard library. 
   - Add an external dependency only when it genuinely saves real work, and explain why before adding it.
2. **Single Storage Interface**: 
   - ALL storage access must go through a single storage module with a thin interface.
   - No other module may import `sqlite3` directly.
   - Future migration to hosted PostgreSQL must be a clean, one-file change.
3. **No Hardcoded User Data**: 
   - Never hardcode user role, target city, keywords, or skills profile in code. 
   - All user-specific parameters must live in configuration files.
4. **No Secrets in Code**: 
   - Environment variables only, loaded and validated in one central place.
5. **Cycle Logging**: 
   - Every agent run must record an entry to the `cycle_log` table: what ran, when, how many records touched, pass/fail status, and any retry reason.
6. **Fail Loudly**: 
   - No bare `except: pass` or swallowed exceptions. If something fails, surface the error explicitly.
7. **Type Hints & Clean Documentation**: 
   - Full type hints on every function signature. 
   - Add docstrings only where intent is not obvious from the name.
8. **File Size Limit**: 
   - Keep files under ~150 lines. Split modules before size becomes a problem.

---

## NETWORK & SOURCES

9. Every external source lives behind a Source class with a uniform interface. The Fetcher never contains source-specific parsing. Adding a source must never require editing the Fetcher.
10. Every Source returns a list of normalised dicts with EXACTLY these keys: source, external_id, title, company, location, url, description, posted_at, raw. Missing values are None, never empty string, never "N/A".
11. All network calls go through one helper with a timeout (10s default), explicit retry (2 attempts, exponential backoff), and a User-Agent header. No bare requests.get anywhere else in the codebase.
12. A source failing must NEVER kill the cycle. Catch per-source, log the failure to cycle_log with status "failed", continue to the next source. One dead job board must not stop the other sources.
13. Secrets come from environment variables via a .env file that is gitignored. Never a literal key in code, never a key in config.yaml. If a key is missing, that source skips itself with a clear log line — it does not crash the cycle.
14. Respect the source. Rate limit to at most 1 request per second per source, set a real User-Agent, and honour any documented page limits.

---

## Coding Style & Execution Guidelines

- **Style**: Small, testable, modular functions. Plain, readable Python over clever/complex Python.
- **Explanations**: Include an explanatory note at the end summarizing what the code does.
- **Scope Discipline**: When asked for one module, build only that module. Do not scaffold the entire application ahead of time.
