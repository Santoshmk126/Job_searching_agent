import sys
from edgedash.config import load_config
from edgedash.storage import get_diagnostics


def main() -> None:
    try:
        config = load_config("config.yaml")
        db_path = config.db_path
    except Exception:
        db_path = "edgedash.db"

    diag = get_diagnostics(db_path)

    print("=" * 70)
    print("                    EDGEDASH DATABASE DIAGNOSTICS")
    print("=" * 70)
    print(f"Target Database : {db_path}")
    print(f"Total Listings  : {diag['total_listings']}")
    print("-" * 70)
    print("1. LISTINGS PER SOURCE:")
    if diag["per_source"]:
        for src, count in diag["per_source"].items():
            print(f"   * {src:<15} : {count:>5} listing(s)")
    else:
        print("   (Database is empty)")

    print("-" * 70)
    print("2. PROBABLE CROSS-SOURCE DUPLICATES (Same Title + Company across sources):")
    cross_dupes = diag["cross_source_duplicates"]
    if cross_dupes:
        print(f"   Found {len(cross_dupes)} group(s) of probable cross-source duplicates:")
        for d in cross_dupes:
            print(f"   ! '{d['title']}' at '{d['company']}' (present in {d['src_count']} sources, {d['total_count']} rows)")
    else:
        print("   ✓ None detected (0 cross-source duplicates)")

    print("-" * 70)
    print("3. FIVE MOST RECENT LISTINGS:")
    recent = diag["recent_listings"]
    if recent:
        for idx, r in enumerate(recent, 1):
            print(f"   [{idx}] [{r['source']}] {r['title']} | Company: {r['company']}")
            print(f"       Location: {r.get('location') or 'Not specified'} | Fetched: {r['fetched_at']}")
    else:
        print("   (No listings available)")

    print("-" * 70)
    print("4. DATA QUALITY AUDIT (Missing URL, Title, or Company):")
    issues = diag["quality_issues"]
    if issues:
        print(f"   ⚠️ WARNING: Found {len(issues)} record(s) with missing critical fields:")
        for item in issues:
            print(f"   - ID: {item['id'][:12]}.. | Source: {item['source']} | Title: {item['title']!r} | Company: {item['company']!r}")
    else:
        print("   ✓ All records healthy (0 missing/empty URLs, titles, or companies)")
    print("=" * 70)


if __name__ == "__main__":
    main()
