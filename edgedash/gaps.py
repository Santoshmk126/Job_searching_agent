from datetime import datetime, timezone
import sys
from typing import Any

from edgedash.config import load_config
import edgedash.storage as storage


def _parse_iso(iso_str: str) -> datetime:
    try:
        return datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    except Exception:
        return datetime.now(timezone.utc)


def compute_gap_trends(
    runs: list[dict[str, Any]],
    earliest_gaps: list[dict[str, Any]],
    latest_gaps: list[dict[str, Any]],
    latest_all_gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pure deterministic gap trend calculation (Rules 22, 25)."""
    if not runs:
        return {'status': 'empty', 'message': 'No skill gap snapshots found in database.'}

    if len(runs) == 1:
        s_dt = _parse_iso(runs[0].get('computed_at', ''))
        return {
            'status': 'single',
            'run_id': runs[0].get('run_id'),
            'snapshot_date': s_dt.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'days_needed': 1,
            'message': 'Only one snapshot recorded so far. 1 more day of runs needed.',
        }

    e_run, l_run = runs[0], runs[-1]
    e_dt, l_dt = _parse_iso(e_run.get('computed_at', '')), _parse_iso(l_run.get('computed_at', ''))
    days = (l_dt.date() - e_dt.date()).days
    w_suffix = f'{days} day' + ('s' if days > 1 else '') + ' apart' if days > 0 else 'same-day runs'
    window_str = f"{e_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} to {l_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} ({w_suffix})"

    e_map, e_top10 = {g['skill']: g for g in earliest_gaps}, [g['skill'] for g in earliest_gaps[:10]]
    l_top10 = latest_gaps[:10]
    l_top10_set, l_all_map = {g['skill']: g for g in l_top10}, {g['skill']: g for g in (latest_all_gaps or latest_gaps)}

    top_10_trends = []
    for idx, g in enumerate(l_top10, 1):
        s, l_cost = g['skill'], g['opportunity_cost']
        if s not in e_map:
            top_10_trends.append({'rank': idx, 'skill': s, 'earliest_cost': None, 'latest_cost': l_cost, 'diff_abs': l_cost, 'diff_pct': None, 'is_new': True, 'status': 'NEW'})
        else:
            e_cost = e_map[s]['opportunity_cost']
            diff = round(l_cost - e_cost, 2)
            pct = round((diff / e_cost) * 100.0, 1) if e_cost > 0 else 0.0
            st = 'RISING' if diff > 0 else ('FALLING' if diff < 0 else 'FLAT')
            top_10_trends.append({'rank': idx, 'skill': s, 'earliest_cost': e_cost, 'latest_cost': l_cost, 'diff_abs': diff, 'diff_pct': pct, 'is_new': False, 'status': st})

    dropped_out = []
    for s in e_top10:
        if s not in l_top10_set:
            e_cost = e_map[s]['opportunity_cost']
            l_cost = l_all_map[s]['opportunity_cost'] if s in l_all_map else None
            diff = round((l_cost or 0.0) - e_cost, 2)
            pct = round((diff / e_cost) * 100.0, 1) if e_cost > 0 else 0.0
            dropped_out.append({'skill': s, 'earliest_cost': e_cost, 'latest_cost': l_cost, 'diff_abs': diff, 'diff_pct': pct, 'status': 'DROPPED OUT'})

    return {
        'status': 'ok',
        'earliest_run_id': e_run.get('run_id'),
        'latest_run_id': l_run.get('run_id'),
        'earliest_date': e_dt.strftime('%Y-%m-%d %H:%M:%S UTC'),
        'latest_date': l_dt.strftime('%Y-%m-%d %H:%M:%S UTC'),
        'window_str': window_str,
        'days_apart': days,
        'top_10_trends': top_10_trends,
        'dropped_out': dropped_out,
    }


def get_gap_trends(db_path: str | None = None) -> dict[str, Any]:
    """Retrieve snapshots from storage and compute trend metrics."""
    cfg = load_config()
    target_db = db_path or cfg.db_path
    runs = storage.get_snapshot_runs(db_path=target_db)
    if not runs:
        return {'status': 'empty', 'message': 'No skill gap snapshots found in database.'}
    if len(runs) == 1:
        return compute_gap_trends(runs, [], [])

    earliest_gaps = storage.get_snapshot_gaps(runs[0]['run_id'], limit=50, db_path=target_db)
    latest_gaps = storage.get_snapshot_gaps(runs[-1]['run_id'], limit=10, db_path=target_db)
    latest_all = storage.get_snapshot_gaps(runs[-1]['run_id'], limit=50, db_path=target_db)
    return compute_gap_trends(runs, earliest_gaps, latest_gaps, latest_all)


def print_gap_trends(db_path: str | None = None) -> None:
    trends = get_gap_trends(db_path=db_path)
    status = trends.get('status')

    if status == 'empty':
        print()
        print('[!] No skill gap snapshots found in database.')
        print('    Run a cycle to generate your first snapshot.')
        print()
        return

    if status == 'single':
        print('=' * 88)
        print('                   EDGEDASH SKILL GAPS TREND REPORT')
        print('=' * 88)
        print(f"Snapshot Date : {trends['snapshot_date']} (Run ID: {trends['run_id']})")
        print('-' * 88)
        print('[!] Only one snapshot recorded so far.')
        print('    At least 2 snapshot runs are needed to compute a trend.')
        print(f"    {trends['days_needed']} more day of runs needed to show a trend.")
        print('    (Deterministic policy: No trend fabricated, interpolated, or extrapolated from 1 point.)')
        print('=' * 88)
        print()
        return

    print('=' * 92)
    print('                          EDGEDASH SKILL GAPS TREND REPORT')
    print('=' * 92)
    print(f"Comparison Window : {trends['window_str']}")
    print(f"Earliest Snapshot : {trends['earliest_date']} ({trends['earliest_run_id']})")
    print(f"Latest Snapshot   : {trends['latest_date']} ({trends['latest_run_id']})")
    print('=' * 92)
    print('CURRENT TOP 10 SKILL GAPS:')
    print(f"{'#':<3} {'Skill':<22} {'Earliest':<11} {'Latest':<11} {'Change (Abs)':<15} {'Change (%)':<13} {'Status':<12}")
    print('-' * 92)

    for item in trends['top_10_trends']:
        r, s = item['rank'], item['skill']
        e_str = f"{item['earliest_cost']:.2f}" if item['earliest_cost'] is not None else '—'
        l_str = f"{item['latest_cost']:.2f}"
        diff_str = f"+{item['diff_abs']:.2f}" if item['is_new'] else f"{item['diff_abs']:+.2f}"
        pct_str = 'NEW' if item['is_new'] else f"{item['diff_pct']:+.1f}%"
        print(f"{r:<3} {s:<22} {e_str:<11} {l_str:<11} {diff_str:<15} {pct_str:<13} {item['status']:<12}")

    print('-' * 92)
    print('SKILLS DROPPED OUT OF TOP 10 (since earliest snapshot):')
    if not trends['dropped_out']:
        print('  None (all skills from earliest top 10 remain in current top 10)')
    else:
        print(f"{'#':<3} {'Skill':<22} {'Earliest':<11} {'Latest':<11} {'Change (Abs)':<15} {'Change (%)':<13} {'Status':<12}")
        print('-' * 92)
        for item in trends['dropped_out']:
            s = item['skill']
            e_str = f"{item['earliest_cost']:.2f}"
            l_str = f"{item['latest_cost']:.2f}" if item['latest_cost'] is not None else '—'
            diff_str = f"{item['diff_abs']:+.2f}"
            pct_str = f"{item['diff_pct']:+.1f}%"
            print(f"-   {s:<22} {e_str:<11} {l_str:<11} {diff_str:<15} {pct_str:<13} {item['status']:<12}")

    print('=' * 92)
    print('Note: Opportunity cost = sum(listing.score / 100) for blocked listings.')
    print("      'NEW' = skill was not present in earliest snapshot.")
    print("      'DROPPED OUT' = in earliest top 10, but dropped out of current top 10.")
    print()


def print_latest_gaps(limit: int = 10) -> None:
    cfg = load_config()
    gaps = storage.get_latest_skill_gaps(limit=limit, db_path=cfg.db_path)
    if not gaps:
        print()
        print('[!] No skill gap snapshots found in database.')
        print('    Run a cycle to generate your first snapshot.')
        print()
        return

    time_str = _parse_iso(gaps[0].get('computed_at', '')).strftime('%Y-%m-%d %H:%M:%S UTC')
    print('=' * 86)
    print(f"                EDGEDASH TOP {len(gaps)} SKILL GAPS REPORT (LATEST SNAPSHOT)")
    print(f"Snapshot Time : {time_str} | Run ID: {gaps[0].get('run_id', 'unknown')}")
    print('=' * 86)
    print(f"{'#':<3} {'Skill':<22} {'Blocked':<8} {'Opp Cost':<10} {'Mean Fit':<9} {'Top':<5} {'Relative Weight':<18} {'Conf':<6}")
    print('-' * 86)

    max_cost = max((g.get('opportunity_cost', 0.0) for g in gaps), default=1.0) or 1.0
    for idx, g in enumerate(gaps, 1):
        s, blk, cost = g['skill'], g['listings_blocked'], g['opportunity_cost']
        filled = max(1, int(round((cost / max_cost) * 16))) if cost > 0 else 0
        bar = '█' * filled + '░' * (16 - filled)
        conf_tag = '[!]' if g.get('low_confidence') else ' '
        print(f"{idx:<3} {s:<22} {blk:<8} {cost:<10.2f} {g['mean_score']:<9.1f} {g['top_score']:<5} {bar:<18} {conf_tag:<6}")

    print('-' * 86)
    print('Note: Gaps ranked by Opportunity Cost (Sum of Listing Score / 100).')
    print('      "[!]" = low confidence (computed from < 3 listings).')
    print()


if __name__ == '__main__':
    if '--trend' in sys.argv:
        print_gap_trends()
    else:
        limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), 10)
        print_latest_gaps(limit=limit)
