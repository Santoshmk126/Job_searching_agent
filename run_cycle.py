import sys
from pathlib import Path

# Ensure repo root is on sys.path for clean execution
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edgedash.config import load_config
from edgedash.orchestrator import run_cycle


def main() -> None:
    config = load_config("config.yaml")
    run_cycle(config)


if __name__ == "__main__":
    main()
