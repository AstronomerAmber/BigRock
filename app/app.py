from pathlib import Path

import streamlit as st

SAMPLE_BRIEFING = Path(__file__).resolve().parents[1] / "agent-store-ops" / "sample_weekly_briefing.md"

st.set_page_config(page_title="Bobabricks Store Operations", page_icon="☕")
st.title("Bobabricks Store Operations Agent")
st.caption("Regional risk briefings with governed tool use and approval-gated follow-up creation.")

if st.button("Generate Weekly Regional Briefing", type="primary"):
    st.session_state["prompt"] = "Generate my weekly Pacific regional risk briefing and create follow-up tasks for high-severity items."

prompt = st.text_area(
    "Ask the agent",
    value=st.session_state.get("prompt", "What tools do you have?"),
    height=120,
)

if st.button("Run Demo Query"):
    st.subheader("Agent Response")
    if "weekly" in prompt.lower() and "briefing" in prompt.lower():
        st.markdown(SAMPLE_BRIEFING.read_text())
    else:
        st.markdown(
            """
I can use Genie Agent, StoreTime, OpsTask, Confluence, Inventory MCP, current time, and memory.

For write actions such as creating OpsTask follow-ups, I will ask for approval before taking action.
"""
        )
