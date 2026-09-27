# EdgeDash

EdgeDash is an autonomous career intelligence loop designed to run on a daily schedule. It aggregates live job listings, evaluates fit against candidate profile attributes, extracts skill discrepancies, self-verifies data integrity, and surfaces actionable opportunities via a read-only Streamlit dashboard.

---

## Current Skill Gap Focus

**Number One Gap**: **Kubernetes** (Opportunity Cost: 5.63 across 14 blocked listings) — Deploying a containerized ML serving pipeline on a local K3s cluster with Helm charts to bridge orchestration requirements for high-fit roles.

---

## Architecture

```text
+-------------------+
| Trigger (6 AM)    |
+---------+---------+
          |
          v
+---------+---------+
|   Orchestrator    |
+----+----+----+----+
     |    |    |
     |    |    +--------------------+
     |    +---------------+         |
     v                    v         v
+---------+          +---------+  +-------------+
| Fetcher |          | Scorer  |  | GapAnalyzer |
+----+----+          +----+----+  +------+------+
     |                    |              |
     +--------------------+--------------+
                          |
                          v
                +---------+---------+
                |     Verifier      |
                +---------+---------+
                          |
                          v
                +---------+---------+
                |  Storage (SQLite) |
                +---------+---------+
                          |
                          v
                +---------+---------+
                | Dashboard (read-only) |
                +-------------------+
```

---

## Implementation Status

- [x] **Core Architecture & Storage**:
  - Configuration loader & schema validation (`edgedash/config.py`, `config.yaml`)
  - Isolated SQLite storage interface with SHA-256 deduplication (`edgedash/storage.py`)
  - Unified agent contract protocol (`edgedash/agents/base.py`)
  - Mock fetcher for testing and dedup verification (`edgedash/agents/mock_fetcher.py` - temporary)
  - Orchestrator loop with state inspection & cycle telemetry (`edgedash/orchestrator.py`)
  - Single-cycle CLI runner (`run_cycle.py`)
- [ ] **Live Ingestion & Verification**:
  - Real job board fetcher integration
  - Schema normalizer & deduplication pipeline
  - Output integrity Verifier agent
- [ ] **Scoring & Skill Gap Analysis**:
  - AI candidate fit scorer
  - Skill gap analysis agent & frequency tracker
- [ ] **Dashboard & Automation**:
  - Read-only Streamlit dashboard
  - Automated scheduled 6 AM trigger
  - Hosted PostgreSQL storage migration

---

## Setup

### Prerequisites
- Python 3.11+

### Installation
```bash
git clone <repo-url>
cd Interview
pip install pyyaml
```

### Configuration
Edit `config.yaml` at the project root to define your target search parameters:
```yaml
target_role: "Data Analyst"
target_city: "Bengaluru"
keywords:
  - "SQL"
  - "Python"
  - "Power BI"
my_skills:
  - "Python"
  - "SQL"
  - "Pandas"
experience_years: 1
db_path: "edgedash.db"
min_fit_score: 70
```

### Execution
Run one orchestrator cycle:
```bash
python run_cycle.py
```

---

## Design Decisions

- **Isolated Storage**: All database interactions are encapsulated inside `edgedash/storage.py` through a minimal interface. This prevents SQL queries from leaking into agent logic and ensures migrating from SQLite to hosted PostgreSQL requires changing only one file.
- **Stable Hash IDs**: Each listing ID is a deterministic SHA-256 digest of `source:url`. This guarantees idempotency across repeated crawls, preventing duplicate rows and providing observable deduplication metrics.
- **Orchestrator Delegation**: The orchestrator acts purely as a coordinator that evaluates system state and delegates work to specialized sub-agents. It never fetches or scores directly, preserving separation of concerns and allowing individual agents to be swapped or tested in isolation.
