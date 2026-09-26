from datetime import datetime, timezone
from typing import Any
import uuid

from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config


class MockFetcher(Agent):
    name: str = "mock_fetcher"

    def _generate_listings(self, config: Config) -> list[dict[str, Any]]:
        role = config.target_role
        city = config.target_city
        now_iso = datetime.now(timezone.utc).isoformat()

        # 4 stable listings identical across all runs to demonstrate deduplication
        stable_listings: list[dict[str, Any]] = [
            {
                "title": f"Junior {role}",
                "company": "DataBridge Analytics",
                "location": city,
                "url": f"https://jobs.example.com/stable/{city.lower()}/databridge-101",
                "description": "Looking for entry-level analyst proficient in SQL, Python, and Excel for reporting.",
                "source": "mock_board",
                "posted_at": "2026-09-20T09:00:00Z",
                "fetched_at": now_iso,
            },
            {
                "title": f"{role}",
                "company": "RetailPulse Tech",
                "location": city,
                "url": f"https://jobs.example.com/stable/{city.lower()}/retailpulse-102",
                "description": "Mid-level position building Power BI dashboards and automating ETL with Python & Pandas.",
                "source": "mock_board",
                "posted_at": "2026-09-21T10:30:00Z",
                "fetched_at": now_iso,
            },
            {
                "title": f"Senior {role}",
                "company": "CloudScale Insights",
                "location": city,
                "url": f"https://jobs.example.com/stable/{city.lower()}/cloudscale-103",
                "description": "Senior contributor needed for Tableau reporting, advanced SQL, and data warehouse modeling.",
                "source": "mock_board",
                "posted_at": "2026-09-22T14:15:00Z",
                "fetched_at": now_iso,
            },
            {
                "title": f"Lead {role} & BI Specialist",
                "company": "FinPeak Systems",
                "location": city,
                "url": f"https://jobs.example.com/stable/{city.lower()}/finpeak-104",
                "description": "Lead analytics team, drive KPI strategy using SQL, dbt, Snowflake, and Power BI.",
                "source": "mock_board",
                "posted_at": "2026-09-23T11:00:00Z",
                "fetched_at": now_iso,
            },
        ]

        # 8 dynamic listings generated fresh per run
        companies = [
            ("Apex Logistics", "Associate", "Manage operational dashboards using SQL and Power BI."),
            ("Zeta Commerce", "Product", "Analyze user conversion funnels with Python, Pandas, and SQL."),
            ("Nova Health", "Healthcare", "EHR data transformations using SQL, Tableau, and Python."),
            ("UrbanKart", "Growth", "A/B testing analytics with statistical modeling and Excel."),
            ("QuantMetrics", "Quantitative", "Time-series forecasting, SQL data pipelines, and dashboards."),
            ("Optima Media", "Digital Marketing", "Campaign tracking using Power BI, Google Analytics, and SQL."),
            ("NexGen Mobility", "IoT", "Telemetry analysis using Python, Spark, and Postgres."),
            ("TrueEdge AI", "AI Systems", "Build evaluation datasets and metrics using Python, SQL, and LLMs."),
        ]

        dynamic_listings: list[dict[str, Any]] = []
        for i, (company, prefix, desc) in enumerate(companies, start=1):
            unique_token = uuid.uuid4().hex[:8]
            dynamic_listings.append(
                {
                    "title": f"{prefix} {role}",
                    "company": company,
                    "location": city,
                    "url": f"https://jobs.example.com/dynamic/{city.lower()}/{company.lower().replace(' ', '-')}-{unique_token}",
                    "description": desc,
                    "source": "mock_board",
                    "posted_at": now_iso,
                    "fetched_at": now_iso,
                }
            )

        return stable_listings + dynamic_listings

    def run(self, config: Config, storage: Any) -> AgentResult:
        listings = self._generate_listings(config)
        new_count = storage.upsert_listings(listings, db_path=config.db_path)
        dupe_count = len(listings) - new_count
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=new_count,
            notes=f"Processed {len(listings)} listings ({new_count} new, {dupe_count} deduplicated)",
        )
