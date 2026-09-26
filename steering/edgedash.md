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

## Coding Style & Execution Guidelines

- **Style**: Small, testable, modular functions. Plain, readable Python over clever/complex Python.
- **Explanations**: Include an explanatory note at the end summarizing what the code does.
- **Scope Discipline**: When asked for one module, build only that module. Do not scaffold the entire application ahead of time.
