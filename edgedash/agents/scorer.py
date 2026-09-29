import time
from datetime import datetime, timezone
from typing import Any
from edgedash.agents.base import Agent, AgentResult
from edgedash.agents.extractor import extract
from edgedash.config import Config
from edgedash.scoring import score_listing
import edgedash.storage as storage


class Scorer(Agent):
    name: str = "scorer"

    def run(
        self,
        config: Config,
        storage_module: Any = storage,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        store = storage_module or storage
        batch_size = (
            stop_conditions.get("max_items")
            if stop_conditions and "max_items" in stop_conditions
            else getattr(config, "score_batch_size", 25)
        )
        max_seconds = (
            stop_conditions.get("max_seconds")
            if stop_conditions and "max_seconds" in stop_conditions
            else getattr(config, "score_max_seconds", 60)
        )
        unscored = store.get_unscored_listings(limit=batch_size, db_path=config.db_path)

        if not unscored:
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="0 unscored listings to evaluate",
            )

        scores: list[int] = []
        failed_count = 0
        cache_hits = 0
        cache_misses = 0

        start_time = time.time()
        for listing in unscored:
            if max_seconds and (time.time() - start_time) >= max_seconds:
                print(f"[{self.name}] Stop condition reached: max_seconds={max_seconds}")
                break
            lid = listing["id"]
            try:
                from edgedash.agents.extractor import compute_description_hash
                h = compute_description_hash(listing.get("description"))
                if store.get_cached_extraction(h, db_path=config.db_path) is not None:
                    cache_hits += 1
                else:
                    cache_misses += 1
                facts = extract(listing, db_path=config.db_path)
                result = score_listing(listing, facts, config)
                score = result["score"]
                reason = result["reason"]
                store.update_listing_score(lid, score, reason, components=result.get("components"), db_path=config.db_path)
                scores.append(score)
            except Exception as exc:
                failed_count += 1
                now_iso = datetime.now(timezone.utc).isoformat()
                store.log_cycle(
                    agent=f"scorer:{lid[:12]}",
                    started_at=now_iso,
                    finished_at=now_iso,
                    records_touched=0,
                    status="failed",
                    notes=f"Extraction/scoring failed: {exc}",
                    db_path=config.db_path,
                )
                print(f"[{self.name}] Skipped listing '{lid[:12]}' due to error: {exc}")
                continue

        count = len(scores)
        if count == 0:
            return AgentResult(
                agent=self.name,
                status="failed" if failed_count > 0 else "ok",
                records_touched=0,
                notes=f"All {failed_count} listings in batch failed extraction/scoring",
            )

        min_val = min(scores)
        max_val = max(scores)
        mean_val = int(round(sum(scores) / count))
        spread = max_val - min_val

        # Rule 20: spread < 10 across multiple records is a suspect run
        is_suspect = (spread < 10 and count > 1)
        status = "suspect" if is_suspect else "ok"
        spread_str = "spread SUSPECT (<10)" if is_suspect else "spread OK"

        notes = (
            f"scored {count} (cache: {cache_hits} hits, {cache_misses} misses) · "
            f"range {min_val}-{max_val} · mean {mean_val} · {failed_count} failed · {spread_str}"
        )

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=count,
            notes=notes,
        )
