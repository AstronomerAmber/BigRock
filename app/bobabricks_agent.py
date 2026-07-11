import asyncio
import os
from contextlib import AsyncExitStack

from databricks.sdk import WorkspaceClient


AGENT_MODEL = os.environ.get("AGENT_MODEL", "databricks-gpt-5").strip()
OPENAI_AGENTS_SDK_ENABLED = os.environ.get("OPENAI_AGENTS_SDK_ENABLED", "true").lower() == "true"
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "01f17b1364c914589ab9d24a70bf5b6f").strip()
STORETIME_MCP_URL = os.environ.get("STORETIME_MCP_URL", "").strip()
OPSTASK_MCP_URL = os.environ.get("OPSTASK_MCP_URL", "").strip()
ATLASSIAN_MCP_URL = os.environ.get("ATLASSIAN_MCP_URL", "").strip()


AGENT_INSTRUCTIONS = """\
You are the Bobabricks Store Operations Agent for regional store leaders.

Use the attached tools directly:
- Genie for governed Bobabricks store metrics, training completion, wait time, and regional performance.
- StoreTime for schedules, training blocks, converted hours, and coverage reasons.
- OpsTask for existing follow-ups and approval-gated task creation.
- Confluence/Atlassian for FY26 goals, operating standards, and playbooks.

Do not invent stores, metrics, targets, task ids, or policy. If a tool is unavailable
or does not return the needed evidence, say what is missing. Lead with the answer,
then cite the tool evidence compactly. Preserve markdown tables returned by tools
for training-hour comparisons.

OpsTask creation remains governed: describe the task you would create and wait for
explicit approval when the UI requires approval.
"""


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


def _workspace_host(workspace_client: WorkspaceClient) -> str:
    return workspace_client.config.host.rstrip("/")


def _genie_mcp_url(workspace_client: WorkspaceClient) -> str:
    return f"{_workspace_host(workspace_client)}/api/2.0/mcp/genie/{GENIE_SPACE_ID}"


def _tool_workspace_client() -> WorkspaceClient:
    # In Databricks Apps, this uses the app service principal. The app resources grant
    # access to Genie, StoreTime, OpsTask, and Lakebase.
    return WorkspaceClient()


def _build_mcp_servers(workspace_client: WorkspaceClient):
    from databricks_openai.agents import McpServer

    servers = [
        McpServer(
            url=_genie_mcp_url(workspace_client),
            name="bobabricks_genie",
            workspace_client=workspace_client,
        )
    ]
    if STORETIME_MCP_URL:
        servers.append(
            McpServer(
                url=STORETIME_MCP_URL,
                name="storetime",
                workspace_client=workspace_client,
            )
        )
    if OPSTASK_MCP_URL:
        servers.append(
            McpServer(
                url=OPSTASK_MCP_URL,
                name="opstask",
                workspace_client=workspace_client,
            )
        )
    if ATLASSIAN_MCP_URL:
        servers.append(
            McpServer(
                url=ATLASSIAN_MCP_URL,
                name="atlassian_confluence",
                workspace_client=workspace_client,
            )
        )
    return servers


async def _connect_available_mcp_servers(stack: AsyncExitStack, workspace_client: WorkspaceClient):
    available = []
    unavailable = []
    for server in _build_mcp_servers(workspace_client):
        name = getattr(server, "name", "tool")
        try:
            connected = await stack.enter_async_context(server)
            await connected.list_tools()
            available.append(connected)
        except Exception:
            unavailable.append(name)
    return available, unavailable


def _agent_instructions(unavailable_tools: list[str]) -> str:
    if not unavailable_tools:
        return AGENT_INSTRUCTIONS
    unavailable = ", ".join(sorted(set(unavailable_tools)))
    return (
        AGENT_INSTRUCTIONS
        + "\n\n# Tool availability\n"
        + f"These tool servers are currently unavailable: {unavailable}. "
        + "Use the remaining tools. If a question requires an unavailable tool, say so directly."
    )


def _extract_output(result) -> str | None:
    final_output = getattr(result, "final_output", None)
    if final_output:
        return str(final_output)

    parts = []
    for item in getattr(result, "new_items", []):
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


async def _run_bobabricks_agent_async(prompt: str, selected_region: str) -> str | None:
    from agents import Agent, Runner, set_default_openai_api, set_default_openai_client
    from agents.tracing import set_trace_processors
    from databricks_openai import AsyncDatabricksOpenAI

    set_default_openai_client(AsyncDatabricksOpenAI())
    set_default_openai_api("chat_completions")
    set_trace_processors([])

    workspace_client = _tool_workspace_client()
    async with AsyncExitStack() as stack:
        mcp_servers, unavailable_tools = await _connect_available_mcp_servers(stack, workspace_client)
        agent = Agent(
            name="Bobabricks Store Operations Agent",
            model=AGENT_MODEL,
            instructions=(
                _agent_instructions(unavailable_tools)
                + f"\n\nThe selected region is {selected_region}. Use it when the user says 'my region'."
            ),
            tools=[],
            mcp_servers=mcp_servers,
        )
        result = await Runner.run(agent, [{"role": "user", "content": prompt}])
    return _extract_output(result)


def run_bobabricks_agent(prompt: str, selected_region: str) -> str | None:
    if not OPENAI_AGENTS_SDK_ENABLED:
        return None
    try:
        return _run_async(_run_bobabricks_agent_async(prompt, selected_region))
    except Exception:
        return None
