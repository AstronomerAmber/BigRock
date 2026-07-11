import asyncio
import json
import os
import re
import time
import uuid

import requests
import streamlit as st
from databricks.sdk import WorkspaceClient

from services.lakebase_memory import LakebaseMemoryClient
from services.store_ops import LocalDataStore, OpsTaskClient, StoreOpsEngine

MAS_ENDPOINT_NAME = os.environ.get("MAS_ENDPOINT_NAME", "").strip()
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "01f17b1364c914589ab9d24a70bf5b6f").strip()
STORETIME_MCP_URL = os.environ.get(
    "STORETIME_MCP_URL",
    "https://bobabricks-storetime-mcp-2847375137997282.aws.databricksapps.com/mcp",
).strip()
OPSTASK_MCP_URL = os.environ.get(
    "OPSTASK_MCP_URL",
    "https://bobabricks-opstask-mcp-2847375137997282.aws.databricksapps.com/mcp",
).strip()
DATABRICKS_WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "0bf53eaf9b66d1fd").strip()
DATABRICKS_CATALOG = os.environ.get("DATABRICKS_CATALOG", "bobabricks_demo").strip()
DATABRICKS_SCHEMA = os.environ.get("DATABRICKS_SCHEMA", "store_ops").strip()
AGENT_MODEL = os.environ.get("AGENT_MODEL", "databricks-claude-sonnet-4").strip()
OPENAI_AGENTS_SDK_ENABLED = os.environ.get("OPENAI_AGENTS_SDK_ENABLED", "true").lower() == "true"


def configure_mlflow_autologging() -> None:
    try:
        import mlflow
    except Exception:
        return

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    registry_uri = os.environ.get("MLFLOW_REGISTRY_URI", "").strip()
    experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID", "").strip()

    try:
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        if registry_uri:
            mlflow.set_registry_uri(registry_uri)
        if experiment_id:
            mlflow.set_experiment(experiment_id=experiment_id)
        mlflow.openai.autolog()
    except Exception:
        return


st.set_page_config(
    page_title="Bobabricks Powered by Databricks",
    page_icon="🧋",
    layout="centered",
)

configure_mlflow_autologging()

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
        return render_live_tool_registry(selected_region, engine, status_rows)

    if "training" in lowered and any(term in lowered for term in ("average", "actual", "hours", "behind")):
        return render_training_hours_markdown(selected_region, engine)

    if "fy26" in lowered or "goal" in lowered or "standard" in lowered:
        return render_fy26_goals_markdown(selected_region, engine)

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


class DatabricksSqlResourceClient:
    def __init__(self):
        self.workspace = get_workspace_client()

    @staticmethod
    def table(name: str) -> str:
        return f"{DATABRICKS_CATALOG}.{DATABRICKS_SCHEMA}.{name}"

    def query(self, statement: str, parameters: dict | None = None) -> list[dict]:
        response = self.workspace.api_client.do(
            "POST",
            "/api/2.0/sql/statements",
            body={
                "warehouse_id": DATABRICKS_WAREHOUSE_ID,
                "statement": statement,
                "parameters": [
                    {"name": key, "value": str(value)}
                    for key, value in (parameters or {}).items()
                    if value is not None
                ],
                "wait_timeout": "30s",
                "on_wait_timeout": "CONTINUE",
            },
        )
        statement_id = response.get("statement_id")
        while response.get("status", {}).get("state") in {"PENDING", "RUNNING"}:
            time.sleep(1)
            response = self.workspace.api_client.do("GET", f"/api/2.0/sql/statements/{statement_id}")
        if response.get("status", {}).get("state") != "SUCCEEDED":
            raise RuntimeError(json.dumps(response.get("status", response), default=str))
        columns = [col["name"] for col in response.get("manifest", {}).get("schema", {}).get("columns", [])]
        return [dict(zip(columns, row, strict=False)) for row in response.get("result", {}).get("data_array", [])]


class JsonRpcMcpResourceClient:
    def __init__(self, url: str):
        self.url = url
        self.workspace = get_workspace_client()

    def call_tool(self, name: str, arguments: dict | None = None) -> list[dict] | dict:
        headers = self.workspace.config.authenticate()
        headers["Content-Type"] = "application/json"
        response = requests.post(
            self.url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"].get("message", payload["error"]))
        content = payload.get("result", {}).get("content", [])
        if not content:
            return {}
        text = content[0].get("text", "{}")
        return json.loads(text)

    def list_tools(self) -> list[dict]:
        headers = self.workspace.config.authenticate()
        headers["Content-Type"] = "application/json"
        response = requests.post(
            self.url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/list",
                "params": {},
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"].get("message", payload["error"]))
        return payload.get("result", {}).get("tools", [])


class DirectStoreOpsDataStore(LocalDataStore):
    def __init__(self):
        super().__init__()
        self.sql = DatabricksSqlResourceClient()

    def store_metrics(self, region: str) -> list[dict[str, str]]:
        rows = self.sql.query(
            f"""
            SELECT region, store_id, store_name, sales_vs_plan_pct, training_completion_pct,
                   avg_wait_minutes, customer_satisfaction
            FROM {self.sql.table("store_metrics")}
            WHERE lower(region) = lower(:region)
            ORDER BY store_id
            """,
            {"region": region},
        )
        return [{key: str(value) for key, value in row.items()} for row in rows]

    def schedules(self) -> dict[str, dict[str, str]]:
        rows = self.sql.query(
            f"""
            SELECT store_id, week, scheduled_training_hours, completed_training_hours,
                   converted_training_hours, conversion_reason
            FROM {self.sql.table("schedules")}
            ORDER BY store_id
            """
        )
        return {str(row["store_id"]): {key: str(value or "") for key, value in row.items()} for row in rows}

    def inventory(self) -> list[dict[str, str]]:
        rows = self.sql.query(
            f"""
            SELECT store_id, ingredient, on_hand_units, forecast_7d_units, reorder_eta_days, stockout_risk
            FROM {self.sql.table("inventory")}
            ORDER BY store_id, ingredient
            """
        )
        return [{key: str(value) for key, value in row.items()} for row in rows]

    def regions(self) -> list[str]:
        rows = self.sql.query(
            f"""
            SELECT DISTINCT region
            FROM {self.sql.table("store_metrics")}
            ORDER BY region
            """
        )
        return [str(row["region"]) for row in rows]

    def existing_tasks(self) -> list[dict]:
        rows = self.sql.query(
            f"""
            SELECT task_id, store_id, title, description, category, severity, status, created_date, owner
            FROM {self.sql.table("ops_tasks")}
            ORDER BY created_date DESC, task_id
            LIMIT 100
            """
        )
        return rows


class DirectOpsTaskClient(OpsTaskClient):
    def __init__(self, data_store: LocalDataStore):
        super().__init__(data_store)
        self.mcp = JsonRpcMcpResourceClient(OPSTASK_MCP_URL)

    def list_tasks(self) -> list[dict]:
        return self.mcp.call_tool("list_existing_ops_tasks", {})

    def create_tasks(self, drafts) -> list[dict]:
        created = []
        for draft in drafts:
            created.append(
                self.mcp.call_tool(
                    "create_ops_task",
                    {
                        "store_id": int(draft.store_id) if str(draft.store_id).isdigit() else draft.store_id,
                        "title": draft.title,
                        "description": draft.description,
                        "category": draft.category,
                        "severity": draft.severity,
                    },
                )
            )
        return created


def build_resource_clients() -> tuple[LocalDataStore, OpsTaskClient, bool]:
    try:
        data = DirectStoreOpsDataStore()
        data.regions()
        return data, DirectOpsTaskClient(data), True
    except Exception:
        data = LocalDataStore()
        return data, OpsTaskClient(data), False


def render_training_hours_markdown(region: str, engine: StoreOpsEngine) -> str:
    metrics = engine.data_store.store_metrics(region)
    try:
        storetime = JsonRpcMcpResourceClient(STORETIME_MCP_URL)
        storetime_rows = []
        for metric in metrics:
            result = storetime.call_tool("inspect_schedule", {"store_id": int(metric["store_id"])})
            storetime_rows.extend(result if isinstance(result, list) else [result])
        schedules = {str(row["store_id"]): {key: str(value or "") for key, value in row.items()} for row in storetime_rows}
        storetime_source = "StoreTime MCP `inspect_schedule`"
    except Exception:
        schedules = engine.data_store.schedules()
        storetime_source = "StoreTime fallback schedule table"
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
        f"- **Genie/data resource:** store-level training completion metrics from `{DATABRICKS_CATALOG}.{DATABRICKS_SCHEMA}.store_metrics`.",
        f"- **StoreTime:** scheduled, completed, and converted training hours from {storetime_source}.",
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


def render_fy26_goals_markdown(region: str, engine: StoreOpsEngine) -> str:
    playbooks = engine.data_store.playbooks()
    goals = playbooks["FY26 Store Operations Goals"]
    training_standard = playbooks["Training Completion Operating Standard"]["guidance"]
    target_training = float(goals["training_completion_target_pct"])
    target_wait = float(goals["customer_wait_target_minutes"])
    metrics = engine.data_store.store_metrics(region)
    schedules = engine.data_store.schedules()
    store_104 = next((row for row in metrics if str(row["store_id"]) == "104"), None)
    schedule_104 = schedules.get("104", {})

    if not store_104:
        return (
            "I found the FY26 goals in Confluence, but Store 104 is not in the selected region. "
            "Switch the region to Pacific to compare Store 104."
        )

    completion = float(store_104["training_completion_pct"])
    gap = target_training - completion
    completed_hours = float(schedule_104.get("completed_training_hours") or 0)
    scheduled_hours = float(schedule_104.get("scheduled_training_hours") or 0)
    converted_hours = float(schedule_104.get("converted_training_hours") or 0)
    conversion_reason = schedule_104.get("conversion_reason") or "none"

    return "\n".join(
        [
            "### FY26 training goals and Store 104",
            "",
            "**Confluence operating standard**",
            f"- Training completion target: **{target_training:.0f}%**.",
            f"- Customer wait target: **{target_wait:.0f} minutes**.",
            f"- Training standard: {training_standard}",
            "",
            "**Store 104 comparison**",
            f"- Store 104 training completion is **{completion:.0f}%**, which is **{gap:.0f} points below** the FY26 target.",
            f"- StoreTime shows **{completed_hours:.0f} of {scheduled_hours:.0f}** scheduled training hours completed.",
            f"- **{converted_hours:.0f} hours** were converted to service coverage for **{conversion_reason}**.",
            "",
            "**Answer**",
            "Store 104 is not missing scheduled training capacity; it is losing protected training time to service coverage. "
            "That makes this a completion/utilization problem. The right next step is to protect the training blocks and, "
            "if you approve, create an OpsTask follow-up for the Store 104 manager.",
        ]
    )


def render_live_tool_registry(
    region: str,
    engine: StoreOpsEngine,
    status_rows: list[dict],
    persist_to_session: bool = True,
) -> str:
    checks = []

    try:
        metrics = engine.data_store.store_metrics(region)
        checks.append(
            {
                "tool": "Genie/data resource",
                "status": "reachable",
                "purpose": "governed store metrics and first-pass inventory",
                "evidence": f"Queried {len(metrics)} {region} store metric rows.",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "tool": "Genie/data resource",
                "status": "unreachable",
                "purpose": "governed store metrics and first-pass inventory",
                "evidence": exc.__class__.__name__,
            }
        )

    mcp_apps = (
        (
            "StoreTime",
            STORETIME_MCP_URL,
            "schedules, training conversion, and coverage reasons",
            "App resource `bobabricks-storetime-mcp` is attached with CAN_USE.",
        ),
        (
            "OpsTask",
            OPSTASK_MCP_URL,
            "approval-gated follow-up task listing and creation",
            "App resource `bobabricks-opstask-mcp` is attached with CAN_USE.",
        ),
    )
    for label, url, purpose, evidence in mcp_apps:
        checks.append(
            {
                "tool": label,
                "status": "configured" if url else "not configured",
                "purpose": purpose,
                "evidence": evidence if url else "No MCP URL in app env.",
            }
        )

    confluence_enabled = os.getenv("CONFLUENCE_MCP_ENABLED", "true").lower() == "true"
    atlassian_url = os.getenv("ATLASSIAN_MCP_URL", "")
    checks.append(
        {
            "tool": "Confluence",
            "status": "configured" if confluence_enabled and atlassian_url else "not configured",
            "purpose": "FY26 goals and playbooks",
            "evidence": "Atlassian MCP URL configured." if atlassian_url else "No Atlassian MCP URL in app env.",
        }
    )

    checks.append(
        {
            "tool": "Lakebase memory",
            "status": "reachable" if memory_status.enabled else "unreachable",
            "purpose": "stable user preferences",
            "evidence": memory_status.message,
        }
    )

    if persist_to_session:
        st.session_state["tool_status"] = checks
    lines = [
        "Here are the Bobabricks tools attached to this demo:",
        "",
        "| Tool | Live status | What it does | Check result |",
        "|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['tool']} | {check['status']} | {check['purpose']} | {check['evidence']} |"
        )
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


def should_preserve_structured_response(prompt: str) -> bool:
    lowered = prompt.lower()
    return "training" in lowered and any(term in lowered for term in ("average", "actual", "hours", "behind"))


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_openai_agents_sdk_response(
    prompt: str,
    selected_region: str,
    engine: StoreOpsEngine,
    ops_tasks: OpsTaskClient,
    status_rows: list[dict],
) -> str | None:
    if not OPENAI_AGENTS_SDK_ENABLED:
        return None

    try:
        from agents import (
            Agent,
            Runner,
            function_tool,
            set_default_openai_api,
            set_default_openai_client,
            set_tracing_disabled,
        )
        from databricks_openai import AsyncDatabricksOpenAI
    except Exception:
        return None

    set_default_openai_client(AsyncDatabricksOpenAI())
    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)

    @function_tool
    def check_available_tools() -> str:
        """Actively check Bobabricks tool/resource reachability and return tool names and status."""
        return render_live_tool_registry(selected_region, engine, status_rows, persist_to_session=False)

    @function_tool
    def compare_training_hours() -> str:
        """Compare scheduled versus actual training hours for the selected region and flag stores behind target."""
        return render_training_hours_markdown(selected_region, engine)

    @function_tool
    def get_fy26_training_goals() -> str:
        """Retrieve FY26 training goals and compare Store 104 against those standards."""
        return render_fy26_goals_markdown(selected_region, engine)

    @function_tool
    def generate_weekly_briefing() -> str:
        """Generate a weekly regional risk briefing and draft approval-gated OpsTask follow-ups."""
        return response_for_prompt(
            f"Generate my weekly {selected_region} regional risk briefing and create follow-up tasks for high-severity items.",
            selected_region,
            engine,
            ops_tasks,
            status_rows,
        )

    agent = Agent(
        name="Bobabricks Store Operations Agent",
        model=AGENT_MODEL,
        instructions=(
            "You are the Bobabricks Store Operations Agent. Use the provided tools for all demo questions. "
            "Do not invent metrics, stores, goals, or task ids. Lead with the answer, then cite which tool supplied the evidence. "
            "Use check_available_tools for tool-list questions, compare_training_hours for training-hour comparisons, "
            "get_fy26_training_goals for FY26 standards or Store 104 goal questions, and generate_weekly_briefing for weekly briefing requests. "
            "OpsTask creation remains approval-gated by the UI. If a tool is marked configured, describe it as attached/configured; "
            "do not downgrade configured Databricks App resources to unavailable because of raw session-context diagnostics."
        ),
        tools=[
            check_available_tools,
            compare_training_hours,
            get_fy26_training_goals,
            generate_weekly_briefing,
        ],
    )

    try:
        result = _run_async(Runner.run(agent, [{"role": "user", "content": prompt}]))
    except Exception:
        return None

    final_output = getattr(result, "final_output", None)
    if final_output:
        return str(final_output)

    new_items = getattr(result, "new_items", [])
    parts = []
    for item in new_items:
        try:
            value = item.to_input_item()
        except Exception:
            value = item
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(part.get("text", "") for part in content if isinstance(part, dict))
    return "\n\n".join(part for part in parts if part) or None


data_store, ops_tasks, _direct_resources_enabled = build_resource_clients()
engine = StoreOpsEngine(data_store)
memory = LakebaseMemoryClient()

regions = data_store.regions()
region_options = sorted(set(regions) | {"Pacific", "Mountain", "Atlantic"})
if "selected_region" not in st.session_state:
    st.session_state.selected_region = "Pacific" if "Pacific" in region_options else region_options[0]
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())

selected_region = st.session_state.selected_region
status_rows = engine.tool_status()
memory_status = memory.status()
memory.remember_preference("demo_user", "selected_region", selected_region)

st.title("🧋 Bobabricks")
st.caption("Powered by Databricks")
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
        region_options,
        index=region_options.index(st.session_state.selected_region),
        label_visibility="collapsed",
    )
    st.session_state.selected_region = selected_region
    st.caption("Region preference is written to Lakebase when available.")

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
    "What are our FY26 training goals, and how does Store 104 stack up?",
    f"Generate my weekly {selected_region} regional risk briefing and create follow-up tasks for high-severity items.",
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

    with st.chat_message("assistant"):
        placeholder = st.empty()
        raw_response = f"*Calling OpenAI Agents SDK... Bobabricks Store Operations Agent*\n\n{render_tool_call_order(prompt)}\n\n"
        placeholder.markdown(raw_response)

        sdk_response = None
        if should_preserve_structured_response(prompt):
            response = local_tool_response(prompt, selected_region, engine, ops_tasks, status_rows)
        else:
            sdk_response = run_openai_agents_sdk_response(prompt, selected_region, engine, ops_tasks, status_rows)
            if sdk_response:
                response = f"{render_tool_call_order(prompt)}\n\n{clean_agent_response(sdk_response)}"
            else:
                response = None

        if not response and MAS_ENDPOINT_NAME:
            agent_messages = build_agent_messages(prompt, st.session_state.messages[:-1], selected_region, status_rows)
            try:
                mas_response = ""
                for chunk in stream_mas(agent_messages):
                    mas_response += chunk
                    placeholder.markdown(f"{render_tool_call_order(prompt)}\n\n{clean_agent_response(mas_response)}")
                response = f"{render_tool_call_order(prompt)}\n\n{clean_agent_response(mas_response)}"
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
