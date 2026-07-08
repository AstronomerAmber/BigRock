# Bobabricks Store Operations Demo

A self-contained demo scaffold for upgrading a Bobabricks Store Operations Agent from Q&A into an approval-governed regional risk briefing workflow.

The ground truth for this demo lives in:

- `BOBABRICKS_DEMO_RUNBOOK.md`
- `CODEX_UPGRADE_PROMPT.txt`
- `BUDGET_GUARDRAIL_SCRIPT.md`

## Demo Shape

The repo is organized to support a live Codex/Omnigent-style upgrade moment:

- `agent-store-ops/` contains the agent configuration, prompt, tool contracts, policy notes, and sample briefing output.
- `app/` contains a lightweight Streamlit-style Databricks app scaffold with the user-facing action `Generate Weekly Regional Briefing`.
- `data/` contains sample Bobabricks operating data for deterministic local/demo behavior.
- `scripts/` contains local validation and sample briefing generation helpers.

## Intended Branch Flow

For a live demo, create two branches from this scaffold:

```bash
git checkout -b demo-start
# keep only baseline tools/behavior if you want a live upgrade moment

git checkout -b demo-final
# keep the full workflow implemented here
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
```

## Notes

This scaffold intentionally uses mock/local tool contracts so the demo can be rehearsed without live Databricks or Atlassian credentials. Replace the placeholder connection values in `agent-store-ops/mcp_servers.yaml` and `app/app.yaml` when wiring to a real environment.
