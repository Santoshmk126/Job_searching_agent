from datetime import datetime, timezone
from unittest.mock import patch
import pytest

from edgedash.config import Config
import edgedash.storage as storage
from edgedash.query.ask import ask


@pytest.fixture
def ask_env(tmp_path):
    db_file = str(tmp_path / "test_ask.db")
    storage.init_db(db_file)
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.upsert_listings([
        {
            "id": "j1", "title": "AI Engineer", "company": "Acme Corp", "location": "Bengaluru",
            "url": "https://example.com/1", "description": "Python, Docker", "source": "test",
            "posted_at": now_iso, "fetched_at": now_iso, "fit_score": 90, "fit_reason": "High fit",
        }
    ], db_path=db_file)
    storage.log_cycle("orchestrator", now_iso, now_iso, 1, "complete", '{"verdict": {"passed": true}}', db_path=db_file)
    return Config(
        target_role="AI Engineer", target_city="Bengaluru", keywords=[], my_skills=[],
        experience_years=1, db_path=db_file, min_fit_score=70
    )


def test_ask_outside_registry_refuses_cleanly(ask_env):
    """Confirm asking outside registry refuses and lists capabilities (Rule 45)."""
    # Mock LLM returning null for unmatchable question
    with patch("edgedash.llm.complete_json", return_value={"tool": None, "params": {}, "confidence": "high"}):
        answer = ask("should I take a pay cut for a remote role?", config=ask_env)

    assert answer.tool_used is None
    assert answer.rows == []
    assert "outside the scope of my verified job intelligence queries" in answer.text
    assert "Which companies are hiring" in answer.text
    assert "What are my top" in answer.text

    # Verify query was logged to query_log
    with storage._get_connection(ask_env.db_path) as conn:
        row = conn.execute("SELECT * FROM query_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["question"] == "should I take a pay cut for a remote role?"
        assert row["is_answerable"] == 0
        assert row["tool_chosen"] is None


def test_ask_valid_query(ask_env):
    """Test valid query routes, executes, phrases, and logs to query_log."""
    def mock_complete(prompt, schema, **kwargs):
        if "query router" in prompt.lower():
            return {"tool": "companies_hiring", "params": {"days": 7}, "confidence": "high"}
        return {"answer": "Acme Corp is actively hiring with 1 job listing in the last 7 days."}

    with patch("edgedash.llm.complete_json", side_effect=mock_complete):
        answer = ask("which companies are hiring?", config=ask_env)

    assert answer.tool_used == "companies_hiring"
    assert len(answer.rows) >= 1
    assert "Acme Corp" in answer.text

    # Verify logged
    with storage._get_connection(ask_env.db_path) as conn:
        row = conn.execute("SELECT * FROM query_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row["tool_chosen"] == "companies_hiring"
        assert row["is_answerable"] == 1


def test_ask_hallucinated_tool_raises_hard_error(ask_env):
    """Test that model hallucinating an unknown tool raises ValueError immediately (Rule 40)."""
    with patch("edgedash.llm.complete_json", return_value={"tool": "sql_generator_tool", "params": {}}):
        with pytest.raises(ValueError, match="Router returned invalid tool"):
            ask("give me all data", config=ask_env)
