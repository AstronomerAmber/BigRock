import logging
import os
from contextlib import asynccontextmanager

from databricks_ai_bridge.long_running import LongRunningAgentServer
from databricks_openai.agents import AsyncDatabricksSession
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from mlflow.genai.agent_server import setup_mlflow_git_based_version_tracking

from agent_server.utils import lakebase_access_message, lakebase_config, replace_fake_id

import agent_server.agent as bobabricks_agent

logger = logging.getLogger(__name__)


async def run_lakebase_session_setup() -> None:
    if not lakebase_config.is_configured:
        logger.warning("Lakebase not configured; skipping session table setup.")
        return
    session = AsyncDatabricksSession(
        session_id="__startup__",
        instance_name=lakebase_config.instance_name,
        autoscaling_endpoint=lakebase_config.autoscaling_endpoint,
        project=lakebase_config.autoscaling_project,
        branch=lakebase_config.autoscaling_branch,
        schema=lakebase_config.memory_schema,
    )
    await session._ensure_tables()


class AgentServer(LongRunningAgentServer):
    def transform_stream_event(self, event, response_id):
        return replace_fake_id(event, response_id)


agent_server = AgentServer(
    "ResponsesAgent",
    enable_chat_proxy=True,
    db_instance_name=lakebase_config.instance_name,
    db_autoscaling_endpoint=lakebase_config.autoscaling_endpoint,
    db_project=lakebase_config.autoscaling_project,
    db_branch=lakebase_config.autoscaling_branch,
    task_timeout_seconds=float(os.getenv("TASK_TIMEOUT_SECONDS", "3600")),
    poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "1.0")),
)

logging.getLogger("agent_server").setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
_original_lifespan = agent_server.app.router.lifespan_context


@asynccontextmanager
async def _lifespan(app):
    try:
        await run_lakebase_session_setup()
    except Exception as exc:
        os.environ["BOBABRICKS_DISABLE_LAKEBASE"] = "1"
        logger.warning(
            "Lakebase session setup failed; continuing without persistent session memory: %s\n\n%s",
            exc,
            lakebase_access_message(),
            exc_info=True,
        )
    try:
        async with _original_lifespan(app):
            yield
    except Exception as exc:
        logger.warning("Long-running DB initialization failed: %s. Background mode disabled.", exc)
        yield


agent_server.app.router.lifespan_context = _lifespan
app = agent_server.app
setup_mlflow_git_based_version_tracking()


BOBABRICKS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Bobabricks</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f7f5f2; color: #202124; }
    .shell { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
    aside { border-right: 1px solid #ddd8d0; background: #fffaf3; padding: 18px; }
    main { display: flex; flex-direction: column; min-height: 100vh; }
    h1 { font-size: 24px; margin: 0 0 4px; }
    .powered { color: #5f6368; font-size: 13px; font-weight: 600; margin-bottom: 18px; }
    .panel { border: 1px solid #e4ded5; border-radius: 8px; padding: 12px; margin: 14px 0; background: #fff; }
    .label { color: #6b6258; font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; margin-bottom: 9px; }
    .tool { margin: 10px 0; }
    .tool strong { display: block; font-size: 14px; }
    .tool span { color: #6b6258; font-size: 12px; }
    .prompt { width: 100%; border: 0; border-radius: 6px; background: transparent; color: #5f6368; cursor: pointer; display: block; font: inherit; font-size: 12px; line-height: 1.45; margin: 3px 0; padding: 8px; text-align: left; }
    .prompt:hover { background: #f1ece5; color: #202124; }
    .welcome { max-width: 780px; margin: 48px auto 20px; padding: 0 24px; text-align: center; }
    .welcome p { color: #5f6368; line-height: 1.55; }
    #messages { flex: 1; margin: 0 auto; max-width: 860px; padding: 0 24px 24px; width: 100%; box-sizing: border-box; }
    .msg { border-bottom: 1px solid #e6e0d8; padding: 18px 0; white-space: pre-wrap; line-height: 1.5; }
    .msg.user { color: #453d36; font-weight: 650; }
    .msg.assistant { color: #202124; }
    form { display: flex; gap: 10px; margin: 0 auto; max-width: 860px; padding: 16px 24px 28px; width: 100%; box-sizing: border-box; }
    textarea { border: 1px solid #d9d2c8; border-radius: 8px; flex: 1; font: inherit; min-height: 46px; padding: 12px; resize: vertical; }
    button.send { background: #1f1f1f; border: 0; border-radius: 8px; color: #fff; cursor: pointer; font: inherit; font-weight: 650; padding: 0 18px; }
    button.send:disabled { opacity: .55; cursor: wait; }
    @media (max-width: 780px) { .shell { grid-template-columns: 1fr; } aside { border-right: 0; border-bottom: 1px solid #ddd8d0; } }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>🧋 Bobabricks</h1>
      <div class="powered">Powered by Databricks</div>
      <div class="panel">
        <div class="label">Lakebase</div>
        <div class="tool"><strong>bobabricks</strong><span>session memory currently disabled by Lakebase auth</span></div>
      </div>
      <div class="panel">
        <div class="label">Tools</div>
        <div class="tool"><strong>Genie Agent</strong><span>governed store metrics</span></div>
        <div class="tool"><strong>StoreTime</strong><span>training schedules and converted hours</span></div>
        <div class="tool"><strong>OpsTask</strong><span>approval-gated follow-ups</span></div>
        <div class="tool"><strong>Confluence</strong><span>FY26 goals and operating standards</span></div>
      </div>
      <div class="panel">
        <div class="label">Demo questions</div>
        <button class="prompt">What tools do you have?</button>
        <button class="prompt">Show average versus actual training hours for my Pacific stores and flag any stores falling behind.</button>
        <button class="prompt">What are our FY26 training goals, and how does Store 104 stack up?</button>
        <button class="prompt">Generate my weekly regional risk briefing.</button>
      </div>
    </aside>
    <main>
      <section class="welcome">
        <h1>Welcome to Bobabricks</h1>
        <p>Bobabricks is a premium boba tea company running a store operations demo on Databricks. This assistant helps regional leaders inspect FY26 training goals, store execution risk, scheduling evidence, and approval-gated follow-up tasks across Genie, StoreTime, OpsTask, Confluence, and Lakebase.</p>
      </section>
      <div id="messages"></div>
      <form id="chat-form">
        <textarea id="prompt" placeholder="Ask Bobabricks..."></textarea>
        <button class="send" type="submit">Send</button>
      </form>
    </main>
  </div>
  <script>
    const form = document.getElementById('chat-form');
    const input = document.getElementById('prompt');
    const messages = document.getElementById('messages');
    const send = form.querySelector('button');
    function add(role, text) {
      const div = document.createElement('div');
      div.className = `msg ${role}`;
      div.textContent = text;
      messages.appendChild(div);
      div.scrollIntoView({ behavior: 'smooth', block: 'end' });
      return div;
    }
    async function ask(text) {
      const prompt = text.trim();
      if (!prompt) return;
      add('user', prompt);
      input.value = '';
      send.disabled = true;
      const pending = add('assistant', 'Thinking...');
      try {
        const res = await fetch('/bobabricks-chat', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ prompt }),
        });
        const data = await res.json();
        pending.textContent = data.response || data.error || '(no response)';
      } catch (err) {
        pending.textContent = `Request failed: ${err}`;
      } finally {
        send.disabled = false;
      }
    }
    form.addEventListener('submit', (event) => { event.preventDefault(); ask(input.value); });
    document.querySelectorAll('.prompt').forEach((button) => button.addEventListener('click', () => ask(button.textContent || '')));
  </script>
</body>
</html>
"""


def _result_text(result) -> str:
    if getattr(result, "final_output", None):
        return str(result.final_output)
    chunks = []
    for item in getattr(result, "new_items", []) or []:
        value = item.to_input_item() if hasattr(item, "to_input_item") else item
        content = value.get("content") if isinstance(value, dict) else None
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(part.get("text", "") for part in content if isinstance(part, dict))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


@app.get("/", response_class=HTMLResponse)
async def bobabricks_home():
    return HTMLResponse(BOBABRICKS_HTML)


@app.post("/bobabricks-chat")
async def bobabricks_chat(request: Request):
    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        return JSONResponse({"error": "Prompt is required."}, status_code=400)
    agent = bobabricks_agent.create_agent(
        unavailable_tools=["Genie Agent", "StoreTime", "OpsTask", "Atlassian Confluence"],
        extra_tools=[],
    )
    result = await bobabricks_agent.Runner.run(agent, [{"role": "user", "content": prompt}])
    text = _result_text(result)
    return {"response": text or "(no response)"}


def main():
    agent_server.run(app_import_string="agent_server.start_server:app")


if __name__ == "__main__":
    main()
