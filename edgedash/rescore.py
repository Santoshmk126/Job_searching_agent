import argparse
import sys
from edgedash.config import load_config
import edgedash.storage as storage


def rescore(all_flag: bool = False, listing_id: str | None = None, auto_confirm: bool = False) -> int:
    config = load_config()
    storage.init_db(config.db_path)

    if all_flag:
        if not auto_confirm:
            try:
                confirm = input("⚠️  Are you sure you want to clear ALL listing scores? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                return 0
            if confirm not in ("y", "yes"):
                print("Operation cancelled. No scores were cleared.")
                return 0

        count = storage.clear_scores(db_path=config.db_path)
        print(f"\n✓ Cleared {count} score(s) across all listings.")
    elif listing_id:
        count = storage.clear_scores(listing_id=listing_id.strip(), db_path=config.db_path)
        if count > 0:
            print(f"\n✓ Cleared score for listing ID '{listing_id}'.")
        else:
            print(f"\nListing '{listing_id}' not found or had no score to clear.")
    else:
        print("Please specify either --all or --id <listing_id>.")
        return 0

    print("Note: Extraction cache was preserved (0 model API calls required to re-score).")
    print("\nNext step: Run the orchestrator cycle to re-score:")
    print("  python run_cycle.py")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EdgeDash Re-scoring Escape Hatch (Rule 18)",
        epilog="Clears scoring state without touching the extraction cache."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Clear scores for all listings")
    group.add_argument("--id", type=str, metavar="LISTING_ID", help="Clear score for a specific listing ID")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt for --all")

    args = parser.parse_args()
    rescore(all_flag=args.all, listing_id=args.id, auto_confirm=args.yes)


if __name__ == "__main__":
    main()
