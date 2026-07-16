# Bobabricks Demo Agent Instructions

These instructions apply to this repository.

## Short-Demo Upgrade

When the user asks:

> For the Bobabricks store operations agent, can you add our FY26 goals and store playbooks as context? Please add the Atlassian Confluence MCP so the agent can pull from Confluence directly, and redeploy the app.

Treat that as the short-demo Confluence upgrade. Make only the small Confluence upgrade:

- Add the managed Atlassian/Confluence MCP to `agent-store-ops/mcp_servers.yaml`.
- Add exactly one new tool to `agent-store-ops/tools.yaml`: `search_confluence`.
- Add `CONFLUENCE_MCP_ENABLED=true` and `ATLASSIAN_MCP_URL` to both root app manifests: `app.yml` and `app.yaml`.
- Preserve the existing baseline capabilities: Genie, StoreTime, OpsTask, and Lakebase sidebar/session context.
- Do not add long-demo features such as inventory risk, weekly regional briefing, task approvals, or scheduled workflow.

## Deployment

This app must be deployed as the repo-root Databricks chat app. Do not infer a bundle-style deployment from `databricks.yml`.

Before redeploying, ask:

```text
Approve redeploying bobabricks-store-ops-demo with the Confluence upgrade?
```

After approval, deploy from the repo root with exactly:

```bash
databricks apps deploy bobabricks-store-ops-demo --profile bigrock --json '{"mode":"SNAPSHOT","git_source":{"branch":"main"}}'
```

Deployment guardrails:

- Do not run `databricks apps deploy --profile DEFAULT --auto-approve`.
- Do not deploy without the app name `bobabricks-store-ops-demo`.
- Do not use `--source-code-path .` or `source_code_path: "."`.
- Do not deploy the `app/` directory; that is the Streamlit app, not the chat demo.
- Use profile `bigrock`, not `DEFAULT`.
- Check deployment status after redeploying.
- Do not read app logs unless deployment fails or the app does not start.

