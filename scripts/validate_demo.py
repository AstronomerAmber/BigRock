#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "BOBABRICKS_DEMO_RUNBOOK.md",
    "CODEX_UPGRADE_PROMPT.txt",
    "BUDGET_GUARDRAIL_SCRIPT.md",
    "agent-store-ops/agent.yaml",
    "agent-store-ops/system_prompt.md",
    "agent-store-ops/mcp_servers.yaml",
    "agent-store-ops/tools.yaml",
    "agent-store-ops/policies.yaml",
    "agent-store-ops/sample_weekly_briefing.md",
    "app/app.yaml",
    "app/app.py",
    "data/store_metrics.csv",
    "data/schedules.csv",
    "data/inventory.csv",
    "data/confluence_playbooks.json",
    "data/ops_tasks.json",
    "scripts/generate_sample_briefing.py",
    "app/services/store_ops.py",
    "tests/test_store_ops.py",
]

REQUIRED_TEXT = {
    "agent-store-ops/system_prompt.md": [
        "sales",
        "labor",
        "inventory",
        "training",
        "customer_experience",
        "Ask for explicit approval before creating any task",
    ],
    "agent-store-ops/mcp_servers.yaml": [
        "managed_atlassian_mcp",
        "CONFLUENCE_MCP_ENABLED:-true",
        "databricks_app_mcp",
        "FY26 Store Operations Goals",
        "Inventory Stockout Escalation Playbook",
    ],
    "app/app.yaml": ["Generate Weekly Regional Briefing"],
    "app/services/store_ops.py": [
        "class StoreOpsEngine",
        "class OpsTaskClient",
        "draft_high_severity_tasks",
    ],
}


def main():
    failures = []
    for relative_path in REQUIRED_FILES:
        if not (ROOT / relative_path).exists():
            failures.append(f"Missing {relative_path}")

    for relative_path, snippets in REQUIRED_TEXT.items():
        text = (ROOT / relative_path).read_text() if (ROOT / relative_path).exists() else ""
        for snippet in snippets:
            if snippet not in text:
                failures.append(f"Missing text in {relative_path}: {snippet}")

    if failures:
        print("Demo validation failed:")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)

    print("Demo validation passed.")


if __name__ == "__main__":
    main()
