# Bobabricks Store Operations Demo Runbook

## Goal
Demonstrate an enterprise-grade Store Operations Agent built with OpenAI/GPT/Codex/Omnigent that evolves live from Q&A into an approval-governed operations workflow.

## Useful Links
- Original demo reference: https://github.com/aravind-segu_data/store_ops_demo_aravind
- Target repo for new demo assets: https://github.com/amber-roberts_data/Omnigent_demos
- Databricks app templates: https://github.com/databricks/app-templates/tree/main

## Step 0: Show Architecture Diagram
Explain the architecture left to right:
- Bobabricks employee uses a chat interface.
- Store Operations Agent sits in the middle as the reasoning layer.
- Tools include Genie Agent, StoreTime, OpsTask, Confluence, and Lakebase Memory.
- Platform services include Agent Bricks, Genie Spaces, MLflow, Unity AI Gateway, Workflows, Databricks Apps, and Governance.

Key message:
"This is not just a chatbot. It is an operational agent connected to governed enterprise data, internal tools, memory, and production platform services."

## Step 1: Open The Deployed Agent
First point to: https://github.com/databricks/app-templates

Launch the Bobabricks Store Operations Agent in the app UI.

Ask:
`What tools do you have?`

Expected tools:
- Genie Agent for store operations data.
- StoreTime for labor and scheduling.
- OpsTask for tickets and task tracking.
- Current time utility.
- Memory.

Note:
- Keep Confluence or Inventory missing at first if you want a live upgrade moment.

## Step 2: Ask A Store Performance Question
Ask:
`Show average versus actual training hours for my Pacific stores and flag any stores falling behind.`

Agent uses:
- Genie Agent.

Expected result:
- Store 104 or another named store is behind.
- Agent gives a short table or bullet summary.

Key message:
"The agent can reason over operational metrics, not just retrieve documents."

## Step 3: Ask A Diagnostic Follow-Up
Ask:
`Why is Store 104 behind on training? Is it a scheduling problem or a completion problem?`

Agent uses:
- StoreTime.
- Possibly OpsTask.

Expected result:
- Store 104 scheduled training shifts, but they were converted to service coverage during rush windows.

Key message:
"Now the agent is combining analytics with operational systems."

## Step 4: Expose The Context Gap
Ask:
`What are our FY26 training goals, and how does Store 104 stack up?`

Expected result:
- Agent cannot answer fully because it lacks Confluence/company context.

Key message:
"The agent knows store data, but not yet the company operating plan."

## Step 5: Use Codex / Omnigent For A Harder Upgrade
Ask Codex:

`For the Bobabricks store operations agent, can you add a regional risk briefing capability?

Please:
1. Add the Atlassian Confluence MCP for FY26 goals and store playbooks.
2. Add inventory risk analysis using the Inventory MCP.
3. Update the system prompt so the agent classifies issues as sales, labor, inventory, training, or customer experience.
4. Add approval-gated OpsTask follow-up creation for high-severity risks.
5. Add a “Generate Weekly Regional Briefing” action in the app.
6. Redeploy the app.`

Key message:
"We are not just changing a config. Codex is upgrading the agent into a workflow."

## Step 6: Show The Code Diff
Show the Omnigent change view.

Highlight:
- Confluence MCP added.
- Inventory MCP added.
- System prompt updated.
- Approval-gated task creation added.
- Weekly briefing command or UI action added.

Key message:
"Codex handled the wiring across tools, config, prompt, and deployment."

## Step 7: Show Platform Services During Redeploy
While redeploy runs, show:
- MLflow traces from earlier questions.
- Unity AI Gateway model/tool configuration.
- Unity AI Gateway dashboard and budgets/policies.

Key message:
"This is observable, governed, and production-ready."

## Step 8: Return To The Agent
Ask:
`What tools do you have?`

Confirm the agent now has:
- Genie Agent.
- StoreTime.
- OpsTask.
- Confluence.
- Inventory MCP.
- Memory.

## Step 9: Run The WOW Query
Ask:
`Generate my weekly regional risk briefing for the Pacific region, and create follow-up tasks for anything high severity.`

Expected agent behavior:
- Uses Genie to identify underperforming stores.
- Uses StoreTime to diagnose labor/scheduling.
- Uses Inventory MCP to detect stockout risks.
- Uses Confluence to compare against FY26 goals and playbooks.
- Uses OpsTask to inspect existing issues.
- Produces a prioritized briefing.
- Requests approval before creating tasks.

## Step 10: Approval Moment
Agent says:
`I found 3 high-severity risks. I recommend creating follow-up tasks for Store 104 and Store 117. Do you approve creating these OpsTask tickets?`

Action:
- Click approve.
- Agent creates tasks.

Key message:
"The agent can take action, but governance controls write operations."

## Step 11: Show Memory
Say:
`Remember that I manage the Pacific region and prefer regional briefings as concise bullet lists with severity labels.`

Then ask:
`Give me my store risk summary.`

Expected behavior:
- Agent uses Pacific region automatically.
- Agent formats the answer as requested.

## Step 12: Show Background / Scheduled Workflow
Show a weekly report workflow:
`Generate Pacific regional risk briefing every Monday at 7 AM.`

Explain:
- Long-running analysis can run in background mode.
- Scheduled jobs can use the same agent/tools.
- Traces still land in MLflow.

## Step 13: Wrap
Closing message:
"We started with a store ops Q&A agent, used Codex and Omnigent to upgrade it live, connected it to company context and inventory systems, and turned it into an approval-gated operations workflow."

---

## Backup Prompts (if a turn fails)
- `Summarize Pacific store risks this week by severity.`
- `Classify Store 104 issues as sales, labor, inventory, training, or customer experience with evidence.`
- `Propose actions only; do not create tasks yet.`
- `Now create tasks for high-severity items.`

## Success Checklist
- [ ] Architecture narrative delivered.
- [ ] Baseline Q&A shown.
- [ ] Live Codex upgrade shown.
- [ ] Budget guardrail shown.
- [ ] Post-upgrade WOW query succeeds.
- [ ] Approval-gated write shown.
- [ ] MLflow trace shown.
