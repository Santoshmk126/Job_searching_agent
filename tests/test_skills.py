import pytest
from edgedash.skills import canonical

ALIASES: dict[str, str] = {
    "k8s": "kubernetes",
    "node": "nodejs",
    "nodejs": "nodejs",
    "node.js": "nodejs",
    "js": "javascript",
    "postgres": "postgres",
    "postgresql": "postgres",
    "psql": "postgres",
    "gcp": "gcp",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "ci/cd": "ci/cd",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
}


def test_case_normalization() -> None:
    assert canonical("PYTHON", ALIASES) == "python"
    assert canonical("PostgreSQL", ALIASES) == "postgres"
    assert canonical("K8S", ALIASES) == "kubernetes"
    assert canonical("ML", ALIASES) == "machine learning"


def test_whitespace_normalization() -> None:
    assert canonical("   python   ", ALIASES) == "python"
    assert canonical("machine   learning", ALIASES) == "machine learning"
    assert canonical("  ci   cd  ", ALIASES) == "ci/cd"


def test_parentheses_removal() -> None:
    assert canonical("kubernetes (eks)", ALIASES) == "kubernetes"
    assert canonical("python (3.11+)", ALIASES) == "python"
    assert canonical("postgres (rds/aurora)", ALIASES) == "postgres"
    assert canonical("react [v18]", ALIASES) == "react"


def test_aliased_term() -> None:
    assert canonical("k8s", ALIASES) == "kubernetes"
    assert canonical("psql", ALIASES) == "postgres"
    assert canonical("google cloud platform", ALIASES) == "gcp"
    assert canonical("node.js", ALIASES) == "nodejs"
    assert canonical("node", ALIASES) == "nodejs"
    assert canonical("js", ALIASES) == "javascript"
    assert canonical("cicd", ALIASES) == "ci/cd"


def test_unaliased_term() -> None:
    assert canonical("fastapi", ALIASES) == "fastapi"
    assert canonical("snowflake", ALIASES) == "snowflake"
    assert canonical("terraform", ALIASES) == "terraform"


def test_empty_string() -> None:
    assert canonical("", ALIASES) == ""
    assert canonical("   ", ALIASES) == ""
    assert canonical(None, ALIASES) == ""  # type: ignore


from edgedash.skills import check_proposal_conflicts, suggest_aliases


def test_conflict_detection_distinct_entries() -> None:
    # Existing alias map keeps node and javascript separate
    alias_map = {
        "node": "nodejs",
        "nodejs": "nodejs",
        "js": "javascript",
        "javascript": "javascript",
    }
    # LLM proposes grouping node and javascript into javascript
    bad_proposal = {
        "canonical": "javascript",
        "variants": ["javascript", "node"],
        "confidence": "high",
    }
    conflicts = check_proposal_conflicts(bad_proposal, alias_map)
    assert len(conflicts) > 0
    assert any("mapped to different skills" in c for c in conflicts)


def test_conflict_detection_override_existing_target() -> None:
    alias_map = {"ts": "typescript"}
    bad_proposal = {
        "canonical": "web",
        "variants": ["ts"],
        "confidence": "low",
    }
    conflicts = check_proposal_conflicts(bad_proposal, alias_map)
    assert len(conflicts) > 0
    assert any("already mapped to 'typescript'" in c for c in conflicts)


def test_no_conflict_for_new_variants() -> None:
    alias_map = {"python": "python"}
    good_proposal = {
        "canonical": "german",
        "variants": ["deutsch", "deutschkenntnisse", "german"],
        "confidence": "high",
    }
    conflicts = check_proposal_conflicts(good_proposal, alias_map)
    assert len(conflicts) == 0


def test_suggest_aliases_warning_and_output(capsys, monkeypatch) -> None:
    class MockLLM:
        @staticmethod
        def complete_json(prompt, schema, config=None):
            return {
                "proposals": [
                    {
                        "canonical": "german",
                        "variants": ["deutsch", "german"],
                        "confidence": "high",
                    },
                    {
                        "canonical": "javascript",
                        "variants": ["js", "node"],
                        "confidence": "high",
                    },
                ]
            }

    from dataclasses import replace
    from edgedash.config import load_config
    cfg = replace(load_config(), skill_aliases={"js": "javascript", "node": "nodejs"})

    suggest_aliases(config=cfg, llm_module=MockLLM)
    captured = capsys.readouterr().out

    # 1. Warning must be present
    assert "WARNING: Automated LLM suggestions REQUIRE human review" in captured
    assert "Merging distinct skills" in captured and "far worse than leaving them separate" in captured

    # 2. Conflicting proposal flagged loudly
    assert "CONFLICT WITH EXISTING ALIAS MAP (Proposal: 'javascript'" in captured
    assert "REJECTED: Your existing config.yaml choices take precedence" in captured

    # 3. Valid proposal formatted as ready-to-paste YAML
    assert '  "deutsch": "german"' in captured
    assert '  "german": "german"' in captured
