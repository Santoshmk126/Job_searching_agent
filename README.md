# EdgeDash

EdgeDash is an autonomous career intelligence loop designed to run on a daily schedule. It aggregates live job listings across multiple sources, extracts structured requirements, evaluates fit against candidate profile attributes using deterministic scoring, surfaces prioritized skill gaps weighted by opportunity cost, and tracks longitudinal trends across immutable snapshots.

---

## Current Skill Gap Focus

> **Top Ranked Gap**: **Kubernetes** (Opportunity Cost: 5.63 across 14 blocked listings) — Deploying a containerized ML serving pipeline on a local K3s cluster with Helm charts to bridge orchestration requirements for high-fit roles.

---

## Architecture

```text
               +-------------------+
               |  Trigger (6 AM)   |
               +---------+---------+
                         |
                         v
               +---------+---------+
               |   Orchestrator    |
               +----+----+----+----+
                    |    |    |
     +--------------+    |    +--------------------+
     |                   |                         |
     v                   v                         v
+---------+         +---------+              +-------------+
| Fetcher |         | Scorer  |              | GapAnalyzer |
+----+----+         +----+----+              +------+------+
     |                   |                          |
     | (Sources:         | (LLM extracts facts;     | (Deterministic
     |  Arbeitnow,       |  Python computes         |  weighted
     |  Apify)           |  fit score)              |  opportunity cost)
     |                   |                          |
     +-------------------+--------------------------+
                         |
                         v
               +---------+---------+
               |  Storage (SQLite) |
               |  - raw_listings   |
               |  - extracted_facts|
               |  - scores         |
               |  - skill_gaps     |
               |  - cycle_log      |
               +---------+---------+
                         |
                         v
          +--------------+--------------+
          |                             |
          v                             v
+-------------------+         +-------------------+
|  CLI Intelligence |         | Dashboard (Future)|
|  - gaps & trends  |         | (Streamlit,       |
|  - alias audit    |         |  read-only)       |
+-------------------+         +-------------------+
```

---

## Implementation Status

- [x] **Core Architecture & Storage (Rules 1–8)**:
  - Central configuration loader & schema validation (`edgedash/config.py`, `config.yaml`)
  - Isolated SQLite storage interface with SHA-256 deduplication and cycle telemetry (`edgedash/storage.py`)
  - Unified agent contract protocol (`edgedash/agents/base.py`)
  - Orchestrator coordinator loop with cycle diagnostics (`edgedash/orchestrator.py`)
  - Single-cycle CLI runner (`run_cycle.py`)
- [x] **Live Ingestion & Normalization (Rules 9–14)**:
  - Uniform `Source` plugin interface (`edgedash/sources/base.py`)
  - Live job board integrations: Arbeitnow (`edgedash/sources/arbeitnow.py`) and Apify Actor (`edgedash/sources/apify.py`)
  - Resilient HTTP gateway with exponential backoff, rate limiting, and timeout guards (`edgedash/sources/http.py`)
  - Schema normalization and deduplication pipeline (`edgedash/normalizer.py`)
- [x] **Intelligence & Deterministic Scoring (Rules 15–21)**:
  - Centralized LLM gateway with strict rate limiting & model switching (`edgedash/llm.py`)
  - Structured fact extraction with schema validation and repair (`edgedash/agents/extractor.py`)
  - Deterministic fit scoring arithmetic in pure Python (`edgedash/scoring.py`)
  - Component-generated human-readable explanations (Rule 19)
  - Batch capping and score distribution telemetry (Rules 20–21)
- [x] **Aggregate Analysis & Skill Gap Intelligence (Rules 22–27)**:
  - Pure deterministic gap computation engine (`edgedash/agents/gap_analyzer.py`)
  - Fit-score weighted opportunity cost: opportunity_cost = sum(score / 100) (Rule 24)
  - User-owned explicit alias canonicalization map (`edgedash/skills.py`, Rule 23)
  - Interactive skill audit CLI (`python -m edgedash.skills --audit`)
  - Strictly read-only LLM alias suggester with loud conflict rejection (`python -m edgedash.skills --suggest-aliases`)
  - Append-only immutable snapshot persistence with historical trend comparison (`python -m edgedash.gaps --trend`, Rule 25)
  - Full row-level traceability down to specific listing IDs (`python -m edgedash.gaps --trace <skill>`, Rule 26)
  - Sample size reporting and low-confidence flags (N < 3) (Rule 27)
- [ ] **Dashboard & Scheduled Automation**:
  - Read-only Streamlit dashboard
  - Automated 6 AM scheduled cron runner
  - Hosted PostgreSQL storage migration

---

## Setup & Installation

### Prerequisites
- Python 3.11+
- Virtual environment tool (`venv`)

### Installation
```bash
git clone https://github.com/Santoshmk126/edgedash.git
cd edgedash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables
Create a `.env` file in the project root (gitignored):
```bash
cp .env.example .env
```
Populate your API keys:
```dotenv
GEMINI_API_KEY=your_gemini_api_key_here
APIFY_TOKEN=your_apify_token_here  # optional, for Apify job scrapers
```

---

## Configuration (`config.yaml`)

Edit `config.yaml` to specify your target job search, skills profile, and scoring parameters:

```yaml
target_role: "AI / Machine Learning Engineer"
target_city: "Bengaluru"
keywords:
  - "AI Engineer"
  - "Machine Learning Engineer"
  - "LLMs"
  - "PyTorch"

my_skills:
  - "Python"
  - "PyTorch"
  - "Scikit-Learn"
  - "Pandas"
  - "NumPy"
  - "SQL"
  - "Docker"
  - "Git"

experience_years: 1
db_path: "edgedash.db"
min_fit_score: 70

sources:
  - "arbeitnow"
  # - "apify"

# LLM Gateway (Rule 15)
llm_provider: "gemini"
llm_model: "gemini-3.1-flash-lite"

# Deterministic Scoring (Rules 16 & 21)
target_seniority: "junior"
score_batch_size: 25
scoring_weights:
  skill_match: 0.45
  seniority_fit: 0.25
  location_fit: 0.15
  recency: 0.15

# User-owned Alias Map (Rule 23)
skill_aliases:
  k8s: "kubernetes"
  kubernetes: "kubernetes"
  js: "javascript"
  node: "nodejs"
  node.js: "nodejs"
  postgres: "postgres"
  postgresql: "postgres"
  gcp: "gcp"
  google cloud: "gcp"
```

---

## CLI & Command Reference

### 1. Run Pipeline Cycle
Execute one complete autonomous ingestion, extraction, scoring, and gap analysis cycle:
```bash
python run_cycle.py
```

### 2. View Top Skill Gaps
Print the top 10 prioritized skill gaps with relative opportunity cost bar charts and confidence indicators:
```bash
python -m edgedash.gaps
```

### 3. Track Longitudinal Trends
Compare the latest snapshot against earlier snapshots to observe emerging and fading skill gaps over time:
```bash
python -m edgedash.gaps --trend
```

### 4. Trace Gap to Raw Source Listings (Rule 26)
Inspect the exact job listings, companies, fit scores, and extracted skills that contributed to a specific skill gap:
```bash
python -m edgedash.gaps --trace "kubernetes"
```

### 5. Audit Skill Canonicalization
Review unmapped variants, frequency counts, and verify how raw skills map to canonical forms:
```bash
python -m edgedash.skills --audit
```

### 6. Suggest Skill Aliases (Strictly Read-Only)
Ask Gemini to suggest canonical aliases for frequently occurring unmapped terms. Per Rule 23, this tool never writes to disk; it outputs ready-to-paste YAML for your review:
```bash
python -m edgedash.skills --suggest-aliases
```

### 7. Verify LLM Connectivity
Check your configured LLM provider, credentials, and rate limits:
```bash
python -m edgedash.llm --check
```

### 8. Run Unit Test Suite
Execute the comprehensive test suite:
```bash
python3 -m pytest
```

---

## Core Engineering Principles

- **Deterministic Arithmetic (Rule 16 & 22)**: LLMs extract structured facts from unformatted text only. All scoring calculations and aggregate rankings are computed using deterministic Python algorithms. The LLM never sees scoring weights or produces aggregate metrics.
- **Weighted Opportunity Cost (Rule 24)**: Skill gaps are ranked by the quality of the opportunities they unlock (`opportunity_cost = sum(score / 100)`). A missing skill on an 85-fit job matters significantly more than a missing skill on a 20-fit job.
- **User-Owned Taxonomy (Rule 23)**: Skill groupings are never decided by fuzzy algorithms or AI auto-merging. Canonicalization is controlled strictly by the user via `skill_aliases` in `config.yaml`.
- **Immutable Snapshots (Rule 25)**: Every gap analysis run appends an immutable snapshot to the database. Trend analysis evaluates real historical change rather than overwriting previous observations.
- **Row-Level Traceability (Rule 26)**: Every aggregate number can be audited down to the specific listing IDs and rows that produced it.
- **Isolated Storage (Rule 2)**: Database access is strictly encapsulated behind `edgedash/storage.py`, facilitating seamless migration to PostgreSQL without changes to agent logic.
- **Strict Line Count Discipline (Rule 8)**: Modules are kept compact and testable (< 200 lines per file).
