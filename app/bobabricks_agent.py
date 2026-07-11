import asyncio
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable


AGENT_MODEL = os.environ.get("AGENT_MODEL", "databricks-gpt-5").strip()
OPENAI_AGENTS_SDK_ENABLED = os.environ.get("OPENAI_AGENTS_SDK_ENABLED", "true").lower() == "true"


@dataclass(frozen=True)
class BobabricksAgentTools:
    check_available_tools: Callable[[], str]
    compare_training_hours: Callable[[], str]
    get_fy26_training_goals: Callable[[], str]
    generate_weekly_briefing: Callable[[], str]
    get_store_ops_context: Callable[[], str]


@contextmanager
def mlflow_span(name: str, inputs: dict | None = None, attributes: dict | None = None):
    try:
        import mlflow
    except Exception:
        yield None
        return

    start_span = getattr(mlflow, "start_span", None)
    if not start_span:
        yield None
        return

    try:
        with start_span(name=name) as span:
            if inputs and hasattr(span, "set_inputs"):
                span.set_inputs(inputs)
            if attributes:
                if hasattr(span, "set_attributes"):
                    span.set_attributes(attributes)
                elif hasattr(span, "set_attribute"):
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
            yield span
    except Exception:
        yield None


def set_span_output(span, output: str) -> None:
    if span is None or not hasattr(span, "set_outputs"):
        return
    try:
        span.set_outputs({"output": output[:8000]})
    except Exception:
        return


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


def run_bobabricks_agent(prompt: str, selected_region: str, tools: BobabricksAgentTools) -> str | None:
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
        with mlflow_span(
            "functions.check_available_tools",
            inputs={"selected_region": selected_region},
            attributes={"bobabricks.tool": "MCP registry"},
        ) as span:
            output = tools.check_available_tools()
            set_span_output(span, output)
            return output

    @function_tool
    def compare_training_hours() -> str:
        """Compare scheduled versus actual training hours for the selected region and flag stores behind target."""
        with mlflow_span(
            "functions.compare_training_hours",
            inputs={"selected_region": selected_region},
            attributes={"bobabricks.tool": "Genie + StoreTime + Confluence"},
        ) as span:
            output = tools.compare_training_hours()
            set_span_output(span, output)
            return output

    @function_tool
    def get_fy26_training_goals() -> str:
        """Retrieve FY26 training goals and compare Store 104 against those standards."""
        with mlflow_span(
            "functions.get_fy26_training_goals",
            inputs={"selected_region": selected_region, "store_id": "104"},
            attributes={"bobabricks.tool": "Confluence + Genie + StoreTime"},
        ) as span:
            output = tools.get_fy26_training_goals()
            set_span_output(span, output)
            return output

    @function_tool
    def generate_weekly_briefing() -> str:
        """Generate a weekly regional risk briefing and draft approval-gated OpsTask follow-ups."""
        with mlflow_span(
            "functions.generate_weekly_briefing",
            inputs={"selected_region": selected_region},
            attributes={"bobabricks.tool": "Genie + Inventory + OpsTask"},
        ) as span:
            output = tools.generate_weekly_briefing()
            set_span_output(span, output)
            return output

    @function_tool
    def get_store_ops_context() -> str:
        """Load regional store metrics, schedules, inventory, operating standards, and existing OpsTask context for free-form questions."""
        with mlflow_span(
            "functions.get_store_ops_context",
            inputs={"selected_region": selected_region},
            attributes={"bobabricks.tool": "regional context"},
        ) as span:
            output = tools.get_store_ops_context()
            set_span_output(span, output)
            return output

    agent = Agent(
        name="Bobabricks Store Operations Agent",
        model=AGENT_MODEL,
        instructions=(
            "You are the Bobabricks Store Operations Agent. Use the provided tools for all user questions. "
            "Do not invent metrics, stores, goals, or task ids. Lead with the answer, then cite which tool supplied the evidence. "
            "Use check_available_tools for tool-list questions, compare_training_hours for training-hour comparisons, "
            "get_fy26_training_goals for FY26 standards or Store 104 goal questions, and generate_weekly_briefing for weekly briefing requests. "
            "When compare_training_hours returns a markdown table, preserve that table in your final answer instead of summarizing it. "
            "For any other free-form store, region, risk, training, inventory, customer-experience, or task question, call get_store_ops_context "
            "and answer from that context. If the requested fact is not present, say what is missing instead of guessing. "
            "OpsTask creation remains approval-gated by the UI. If a tool is marked configured, describe it as attached/configured; "
            "do not downgrade configured Databricks App resources to unavailable because of raw session-context diagnostics."
        ),
        tools=[
            check_available_tools,
            compare_training_hours,
            get_fy26_training_goals,
            generate_weekly_briefing,
            get_store_ops_context,
        ],
    )

    try:
        with mlflow_span(
            "AgentRunner.run",
            inputs={"prompt": prompt, "selected_region": selected_region},
            attributes={"bobabricks.model": AGENT_MODEL},
        ) as span:
            result = _run_async(Runner.run(agent, [{"role": "user", "content": prompt}]))

            final_output = getattr(result, "final_output", None)
            if final_output:
                output = str(final_output)
                set_span_output(span, output)
                return output

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
            output = "\n\n".join(part for part in parts if part) or None
            if output:
                set_span_output(span, output)
            return output
    except Exception:
        return None
