import streamlit as st

from services.lakebase_memory import LakebaseMemoryClient
from services.store_ops import LocalDataStore, OpsTaskClient, StoreOpsEngine

st.set_page_config(page_title="Bobabricks Store Operations", page_icon="B", layout="wide")

st.markdown(
    """
    <style>
      :root {
        --bb-ink: #1f1a17;
        --bb-muted: #6f6259;
        --bb-line: #e7dfd8;
        --bb-cream: #fffaf3;
        --bb-mint: #d9f2e4;
        --bb-red: #b42318;
        --bb-green: #067647;
        --bb-coffee: #5f3b25;
      }
      .block-container {
        padding-top: 1.5rem;
        max-width: 1180px;
      }
      div[data-testid="stSidebar"] {
        background: #f8f2ea;
        border-right: 1px solid var(--bb-line);
      }
      .bb-header {
        border-bottom: 1px solid var(--bb-line);
        padding: 0.35rem 0 1rem;
        margin-bottom: 1rem;
      }
      .bb-kicker {
        color: var(--bb-coffee);
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0;
        text-transform: uppercase;
      }
      .bb-title {
        color: var(--bb-ink);
        font-size: 2.1rem;
        font-weight: 760;
        line-height: 1.1;
        margin: 0.15rem 0 0.35rem;
      }
      .bb-subtitle {
        color: var(--bb-muted);
        font-size: 1rem;
        max-width: 760px;
      }
      .bb-panel {
        border: 1px solid var(--bb-line);
        border-radius: 8px;
        padding: 1rem;
        background: #fffdf9;
      }
      .bb-status {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        border: 1px solid var(--bb-line);
        border-radius: 999px;
        padding: 0.22rem 0.55rem;
        margin: 0.1rem 0.2rem 0.1rem 0;
        color: var(--bb-ink);
        background: white;
        font-size: 0.82rem;
      }
      .bb-status.ok { border-color: #b7dfc5; background: #f2fbf5; color: var(--bb-green); }
      .bb-status.warn { border-color: #f1c7c1; background: #fff7f5; color: var(--bb-red); }
      .bb-divider { height: 1px; background: var(--bb-line); margin: 1rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="bb-header">
      <div class="bb-kicker">Bobabricks operations command center</div>
      <div class="bb-title">Store Operations Agent</div>
      <div class="bb-subtitle">
        Regional risk briefings across Genie, StoreTime, OpsTask, Confluence,
        and Lakebase memory with approval-gated follow-up creation.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

data_store = LocalDataStore()
engine = StoreOpsEngine(data_store)
ops_tasks = OpsTaskClient(data_store)
memory = LakebaseMemoryClient()

regions = data_store.regions()

with st.sidebar:
    st.subheader("Demo controls")
    selected_region = st.selectbox("Region", regions, index=regions.index("Pacific") if "Pacific" in regions else 0)
    st.caption("Region preference is written to Lakebase when available.")

    st.divider()
    st.subheader("Runtime")
    memory_status = memory.status()
    st.write("Lakebase memory")
    st.caption(memory_status.message)
    st.write("Genie space")
    st.caption("bobabricks_store_operations")
    st.write("MCP apps")
    st.caption("StoreTime and OpsTask are Databricks Apps resources.")

memory.remember_preference("demo_user", "selected_region", selected_region)

status_rows = engine.tool_status()
enabled_count = sum(row["status"] in {"configured", "enabled", "approval-gated"} for row in status_rows)
high_level_issues = engine.build_weekly_briefing(selected_region)
high_count = sum(issue.severity == "high" for issue in high_level_issues)

metric_cols = st.columns(4)
metric_cols[0].metric("Region", selected_region)
metric_cols[1].metric("Active tools", f"{enabled_count}/{len(status_rows)}")
metric_cols[2].metric("Open high risks", high_count)
metric_cols[3].metric("Approval policy", "Required")

st.markdown('<div class="bb-divider"></div>', unsafe_allow_html=True)

left, right = st.columns([0.66, 0.34], gap="large")

with right:
    st.subheader("Connected tools")
    for row in status_rows:
        status_class = "warn" if row["status"] in {"disabled", "fallback to Genie"} else "ok"
        st.markdown(
            f'<span class="bb-status {status_class}">{row["tool"]}: {row["status"]}</span>',
            unsafe_allow_html=True,
        )
    st.caption("Tool availability reflects configured app resources and environment flags.")

    st.subheader("Runbook shortcuts")
    if st.button("Generate Weekly Regional Briefing", type="primary", use_container_width=True):
        st.session_state["prompt"] = (
            f"Generate my weekly {selected_region} regional risk briefing and create follow-up tasks "
            "for high-severity items."
        )
    if st.button("Inspect Store 104 Training", use_container_width=True):
        st.session_state["prompt"] = "Why is Store 104 behind on training? Is it a scheduling problem or a completion problem?"
    if st.button("Show Available Tools", use_container_width=True):
        st.session_state["prompt"] = "What tools do you have?"

with left:
    prompt = st.text_area(
        "Ask the agent",
        value=st.session_state.get("prompt", "What tools do you have?"),
        height=132,
    )

    if st.button("Run Demo Query", type="primary"):
        lowered = prompt.lower()
        st.session_state["created_tasks"] = []

        if "tool" in lowered and "weekly" not in lowered:
            st.session_state["tool_status"] = status_rows
            st.session_state["briefing"] = None
        elif "weekly" in lowered and "briefing" in lowered:
            existing_tasks = ops_tasks.list_tasks()
            issues = engine.build_weekly_briefing(selected_region)
            drafts = engine.draft_high_severity_tasks(issues, existing_tasks)

            st.session_state["pending_drafts"] = drafts
            st.session_state["briefing"] = engine.render_briefing_markdown(selected_region, issues, drafts)
            st.session_state["existing_tasks"] = existing_tasks
            st.session_state["tool_status"] = None
        elif "104" in lowered and "training" in lowered:
            st.session_state["briefing"] = (
                "Store 104 is behind because scheduled training time was converted to rush-window service coverage. "
                "That is a completion/utilization issue, not a scheduling issue. StoreTime evidence should show "
                "converted training hours and a rush-window coverage reason."
            )
            st.session_state["tool_status"] = None
        else:
            st.session_state["briefing"] = (
                "Ask for a weekly regional risk briefing, Store 104 training diagnostics, or available tools. "
                "Write actions such as OpsTask creation require explicit approval."
            )
            st.session_state["tool_status"] = None

if st.session_state.get("tool_status"):
    st.subheader("Available Tools")
    st.dataframe(st.session_state["tool_status"], hide_index=True, use_container_width=True)

if st.session_state.get("briefing"):
    st.subheader("Agent Response")
    st.markdown(st.session_state["briefing"])

pending_drafts = st.session_state.get("pending_drafts", [])
if pending_drafts:
    st.subheader("Pending OpsTask Approval")
    st.dataframe(
        [
            {
                "store_id": draft.store_id,
                "title": draft.title,
                "category": draft.category,
                "severity": draft.severity,
            }
            for draft in pending_drafts
        ],
        hide_index=True,
        use_container_width=True,
    )

    if st.button("Approve and Create OpsTask Tickets"):
        st.session_state["created_tasks"] = ops_tasks.create_tasks(pending_drafts)
        st.session_state["pending_drafts"] = []
        st.rerun()

if st.session_state.get("created_tasks"):
    st.subheader("Created OpsTask Tickets")
    st.dataframe(st.session_state["created_tasks"], hide_index=True, use_container_width=True)

if st.session_state.get("existing_tasks"):
    with st.expander("Existing OpsTask Context"):
        st.dataframe(st.session_state["existing_tasks"], hide_index=True, use_container_width=True)
