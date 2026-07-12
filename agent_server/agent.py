import json
import logging
import os
import re
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any, AsyncGenerator

import httpx
import mlflow
from agents import Agent, FunctionTool, RunContextWrapper, Runner, function_tool, set_default_openai_api, set_default_openai_client
from agents.tracing import set_trace_processors
from databricks.sdk import WorkspaceClient
from databricks_openai import AsyncDatabricksOpenAI
from databricks_openai.agents import AsyncDatabricksSession, McpServer
from fastapi import HTTPException
from mlflow.genai.agent_server import get_request_headers, invoke, stream
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse, ResponsesAgentStreamEvent

from agent_server.utils import (
    deduplicate_input,
    get_databricks_host_from_env,
    get_session_id,
    lakebase_access_message,
    lakebase_config,
    process_agent_stream_events,
)

set_default_openai_client(AsyncDatabricksOpenAI())
set_default_openai_api("chat_completions")
set_trace_processors([])
mlflow.openai.autolog()
logging.getLogger("mlflow.utils.autologging_utils").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


def _enrich_agent_spans() -> None:
    try:
        from mlflow.openai import _agent_tracer as tracer

        orig_name = tracer._get_span_name
        orig_parse = tracer._parse_span_data

        def friendly_tool_name(value):
            if not value:
                return value
            text = str(value)
            if re.fullmatch(r"query_space_[0-9a-f]+", text):
                return "Genie Agent - query Bobabricks store metrics"
            if re.fullmatch(r"poll_response_[0-9a-f]+", text):
                return "Genie Agent - poll query result"
            return value

        def name(span_data):
            span_type = getattr(span_data, "type", "")
            if span_type == "turn":
                return f"Turn #{getattr(span_data, 'turn', '?')}"
            if span_type == "mcp_tools":
                return f"MCP: list tools ({getattr(span_data, 'server', '?')})"
            existing = getattr(span_data, "name", None)
            existing = friendly_tool_name(existing)
            return existing if existing else orig_name(span_data)

        def parse(span_data):
            inputs, outputs, attributes = orig_parse(span_data)
            attributes = dict(attributes or {})
            span_type = getattr(span_data, "type", "")
            if span_type == "mcp_tools":
                tools = [
                    friendly_tool_name(tool)
                    for tool in list(getattr(span_data, "result", None) or [])
                ]
                attributes["server"] = getattr(span_data, "server", None)
                attributes["tool_count"] = len(tools)
                outputs = {"tools": tools}
            elif span_type == "turn":
                attributes["turn"] = getattr(span_data, "turn", None)
                attributes["agent"] = getattr(span_data, "agent_name", None)
                if getattr(span_data, "usage", None):
                    attributes["usage"] = span_data.usage
            if attributes.get("name"):
                attributes["name"] = friendly_tool_name(attributes["name"])
            if isinstance(inputs, dict):
                inputs = {
                    key: friendly_tool_name(value) if key in {"name", "tool", "tool_name"} else value
                    for key, value in inputs.items()
                }
            return inputs, outputs, attributes

        tracer._get_span_name = name
        tracer._parse_span_data = parse
    except Exception:
        logger.debug("Could not enrich openai-agents spans.", exc_info=True)


_enrich_agent_spans()

MODEL = os.getenv("AGENT_MODEL", "databricks-gpt-5")
GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "01f17b1364c914589ab9d24a70bf5b6f")
STORETIME_MCP_URL = os.getenv("STORETIME_MCP_URL", "https://bobabricks-storetime-mcp-2847375137997282.aws.databricksapps.com/mcp")
OPSTASK_MCP_URL = os.getenv("OPSTASK_MCP_URL", "https://bobabricks-opstask-mcp-2847375137997282.aws.databricksapps.com/mcp")
ATLASSIAN_MCP_URL = os.getenv("ATLASSIAN_MCP_URL")
ATLASSIAN_OFF_SENTINELS = {"", "off", "none", "disabled", "false"}
ATLASSIAN_FRIENDLY_NAME = "Atlassian Confluence"
USE_SDK_MCP_SERVERS = os.getenv("USE_SDK_MCP_SERVERS", "false").strip().lower() in {"1", "true", "on", "yes"}

AGENT_INSTRUCTIONS = """\
You are the Bobabricks Store Operations Agent for regional store leaders.

Use the attached tools directly:
- Genie for governed Bobabricks store metrics, training completion, wait time, and regional performance.
- StoreTime for schedules, training blocks, converted hours, and coverage reasons.
- OpsTask for existing follow-ups and approval-gated task creation.
- Confluence/Atlassian for FY26 goals, operating standards, and playbooks when the Atlassian tools are connected.

Do not invent stores, metrics, targets, task ids, or policy. If a tool is unavailable
or does not return the needed evidence required by the user's question, say what is
missing. Lead with the answer, then cite the tool evidence compactly. Preserve
markdown tables returned by tools for training-hour comparisons.

When asked what tools you have, answer as a concise Bobabricks tool inventory.
Do not use "Available" and "Unavailable" headings. Only mention unavailable
capabilities when they are directly relevant to the user request.

For Bobabricks demo questions, prefer compact answer-first output. Do not print a
separate hardcoded "Tool call order" section; the trace is the source of truth for
tool order. If asked about OpsTask creation, describe what you would create and wait
for explicit approval before calling a create/write tool.
"""

CONTEXT_INSTRUCTIONS = """\

# Company policy & documentation
Use Confluence as the source of truth for FY26 training goals, operating standards,
thresholds, and required actions. Always ground store metrics in Genie or StoreTime.
"""


@function_tool
def get_current_time() -> str:
    """Get the current date and time in ISO 8601 format."""
    return datetime.now().isoformat()


def _genie_mcp_url() -> str:
    return f"{get_databricks_host_from_env()}/api/2.0/mcp/genie/{GENIE_SPACE_ID}"


def _atlassian_url() -> str:
    if ATLASSIAN_MCP_URL is None:
        return ""
    if ATLASSIAN_MCP_URL.strip().lower() in ATLASSIAN_OFF_SENTINELS:
        return ""
    return ATLASSIAN_MCP_URL


class DirectMcpClient:
    def __init__(self, url: str, token: str, timeout: float = 30.0) -> None:
        self.url = url
        self.token = token
        self.session_id: str | None = None
        self._next_id = 1
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "DirectMcpClient":
        await self.initialize()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": "2025-03-26",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _parse_body(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            for raw in response.text.splitlines():
                if raw.startswith("data:"):
                    payload = raw[len("data:"):].strip()
                    if payload:
                        return json.loads(payload)
            raise RuntimeError(f"MCP response did not include a JSON-RPC frame: {response.text[:300]!r}")
        return response.json()

    async def _send(self, method: str, params: dict[str, Any] | None = None, expect_response: bool = True):
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if expect_response:
            body["id"] = self._next_id
            self._next_id += 1
        if params is not None:
            body["params"] = params
        response = await self._client.post(self.url, headers=self._headers(), json=body)
        if method == "initialize":
            self.session_id = response.headers.get("Mcp-Session-Id")
        if response.status_code >= 400:
            raise RuntimeError(f"MCP {method} HTTP {response.status_code}: {response.text[:400]}")
        if not expect_response:
            return None
        return self._parse_body(response)

    async def initialize(self) -> None:
        await self._send(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "bobabricks-direct-client", "version": "0.1"},
            },
        )
        await self._send("notifications/initialized", expect_response=False)

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send("tools/list", {})
        if result is None or "error" in result:
            raise RuntimeError(f"MCP tools/list error: {result}")
        return result.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._send("tools/call", {"name": name, "arguments": arguments})
        if result is None:
            return json.dumps({"error": "empty response"})
        if "error" in result:
            return json.dumps({"error": result["error"]})
        inner = result.get("result", {})
        content = inner.get("content")
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(item.get("text", ""))
                else:
                    chunks.append(json.dumps(item) if isinstance(item, dict) else str(item))
            if chunks:
                return "\n".join(chunks)
        return json.dumps(inner)


def _sanitize_schema(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_schema(v) for k, v in obj.items() if k != "$schema"}
    if isinstance(obj, list):
        return [_sanitize_schema(item) for item in obj]
    return obj


def _make_function_tool(client: DirectMcpClient, meta: dict[str, Any]) -> FunctionTool:
    tool_name = meta["name"]
    schema = _sanitize_schema(meta.get("inputSchema") or {"type": "object", "properties": {}})

    async def _invoke(ctx: RunContextWrapper, args_json: str, _tool: str = tool_name) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except Exception:
            args = {}
        try:
            return await client.call_tool(_tool, args)
        except Exception as exc:
            return f"Tool error ({_tool}): {type(exc).__name__}: {exc}"

    return FunctionTool(
        name=tool_name,
        description=meta.get("description") or tool_name,
        params_json_schema=schema,
        on_invoke_tool=_invoke,
        strict_json_schema=False,
    )


def _atlassian_token() -> str:
    try:
        headers = get_request_headers() or {}
        token = headers.get("x-forwarded-access-token")
        if not token:
            authorization = headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization.split(" ", 1)[1]
        if token:
            return token
    except Exception:
        pass
    return os.getenv("ATLASSIAN_MCP_BEARER_TOKEN", "")


def _databricks_mcp_token() -> str:
    try:
        headers = get_request_headers() or {}
        token = headers.get("x-forwarded-access-token")
        if not token:
            authorization = headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization.split(" ", 1)[1]
        if token:
            return token
    except Exception:
        pass
    return os.getenv("DATABRICKS_TOKEN", "")


async def build_atlassian_tools(stack: AsyncExitStack) -> tuple[list[FunctionTool], list[str]]:
    url = _atlassian_url()
    if not url:
        return [], []
    token = _atlassian_token()
    if not token:
        return [], [ATLASSIAN_FRIENDLY_NAME]
    try:
        client = await stack.enter_async_context(DirectMcpClient(url, token))
        return [_make_function_tool(client, meta) for meta in await client.list_tools()], []
    except Exception as exc:
        logger.warning("Atlassian MCP unavailable; running without it. (%s)", exc)
        return [], [ATLASSIAN_FRIENDLY_NAME]


async def build_direct_databricks_mcp_tools(stack: AsyncExitStack) -> tuple[list[FunctionTool], list[str]]:
    if os.getenv("DISABLE_MCP_SERVERS", "false").strip().lower() in {"1", "true", "on", "yes"}:
        return [], list(MCP_FRIENDLY_NAMES.values())
    token = _databricks_mcp_token()
    if not token:
        return [], list(MCP_FRIENDLY_NAMES.values())

    tools: list[FunctionTool] = []
    unavailable: list[str] = []
    for name, url in [
        ("storetime", STORETIME_MCP_URL),
        ("opstask", OPSTASK_MCP_URL),
    ]:
        if not url:
            continue
        try:
            client = await stack.enter_async_context(DirectMcpClient(url, token))
            tools.extend(_make_function_tool(client, meta) for meta in await client.list_tools())
        except Exception as exc:
            logger.warning("MCP server %r unavailable over direct transport; running without it. (%s)", name, exc)
            unavailable.append(MCP_FRIENDLY_NAMES.get(name, name))
    return tools, unavailable


def build_mcp_servers(workspace_client: WorkspaceClient) -> list[McpServer]:
    servers = []
    if os.getenv("ENABLE_GENIE_MCP", "true").strip().lower() not in {"0", "false", "off", "no"}:
        servers.append(McpServer(url=_genie_mcp_url(), name="bobabricks_genie", workspace_client=workspace_client))
    if not USE_SDK_MCP_SERVERS:
        return servers
    if STORETIME_MCP_URL:
        servers.append(McpServer(url=STORETIME_MCP_URL, name="storetime", workspace_client=workspace_client))
    if OPSTASK_MCP_URL:
        servers.append(McpServer(url=OPSTASK_MCP_URL, name="opstask", workspace_client=workspace_client))
    return servers


MCP_FRIENDLY_NAMES = {
    "bobabricks_genie": "Genie Agent",
    "storetime": "StoreTime",
    "opstask": "OpsTask",
}


async def connect_available_mcp_servers(stack: AsyncExitStack, workspace_client: WorkspaceClient):
    available = []
    unavailable = []
    if os.getenv("DISABLE_MCP_SERVERS", "false").strip().lower() in {"1", "true", "on", "yes"}:
        return available, list(MCP_FRIENDLY_NAMES.values())
    for server in build_mcp_servers(workspace_client):
        name = getattr(server, "name", "tool")
        try:
            connected = await stack.enter_async_context(server)
            await connected.list_tools()
            available.append(connected)
        except Exception as exc:
            logger.warning("MCP server %r unavailable; running without it. (%s)", name, exc)
            unavailable.append(MCP_FRIENDLY_NAMES.get(name, name))
    return available, unavailable


async def close_tool_stack(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except BaseException as exc:
        logger.warning("MCP cleanup failed after response generation. (%s)", exc, exc_info=True)


def create_agent(mcp_servers=None, unavailable_tools=None, extra_tools=None, context_tools_enabled: bool = False) -> Agent:
    instructions = AGENT_INSTRUCTIONS
    if context_tools_enabled:
        instructions += CONTEXT_INSTRUCTIONS
    if unavailable_tools:
        names = ", ".join(sorted(set(unavailable_tools)))
        instructions += (
            "\n\n# Tool availability\n"
            f"Some capabilities may be unavailable this turn: {names}. Do not lead with this. "
            "Only mention unavailable capabilities when the user's request explicitly requires them."
        )
    return Agent(
        name="Bobabricks Store Operations Agent",
        instructions=instructions,
        model=MODEL,
        tools=[get_current_time, *(extra_tools or [])],
        mcp_servers=mcp_servers or [],
    )


def maybe_create_session(session_id: str) -> AsyncDatabricksSession | None:
    if os.getenv("BOBABRICKS_DISABLE_LAKEBASE") == "1":
        return None
    if not lakebase_config.is_configured:
        return None
    return AsyncDatabricksSession(
        session_id=session_id,
        instance_name=lakebase_config.instance_name,
        autoscaling_endpoint=lakebase_config.autoscaling_endpoint,
        project=lakebase_config.autoscaling_project,
        branch=lakebase_config.autoscaling_branch,
        schema=lakebase_config.memory_schema,
        create_tables=False,
    )


def _is_lakebase_error(exc: Exception) -> bool:
    return any(keyword in str(exc).lower() for keyword in ["lakebase", "pg_hba", "postgres", "database instance", "insufficient privilege"])


def _item_text(item: Any) -> str:
    value = item.model_dump() if hasattr(item, "model_dump") else item
    content = value.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _is_title_request(request: ResponsesAgentRequest) -> bool:
    for item in request.input:
        value = item.model_dump() if hasattr(item, "model_dump") else item
        if value.get("role") == "system" and "generate a short title" in _item_text(item).lower():
            return True
    return False


def _title_agent() -> Agent:
    return Agent(
        name="Conversation Titler",
        instructions="Generate a concise title. Output only the title text.",
        model=MODEL,
        tools=[],
    )


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    try:
        if _is_title_request(request):
            result = await Runner.run(_title_agent(), [item.model_dump() for item in request.input])
            return ResponsesAgentResponse(output=[item.to_input_item() for item in result.new_items])

        session_id = get_session_id(request)
        if session_id:
            mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})
        session = maybe_create_session(session_id)

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            mcp_servers, unavailable_tools = await connect_available_mcp_servers(stack, WorkspaceClient())
            direct_tools, direct_unavailable = await build_direct_databricks_mcp_tools(stack)
            atlassian_tools, atlassian_unavailable = await build_atlassian_tools(stack)
            agent = create_agent(
                mcp_servers=mcp_servers,
                unavailable_tools=unavailable_tools + direct_unavailable + atlassian_unavailable,
                extra_tools=direct_tools + atlassian_tools,
                context_tools_enabled=bool(atlassian_tools),
            )
            result = await Runner.run(agent, await deduplicate_input(request, session), session=session)
        finally:
            await close_tool_stack(stack)

        return ResponsesAgentResponse(
            output=[item.to_input_item() for item in result.new_items],
            custom_outputs={"session_id": session.session_id if session else session_id},
        )
    except Exception as exc:
        if _is_lakebase_error(exc):
            raise HTTPException(status_code=503, detail=lakebase_access_message()) from exc
        raise


@stream()
async def stream_handler(request: ResponsesAgentRequest) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    try:
        if _is_title_request(request):
            result = Runner.run_streamed(_title_agent(), input=[item.model_dump() for item in request.input])
            async for event in process_agent_stream_events(result.stream_events()):
                yield event
            return

        session_id = get_session_id(request)
        if session_id:
            mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})
        session = maybe_create_session(session_id)

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            mcp_servers, unavailable_tools = await connect_available_mcp_servers(stack, WorkspaceClient())
            direct_tools, direct_unavailable = await build_direct_databricks_mcp_tools(stack)
            atlassian_tools, atlassian_unavailable = await build_atlassian_tools(stack)
            agent = create_agent(
                mcp_servers=mcp_servers,
                unavailable_tools=unavailable_tools + direct_unavailable + atlassian_unavailable,
                extra_tools=direct_tools + atlassian_tools,
                context_tools_enabled=bool(atlassian_tools),
            )
            result = Runner.run_streamed(agent, input=await deduplicate_input(request, session), session=session)
            async for event in process_agent_stream_events(result.stream_events()):
                yield event
        finally:
            await close_tool_stack(stack)
    except Exception as exc:
        if _is_lakebase_error(exc):
            raise HTTPException(status_code=503, detail=lakebase_access_message()) from exc
        raise
