import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path for clean execution
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edgedash.config import load_config
from edgedash.orchestrator import run_cycle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EdgeDash Autonomous Career Intelligence Cycle"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect state, render plan, and exit without executing or writing to storage.",
    )
    parser.add_argument(
        "--force",
        action="append",
        metavar="AGENT",
        help="Force the named agent to run even if skipped by state (repeatable).",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print full system state and decision explanations.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration YAML (default: config.yaml).",
    )

    args = parser.parse_args()
    config = load_config(args.config)
    run_cycle(
        config,
        dry_run=args.dry_run,
        force_agents=args.force,
        explain=args.explain,
    )


if __name__ == "__main__":
    main()
