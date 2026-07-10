import json
import os
import re
import uuid

import requests
import streamlit as st
from databricks.sdk import WorkspaceClient

from services.lakebase_memory import LakebaseMemoryClient
from services.store_ops import LocalDataStore, OpsTaskClient, StoreOpsEngine

MAS_ENDPOINT_NAME = os.environ.get("MAS_ENDPOINT_NAME", "").strip()

st.set_page_config(
    page_title="Bobabricks powered by Databricks and Lakebase",
    page_icon="🧋",
    layout="centered",
)

st.markdown(
    """
    <style>
    @keyframes blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.25; }
    }
    .block-container { max-width: 880px; padding-top: 2rem; }
    div[data-testid="stSidebar"] { background: #faf7f2; border-right: 1px solid #eadfd3; }
    .bb-intro { color: #59463a; font-size: 1.02rem; line-height: 1.55; margin-bottom: 1.2rem; }
    .lakebase-panel {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2d3a4a;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 12px;
        color: #e2e8f0;
        font-size: 13px;
    }
    .lakebase-panel .label { color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
    .lakebase-panel .value { color: #f1f5f9; font-weight: 500; font-family: monospace; font-size: 12px; overflow-wrap: anywhere; }
    .db-dot {
        animation: blink 1s ease-in-out infinite;
        background-color: #22c55e;
        border-radius: 50%;
        display: inline-block;
        height: 10px;
        margin-right: 6px;
        vertical-align: middle;
        width: 10px;
    }
    .db-dot-off { animation: none; background-color: #9ca3af; }
    .tool-pill { border: 1px solid #d8c8b8; border-radius: 999px; display: inline-block; font-size: 0.82rem; margin: 0.15rem 0.15rem 0.15rem 0; padding: 0.22rem 0.55rem; }
    .tool-pill-ok { background: #f0fbf4; border-color: #b7dfc5; color: #067647; }
    .tool-pill-warn { background: #fff7f5; border-color: #f1c7c1; color: #b42318; }
    </style>
    """,
    unsafe_allow_html=True,
)


def response_for_prompt(prompt: str, selected_region: str, engine: StoreOpsEngine, ops_tasks: OpsTaskClient, status_rows: list[dict]) -> str:
    lowered = prompt.lower()
    st.session_state["tool_status"] = None
    st.session_state["pending_drafts"] = []
    st.session_state["existing_tasks"] = None
    st.session_state["created_tasks"] = []

    if "tool" in lowered and "weekly" not in lowered:
        st.session_state["tool_status"] = status_rows
        tools = "\n".join(f"- {row['tool']} ({row['status']}): {row['purpose']}" for row in status_rows)
        return (
            "I have these Bobabricks demo tools attached:\n\n"
            f"{tools}\n\n"
            "Genie handles store operations analytics, StoreTime supplies schedule and training evidence, "
            "OpsTask is approval-gated for follow-up creation, Confluence supplies the operating standards, "
            "and Lakebase stores demo preferences."
        )

    if "training" in lowered and any(term in lowered for term in ("average", "actual", "hours", "behind")):
        return render_training_hours_markdown(selected_region, engine)

    if "weekly" in lowered and "briefing" in lowered:
        existing_tasks = ops_tasks.list_tasks()
        issues = engine.build_weekly_briefing(selected_region)
        drafts = engine.draft_high_severity_tasks(issues, existing_tasks)
        st.session_state["pending_drafts"] = drafts
        st.session_state["existing_tasks"] = existing_tasks
        return engine.render_briefing_markdown(selected_region, issues, drafts)

    if "104" in lowered and "training" in lowered:
        return (
            "Store 104 is behind because scheduled training time was converted to rush-window service coverage. "
            "That is a completion/utilization issue, not a scheduling issue.\n\n"
            "StoreTime evidence should show converted training hours and a rush-window coverage reason. "
            "The right follow-up is to protect non-rush training blocks and only create an OpsTask after approval."
        )

    if "fy26" in lowered or "goal" in lowered or "standard" in lowered:
        return (
            "For the FY26 operating standards demo, I would ground the answer in the Bobabricks Confluence page, "
            "then compare each store against the Genie training and execution signals.\n\n"
            "For Store 104, the key gap is training completion. It is not enough to schedule training hours; the "
            "store needs protected completion time and manager follow-through."
        )

    if "create tasks" in lowered or "now create" in lowered:
        drafts = st.session_state.get("pending_drafts", [])
        if not drafts:
            issues = engine.build_weekly_briefing(selected_region)
            drafts = engine.draft_high_severity_tasks(issues, ops_tasks.list_tasks())
        st.session_state["pending_drafts"] = drafts
        return "I found high-severity follow-ups ready for approval. Use the approval button below to create OpsTask tickets."

    if "propose" in lowered or "do not create" in lowered:
        issues = engine.build_weekly_briefing(selected_region)
        drafts = engine.draft_high_severity_tasks(issues, ops_tasks.list_tasks())
        return (
            "Proposed actions only:\n\n"
            + "\n".join(f"- {draft.store_id}: {draft.title}" for draft in drafts)
            + "\n\nNo OpsTask tickets have been created."
        )

    return (
        "Ask for available tools, a weekly regional risk briefing, Store 104 training diagnostics, "
        "FY26 operating standards, or approval-gated OpsTask creation."
    )


@st.cache_resource
def get_workspace_client():
    return WorkspaceClient()


def clean_agent_response(full_text: str) -> str:
    text = re.sub(
        r"<name>([^<]+)</name>",
        lambda match: f"*Calling tool... {match.group(1).replace('_', ' ').replace('-', ' ')}*",
        full_text,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or "No response from the agent."


def render_training_hours_markdown(region: str, engine: StoreOpsEngine) -> str:
    metrics = engine.data_store.store_metrics(region)
    schedules = engine.data_store.schedules()
    targets = engine.data_store.playbooks()["FY26 Store Operations Goals"]
    target_training = float(targets["training_completion_target_pct"])

    rows = []
    total_scheduled = 0.0
    total_completed = 0.0
    for metric in metrics:
        schedule = schedules.get(metric["store_id"], {})
        scheduled = float(schedule.get("scheduled_training_hours") or 0)
        completed = float(schedule.get("completed_training_hours") or 0)
        converted = float(schedule.get("converted_training_hours") or 0)
        completion = float(metric["training_completion_pct"])
        total_scheduled += scheduled
        total_completed += completed
        rows.append(
            {
                "store_id": metric["store_id"],
                "store_name": metric["store_name"],
                "scheduled": scheduled,
                "completed": completed,
                "converted": converted,
                "completion": completion,
                "reason": schedule.get("conversion_reason") or "none",
                "behind": completion < target_training,
            }
        )

    avg_scheduled = total_scheduled / len(rows) if rows else 0
    avg_completed = total_completed / len(rows) if rows else 0
    avg_actual_pct = (total_completed / total_scheduled * 100) if total_scheduled else 0

    lines = [
        f"### {region} training hours",
        "",
        "**Evidence used**",
        "- **Confluence:** FY26 training completion target.",
        "- **Genie Agent:** store-level training completion metrics.",
        "- **StoreTime:** scheduled, completed, and converted training hours.",
        "",
        (
            f"Across {len(rows)} {region} stores, average scheduled training is "
            f"{avg_scheduled:.1f} hours and average actual completed training is {avg_completed:.1f} hours "
            f"({avg_actual_pct:.0f}% of scheduled hours). The FY26 completion target is {target_training:.0f}%."
        ),
        "",
        "| Store | Scheduled | Actual completed | Completion | Converted | Behind? | Evidence |",
        "|---|---:|---:|---:|---:|---|---|",
    ]

    for row in rows:
        behind = "Yes" if row["behind"] else "No"
        evidence = (
            f"{row['converted']:.0f} hours converted for {row['reason']}"
            if row["converted"]
            else "no converted training hours"
        )
        lines.append(
            f"| {row['store_id']} - {row['store_name']} | {row['scheduled']:.0f} | "
            f"{row['completed']:.0f} | {row['completion']:.0f}% | {row['converted']:.0f} | "
            f"{behind} | {evidence} |"
        )

    behind_rows = [row for row in rows if row["behind"]]
    if behind_rows:
        stores = ", ".join(f"Store {row['store_id']}" for row in behind_rows)
        lines.extend(
            [
                "",
                f"**Flagged stores:** {stores}.",
                "Store 104 is the clearest issue: 25 of 42 scheduled hours were completed, and "
                "14 training hours were converted to rush-window service coverage.",
            ]
        )
    else:
        lines.extend(["", "**Flagged stores:** none."])

    return "\n".join(lines)


def stream_mas(messages: list[dict]):
    workspace = get_workspace_client()
    url = f"{workspace.config.host.rstrip('/')}/serving-endpoints/{MAS_ENDPOINT_NAME}/invocations"
    headers = workspace.config.authenticate()
    headers["Content-Type"] = "application/json"

    response = requests.post(
        url,
        headers=headers,
        json={"input": messages, "stream": True},
        stream=True,
        timeout=300,
    )
    response.raise_for_status()

    emitted_tools = set()
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")
        if event_type in ("response.output_item.added", "response.output_item.done"):
            item = event.get("item", {})
            tool_name = item.get("name") if item.get("type") == "function_call" else None
            for block in item.get("content", []):
                text = block.get("text", "").strip()
                match = re.match(r"^<name>([^<]+)</name>$", text)
                if match:
                    tool_name = match.group(1)
            if tool_name and tool_name not in emitted_tools:
                emitted_tools.add(tool_name)
                yield f"\n\n*Calling tool... {tool_name.replace('_', ' ').replace('-', ' ')}*\n\n"

        if event_type == "response.output_text.delta":
            yield event.get("delta", "")
        elif "delta" in event:
            delta = event["delta"]
            yield delta if isinstance(delta, str) else delta.get("content", "")


def query_mas(messages: list[dict]) -> str:
    workspace = get_workspace_client()
    url = f"{workspace.config.host.rstrip('/')}/serving-endpoints/{MAS_ENDPOINT_NAME}/invocations"
    headers = workspace.config.authenticate()
    headers["Content-Type"] = "application/json"

    response = requests.post(url, headers=headers, json={"input": messages}, timeout=300)
    response.raise_for_status()
    data = response.json()

    parts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    parts.append(block["text"])
    return clean_agent_response("\n\n".join(parts))


def build_agent_messages(prompt: str, prior_messages: list[dict], selected_region: str, status_rows: list[dict]) -> list[dict]:
    tool_context = "\n".join(
        f"- {row['tool']} ({row['status']}): {row['purpose']}" for row in status_rows
    )
    system_context = (
        "You are the Bobabricks store operations demo assistant. "
        f"The selected region is {selected_region}. "
        "Use the attached Databricks resources and MCP tools when answering: Genie for metrics, "
        "StoreTime for scheduling/training evidence, OpsTask for follow-up tasks, Confluence for FY26 standards, "
        "Inventory MCP for stockout risk, and Lakebase for memory. "
        "When you use a tool, briefly name what evidence came from it. "
        "Do not invent task creation; ask for approval before creating OpsTask tickets.\n\n"
        f"Available tools:\n{tool_context}"
    )
    conversation = [{"role": "system", "content": system_context}]
    conversation.extend(prior_messages[-8:])
    conversation.append({"role": "user", "content": prompt})
    return conversation


def tool_call_order(prompt: str) -> list[tuple[str, str]]:
    lowered = prompt.lower()
    calls = [
        ("Lakebase memory", "load selected region and demo context"),
    ]

    if "tool" in lowered and "weekly" not in lowered:
        calls.append(("MCP registry", "list available tools, status, and purpose"))
        return calls

    if any(term in lowered for term in ("fy26", "goal", "standard", "weekly", "briefing", "training")):
        calls.append(("Confluence", "retrieve FY26 goals and operating standards"))

    if any(term in lowered for term in ("average", "actual", "training", "weekly", "briefing", "store", "risk")):
        calls.append(("Genie Agent", "query governed store metrics and training performance"))

    if any(term in lowered for term in ("training", "schedule", "scheduling", "104", "storetime", "completion")):
        calls.append(("StoreTime", "inspect training blocks, converted hours, and coverage reasons"))

    if any(term in lowered for term in ("weekly", "briefing", "inventory", "stockout", "risk")):
        calls.append(("Inventory MCP", "check ingredient availability and stockout risk"))

    if any(term in lowered for term in ("weekly", "briefing", "task", "tasks", "propose", "create")):
        calls.append(("OpsTask", "list existing follow-ups and draft approval-gated tasks"))

    return calls


def render_tool_call_order(prompt: str) -> str:
    lines = ["**Tool call order**"]
    for index, (tool, action) in enumerate(tool_call_order(prompt), start=1):
        lines.append(f"{index}. **{tool}** - {action}")
    return "\n".join(lines)


def local_tool_response(
    prompt: str,
    selected_region: str,
    engine: StoreOpsEngine,
    ops_tasks: OpsTaskClient,
    status_rows: list[dict],
) -> str:
    return f"{render_tool_call_order(prompt)}\n\n{response_for_prompt(prompt, selected_region, engine, ops_tasks, status_rows)}"


data_store = LocalDataStore()
engine = StoreOpsEngine(data_store)
ops_tasks = OpsTaskClient(data_store)
memory = LakebaseMemoryClient()

regions = data_store.regions()
if "selected_region" not in st.session_state:
    st.session_state.selected_region = "Pacific" if "Pacific" in regions else regions[0]
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())

selected_region = st.session_state.selected_region
status_rows = engine.tool_status()
enabled_count = sum(row["status"] in {"configured", "enabled", "approval-gated"} for row in status_rows)
high_count = sum(issue.severity == "high" for issue in engine.build_weekly_briefing(selected_region))
memory_status = memory.status()
memory.remember_preference("demo_user", "selected_region", selected_region)

st.title("🧋 Bobabricks")
st.caption("powered by Databricks and Lakebase")
st.markdown(
    """
    <div class="bb-intro">
    Bobabricks is a premium boba tea company running a store operations demo on Databricks.
    This assistant helps regional leaders inspect FY26 training goals, store execution risk,
    scheduling evidence, and approval-gated follow-up tasks across Genie, StoreTime, OpsTask,
    Confluence, and Lakebase.
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    dot_class = "db-dot" if memory_status.enabled else "db-dot db-dot-off"
    status_text = "Connected" if memory_status.enabled else "Disconnected"
    st.markdown(
        f"""
        <div class="lakebase-panel">
            <div style="display: flex; align-items: center; margin-bottom: 10px;">
                <span class="{dot_class}"></span>
                <strong style="font-size: 14px;">LAKEBASE</strong>
                <span style="margin-left: auto; font-size: 11px; color: #22c55e;">{status_text}</span>
            </div>
            <div class="label">Instance</div>
            <div class="value">{memory.instance_name}</div>
            <div class="label" style="margin-top: 8px;">Database</div>
            <div class="value">{memory.database}</div>
            <div class="label" style="margin-top: 8px;">Schema</div>
            <div class="value">{memory.schema}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(memory_status.message)

    st.divider()
    st.markdown("**Region**")
    selected_region = st.selectbox(
        "Region",
        regions,
        index=regions.index(st.session_state.selected_region),
        label_visibility="collapsed",
    )
    st.session_state.selected_region = selected_region
    st.caption("Region preference is written to Lakebase when available.")

    st.divider()
    st.markdown("**Runtime**")
    st.metric("Active tools", f"{enabled_count}/{len(status_rows)}")
    st.metric("Open high risks", high_count)
    st.metric("Approval policy", "Required")

    st.divider()
    st.markdown("**Connected tools**")
    for row in status_rows:
        status_class = "tool-pill-warn" if row["status"] in {"disabled", "fallback to Genie"} else "tool-pill-ok"
        st.markdown(
            f'<span class="tool-pill {status_class}">{row["tool"]}: {row["status"]}</span>',
            unsafe_allow_html=True,
        )
        st.caption(row["purpose"])

    st.divider()
    if st.button("New Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conversation_id = str(uuid.uuid4())
        st.session_state["pending_drafts"] = []
        st.session_state["created_tasks"] = []
        st.rerun()

examples = [
    "What tools do you have?",
    f"Show average versus actual training hours for my {selected_region} stores and flag any stores falling behind.",
    "Why is Store 104 behind on training? Is it a scheduling problem or a completion problem?",
    "What are our FY26 training goals, and how does Store 104 stack up?",
    f"Generate my weekly {selected_region} regional risk briefing and create follow-up tasks for high-severity items.",
    "Propose actions only; do not create tasks yet.",
    "Now create tasks for high-severity items.",
]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

last_role = st.session_state.messages[-1]["role"] if st.session_state.messages else None
if last_role in (None, "assistant"):
    st.markdown("**Try asking:**")
    for example in examples:
        if st.button(f'"{example}"', key=f"example_{example}", use_container_width=True):
            st.session_state.example_prompt = example
            st.rerun()

prompt = st.session_state.pop("example_prompt", None)
typed_prompt = st.chat_input("Ask about training, store risk, standards, or follow-up tasks...")
if typed_prompt:
    prompt = typed_prompt

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    agent_messages = build_agent_messages(prompt, st.session_state.messages[:-1], selected_region, status_rows)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        raw_response = f"*Calling agent... Bobabricks Store Operations*\n\n{render_tool_call_order(prompt)}\n\n"
        placeholder.markdown(raw_response)
        if MAS_ENDPOINT_NAME:
            try:
                for chunk in stream_mas(agent_messages):
                    raw_response += chunk
                    placeholder.markdown(clean_agent_response(raw_response))
                response = clean_agent_response(raw_response)
            except Exception:
                response = local_tool_response(prompt, selected_region, engine, ops_tasks, status_rows)
        else:
            response = local_tool_response(prompt, selected_region, engine, ops_tasks, status_rows)
        placeholder.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})

if st.session_state.get("tool_status"):
    with st.expander("Available tool details", expanded=True):
        st.dataframe(st.session_state["tool_status"], hide_index=True, use_container_width=True)

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

    if st.button("Approve and Create OpsTask Tickets", type="primary"):
        created_tasks = ops_tasks.create_tasks(pending_drafts)
        st.session_state["created_tasks"] = created_tasks
        st.session_state["pending_drafts"] = []
        summary = "\n".join(f"- {task['task_id']}: {task['title']}" for task in created_tasks)
        st.session_state.messages.append(
            {"role": "assistant", "content": f"Created OpsTask tickets:\n\n{summary}"}
        )
        st.rerun()

if st.session_state.get("created_tasks"):
    with st.expander("Created OpsTask tickets", expanded=True):
        st.dataframe(st.session_state["created_tasks"], hide_index=True, use_container_width=True)

if st.session_state.get("existing_tasks"):
    with st.expander("Existing OpsTask context"):
        st.dataframe(st.session_state["existing_tasks"], hide_index=True, use_container_width=True)
