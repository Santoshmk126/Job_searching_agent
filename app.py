import json
import urllib.parse
from datetime import datetime
from typing import Any
import streamlit as st
from edgedash.config import load_config
import edgedash.storage as storage

st.set_page_config(
    page_title="EdgeDash — Agent Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .badge-complete { background-color: #2e7d32; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
    .badge-nothing { background-color: #455a64; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
    .badge-partial { background-color: #f57c00; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
    .badge-degraded { background-color: #c62828; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
    .row-degraded { background-color: rgba(198, 40, 40, 0.15) !important; border-left: 4px solid #c62828 !important; }
    .row-partial { background-color: rgba(245, 124, 0, 0.10) !important; border-left: 4px solid #f57c00 !important; }
    .row-complete { border-left: 4px solid #2e7d32 !important; }
    .row-nothing { border-left: 4px solid #78909c !important; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=5)
def load_data(db_path: str):
    """Load records strictly through storage module, scoping data panels to the last passing cycle (Rule 2 & 38)."""
    cycles = storage.get_recent_cycles(limit=30, agent="orchestrator", db_path=db_path)
    latest_verified = storage.get_latest_verified_cycle(db_path=db_path)

    # Rule 38: Every data panel reads from the LAST PASSING CYCLE only!
    verified_as_of = latest_verified.get("finished_at") if latest_verified else None

    total_listings, total_scored = storage.get_listing_counts(as_of=verified_as_of, db_path=db_path)
    top_listings = storage.get_top_scored_listings(limit=10, as_of=verified_as_of, db_path=db_path)
    top_gaps = storage.get_latest_skill_gaps(limit=10, as_of=verified_as_of, db_path=db_path)
    return cycles, latest_verified, total_listings, total_scored, top_listings, top_gaps


def format_ts(ts_str: str | None) -> str:
    if not ts_str:
        return "None"
    try:
        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M:%S UTC")
    except Exception:
        return str(ts_str)[:19]


def main():
    config = load_config()
    cycles, latest_verified, total_listings, total_scored, top_listings, top_gaps = load_data(config.db_path)

    # Empty database state handling
    if not cycles and total_listings == 0:
        st.title("⚡ EdgeDash Autonomous Career Intelligence")
        st.info("No cycles recorded yet. Run python run_cycle.py in your terminal to start the scheduler.")
        return

    latest_cycle = cycles[0] if cycles else None
    latest_status = (latest_cycle.get("status") if latest_cycle else "unknown").lower()
    latest_notes = latest_cycle.get("notes_parsed", {}) if latest_cycle else {}
    latest_verdict = latest_notes.get("verdict", {})
    verdict_passed = latest_verdict.get("passed", True) if latest_verdict else (latest_status != "degraded")

    # =========================================================================
    # SECTION 1: HEADER STRIP
    # =========================================================================
    st.title("⚡ EdgeDash Agent Activity Dashboard")
    st.caption("Autonomous, deterministic career intelligence loop — read-only view.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        verified_ts = latest_verified.get("finished_at") if latest_verified else None
        st.metric("Last Verified Cycle", format_ts(verified_ts))
    with c2:
        st.metric("Total Listings (Verified)", f"{total_listings:,}")
    with c3:
        st.metric("Total Scored (Verified)", f"{total_scored:,}")
    with c4:
        v_label = "PASSING" if verdict_passed else ("DEGRADED" if latest_status == "degraded" else "FAILED")
        st.metric("Current Verdict Status", v_label)

    # Rule 38 warning banner if latest cycle failed or degraded
    if latest_cycle and (latest_status in ("degraded", "failed") or not verdict_passed):
        v_ts = latest_verified.get("finished_at") if latest_verified else "earlier baseline"
        st.warning(
            f"⚠️ **ATTENTION (Rule 38)**: The newest cycle ({format_ts(latest_cycle.get('finished_at'))}) "
            f"failed verification with status `{latest_status.upper()}`. All candidate listings and skill gaps "
            f"displayed below are pinned to the last verified passing cycle ({format_ts(v_ts)})."
        )

    st.markdown("---")

    # =========================================================================
    # SECTION 2: AGENT ACTIVITY LOG (Main Panel, Most Space)
    # =========================================================================
    st.subheader("📋 Agent Activity Log (Recent 30 Cycles)")
    st.caption("Complete chronological record of orchestrator cycles, decisions, delegations, retries, and verdicts.")

    if not cycles:
        st.info("No cycles logged yet.")
    else:
        table_rows = []
        for c in cycles:
            notes = c.get("notes_parsed", {})
            v = notes.get("verdict", {})
            durations = notes.get("durations", {})
            dur_str = ", ".join(f"{k}: {v}s" for k, v in durations.items()) if durations else f"{c.get('records_touched', 0)} recs"
            ran = ", ".join(notes.get("ran", [])) or "none"
            skipped = ", ".join(f"{k} ({reason})" for k, reason in notes.get("skipped", {}).items()) or "none"

            status = c.get("status", "unknown").upper()
            v_status = v.get("status", "pass").upper() if v else ("PASS" if status in ("COMPLETE", "NOTHING_TO_DO") else "FAIL")
            
            failed_checks = v.get("failed_checks", []) if v else []
            if failed_checks:
                f_details = "; ".join(f"{fc.get('name')}: {fc.get('message')}" for fc in failed_checks)
            else:
                f_details = "None (Passed)"

            retries = v.get("retry_count", 0) if v else 0

            badge_class = "badge-complete" if status == "COMPLETE" else (
                "badge-nothing" if status == "NOTHING_TO_DO" else (
                    "badge-partial" if status == "PARTIAL" else "badge-degraded"
                )
            )

            table_rows.append({
                "Finished At": format_ts(c.get("finished_at")),
                "Outcome": f'<span class="{badge_class}">{status}</span>',
                "Agents Ran": ran,
                "Skipped (Reason)": skipped,
                "Verdict": f"<b>{v_status}</b>",
                "Failed Checks & Observed": f_details,
                "Retries": retries,
                "Durations": dur_str,
                "raw_status": status,
            })

        html = '<table style="width:100%; border-collapse: collapse; font-size: 13px;">'
        html += '<tr style="border-bottom: 2px solid #374151; text-align: left; padding: 8px;">'
        headers = ["Finished At", "Outcome", "Agents Ran", "Skipped (Reason)", "Verdict", "Failed Checks & Observed", "Retries", "Duration"]
        for h in headers:
            html += f'<th style="padding: 8px 10px;">{h}</th>'
        html += '</tr>'

        for r in table_rows:
            row_class = "row-degraded" if r["raw_status"] in ("DEGRADED", "FAILED") else (
                "row-partial" if r["raw_status"] == "PARTIAL" else (
                    "row-nothing" if r["raw_status"] == "NOTHING_TO_DO" else "row-complete"
                )
            )
            html += f'<tr class="{row_class}" style="border-bottom: 1px solid #2d3748;">'
            html += f'<td style="padding: 8px 10px; white-space: nowrap;">{r["Finished At"]}</td>'
            html += f'<td style="padding: 8px 10px;">{r["Outcome"]}</td>'
            html += f'<td style="padding: 8px 10px;">{r["Agents Ran"]}</td>'
            html += f'<td style="padding: 8px 10px; max-width: 250px; overflow: hidden; text-overflow: ellipsis;">{r["Skipped (Reason)"]}</td>'
            html += f'<td style="padding: 8px 10px;">{r["Verdict"]}</td>'
            fail_color = "#ef5350" if "failed" in r["Failed Checks & Observed"].lower() else "#9e9e9e"
            html += f'<td style="padding: 8px 10px; color: {fail_color};">{r["Failed Checks & Observed"]}</td>'
            html += f'<td style="padding: 8px 10px; text-align: center;">{r["Retries"]}</td>'
            html += f'<td style="padding: 8px 10px; white-space: nowrap;">{r["Durations"]}</td>'
            html += '</tr>'
        html += '</table>'
        st.markdown(html, unsafe_allow_html=True)

    st.markdown("---")

    # =========================================================================
    # SECTION 3: TWO COMPACT PANELS (Top 10 Listings & Top 10 Skill Gaps)
    # =========================================================================
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("🎯 Top 10 Scored Listings (Verified)")
        if not top_listings:
            st.info("No scored listings available.")
        else:
            for item in top_listings:
                score = item.get("fit_score", 0)
                title = item.get("title", "Untitled")
                company = item.get("company", "Unknown")
                url = item.get("url")
                reason = item.get("fit_reason", "No reason recorded")

                # Ensure URL is valid, actionable, and never dead example.com
                if not url or "example.com" in url:
                    search_query = f"{company} {title} jobs"
                    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(search_query)}"

                link_html = f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="color: #60a5fa; text-decoration: underline; font-weight: 600;">{title} ↗</a>'
                badge_color = "#16a34a" if score >= 80 else ("#2563eb" if score >= 60 else "#eab308")

                st.markdown(
                    f'<div style="margin-bottom: 12px; padding: 10px 12px; background: rgba(30, 41, 59, 0.4); border-radius: 6px; border: 1px solid #334155;">'
                    f'<span style="background-color: {badge_color}; color: white; padding: 2px 7px; border-radius: 4px; font-weight: 700; font-size: 11px; margin-right: 8px;">{score:02d}/100</span>'
                    f'{link_html} — <span style="color: #cbd5e1; font-style: italic;">{company}</span>'
                    f'<div style="color: #94a3b8; font-size: 12px; margin-top: 5px; line-height: 1.4;">{reason}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    with col_right:
        st.subheader("📊 Top 10 Market Skill Gaps (Verified)")
        if not top_gaps:
            st.info("No skill gaps snapshot available.")
        else:
            gap_data = []
            for g in top_gaps:
                gap_data.append({
                    "Skill": g.get("skill", "").upper(),
                    "Opportunity Cost": f"{g.get('opportunity_cost', 0.0):.2f}",
                    "Listings Blocked": g.get("listings_blocked", 0),
                    "Mean Score": f"{g.get('mean_score', 0.0):.1f}",
                    "Confidence": "⚠️ Low (<3)" if g.get("low_confidence") else "High",
                })
            st.dataframe(gap_data, use_container_width=True, hide_index=True)

    st.markdown("---")

    # =========================================================================
    # SECTION 4: ASK YOUR DATA (Rules 40-45 & Abuse Guards)
    # =========================================================================
    st.subheader("💬 Ask Your Data")
    st.caption("Ask questions in plain English. Queries are routed to verified parameterised tools — no raw SQL, no hallucinations.")

    from edgedash.query.guards import check_daily_cap
    is_cap_exceeded, current_count, cap = check_daily_cap(config)

    if is_cap_exceeded:
        st.warning(
            f"🔒 **Daily Question Cap Reached ({current_count}/{cap})**: "
            "To safeguard API quotas on this public deployment, the natural language ask box is temporarily disabled. "
            "It will reopen automatically at midnight UTC. All verified data panels and tables above remain fully operational."
        )
    else:
        import uuid
        session_id = st.session_state.setdefault("session_id", uuid.uuid4().hex)

        # 3 Example Buttons (Point 6: first thing a visitor does works)
        ex_cols = st.columns(3)
        clicked_query = None
        with ex_cols[0]:
            if st.button("🏢 Which companies are hiring?", use_container_width=True):
                clicked_query = "Which companies are hiring in the last 14 days?"
        with ex_cols[1]:
            if st.button("🎯 What are my top job matches?", use_container_width=True):
                clicked_query = "What are my top 5 job matches?"
        with ex_cols[2]:
            if st.button("📉 What are my top skill gaps?", use_container_width=True):
                clicked_query = "What are my top 5 skill gaps by opportunity cost?"

        if "current_question" not in st.session_state:
            st.session_state["current_question"] = ""

        if clicked_query:
            st.session_state["current_question"] = clicked_query

        user_query = st.text_input(
            "Ask a question about jobs, skills, or hiring trends:",
            value=st.session_state["current_question"],
            placeholder="e.g. Which companies are hiring recently? or What are my top skill gaps?",
            max_chars=300,
        )

        run_submitted = st.button("Ask EdgeDash", type="primary")

        if run_submitted or clicked_query:
            active_q = clicked_query or user_query
            if active_q.strip():
                with st.spinner("Analyzing verified career data..."):
                    from edgedash.query.ask import ask
                    ans = ask(active_q.strip(), session_id=session_id, config=config)

                st.markdown("#### 💡 Answer")
                st.info(ans.text)

                # Rule 44: Every answer displays the underlying rows alongside it
                if ans.rows:
                    st.markdown("#### 📋 Underlying Data Records (Rule 44)")
                    st.dataframe(ans.rows, use_container_width=True, hide_index=True)
                elif ans.tool_used is not None:
                    st.caption("No matching records returned by this query tool.")


if __name__ == "__main__":
    main()

