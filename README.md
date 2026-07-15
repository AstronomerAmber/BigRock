# Bobabricks Store Operations Demo

A self-contained demo scaffold for upgrading a Bobabricks Store Operations Agent from Q&A into an approval-governed regional risk briefing workflow.

The ground truth for this demo lives in:

- `BOBABRICKS_DEMO_RUNBOOK.md`
- `CODEX_UPGRADE_PROMPT.txt`
- `BUDGET_GUARDRAIL_SCRIPT.md`

## Demo Shape

The repo is organized to support a live Codex/Omnigent-style upgrade moment:

- `agent-store-ops/` contains the agent configuration, prompt, tool contracts, policy notes, and sample briefing output.
- `app/` contains the Streamlit Databricks app plus local service adapters that power the weekly briefing, tool-status view, duplicate-aware OpsTask drafts, and approval-gated task creation.
- `data/` contains sample Bobabricks operating data for deterministic local/demo behavior and Delta table seeding.
- `mcp-apps/` contains Databricks App MCP services for StoreTime, OpsTask, and Inventory.
- `scripts/` contains local validation and sample briefing generation helpers.

## Recommended First Pass

- Use real Databricks Genie for Bobabricks metrics, including first-pass inventory facts.
- Use real Databricks-App MCPs for StoreTime and OpsTask, backed by demo Delta tables.
- Use real Lakebase memory for stable preferences and regional context.
- Keep Confluence disabled in `demo-start`, then enable it live through the real Databricks managed Atlassian/Confluence MCP. The Bobabricks article is demo content, but the connector is the actual workspace integration.
- For Inventory, either keep inventory data in Genie for the first pass or enable a small `bobabricks-inventory-mcp` Databricks App for the final WOW query.

## Intended Branch Flow

For a live demo, create two branches from this scaffold:

```bash
git checkout -b demo-start
# keep Genie, StoreTime, OpsTask, current time, and memory available
# keep Confluence disabled and optional Inventory MCP inactive

git checkout -b demo-final
# enable Confluence live; optionally enable Inventory MCP as a separate final-pass tool
```

## Key Demo Query

```text
Generate my weekly Pacific regional risk briefing and create follow-up tasks for high-severity items.
```

Expected behavior:

1. Uses store performance, training, labor, inventory, playbook, and existing OpsTask context.
2. Classifies each issue as `sales`, `labor`, `inventory`, `training`, or `customer_experience`.
3. Returns a weekly briefing with store, severity, category, evidence, and recommended action.
4. Asks approval before creating OpsTask follow-ups for high-severity risks.

## Local Smoke Test

```bash
python3 scripts/generate_sample_briefing.py --region Pacific
python3 scripts/validate_demo.py
python3 -m unittest tests/test_store_ops.py
```

The app uses CSV/JSON-backed adapters in `app/services/store_ops.py` for deterministic demo behavior. Created OpsTask tickets are written to `/tmp/bobabricks_created_ops_tasks.json` by default so deployment/runtime writes do not mutate committed sample data.

## Databricks App MCPs

The StoreTime, OpsTask, and Inventory MCP services live in `mcp-apps/`. Deploy them as separate Databricks Apps named `bobabricks-storetime-mcp`, `bobabricks-opstask-mcp`, and `bobabricks-inventory-mcp` after provisioning the demo Delta tables. See `mcp-apps/README.md` for commands.

## Notes

This scaffold is now oriented around a real Databricks-first demo path. Local sample data remains available for deterministic rehearsal, but `agent-store-ops/mcp_servers.yaml` expects Genie, Databricks-App MCPs, managed Atlassian MCP, and Lakebase memory to be wired in the target workspace.
