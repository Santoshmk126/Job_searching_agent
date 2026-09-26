from datetime import datetime, timezone
from typing import Any
from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config
from edgedash.sources.base import SOURCES
import edgedash.sources  # ensures all registered sources are loaded
import edgedash.storage as storage
from edgedash.storage import generate_listing_id


class Fetcher(Agent):
    name: str = "fetcher"

    def run(self, config: Config, storage_module: Any = storage) -> AgentResult:
        store = storage_module or storage
        source_names = config.sources if config.sources else ["arbeitnow"]
        source_summaries: list[str] = []
        total_new = 0

        for src_name in source_names:
            if src_name not in SOURCES:
                msg = f"Unknown source '{src_name}'"
                print(f"[{self.name}] WARNING: {msg}")
                store.log_cycle(
                    agent=f"fetcher:{src_name}",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    records_touched=0,
                    status="failed",
                    notes=msg,
                    db_path=config.db_path,
                )
                source_summaries.append(f"{src_name}: FAILED (unknown source)")
                continue

            src_cls = SOURCES[src_name]
            src = src_cls()
            start_iso = datetime.now(timezone.utc).isoformat()
            try:
                rows = src.fetch(config)
                for r in rows:
                    r["id"] = generate_listing_id(r["source"], r["url"])

                new_count = store.upsert_listings(rows, db_path=config.db_path)
                total_new += new_count
                end_iso = datetime.now(timezone.utc).isoformat()

                store.log_cycle(
                    agent=f"fetcher:{src_name}",
                    started_at=start_iso,
                    finished_at=end_iso,
                    records_touched=len(rows),
                    status="ok",
                    notes=f"Fetched {len(rows)} rows ({new_count} new)",
                    db_path=config.db_path,
                )
                source_summaries.append(f"{src_name}: {len(rows)} rows ({new_count} new)")
            except Exception as exc:
                end_iso = datetime.now(timezone.utc).isoformat()
                print(f"[{self.name}] WARNING: Source '{src_name}' failed: {exc}")
                store.log_cycle(
                    agent=f"fetcher:{src_name}",
                    started_at=start_iso,
                    finished_at=end_iso,
                    records_touched=0,
                    status="failed",
                    notes=str(exc),
                    db_path=config.db_path,
                )
                source_summaries.append(f"{src_name}: FAILED ({exc})")

        notes = " | ".join(source_summaries) if source_summaries else "No sources configured"
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=total_new,
            notes=notes,
        )
