import unittest

from app.services.store_ops import LocalDataStore, StoreOpsEngine, OpsTaskClient


class StoreOpsEngineTest(unittest.TestCase):
    def setUp(self):
        self.data_store = LocalDataStore()
        self.engine = StoreOpsEngine(self.data_store)

    def test_weekly_pacific_briefing_uses_expected_categories_and_order(self):
        issues = self.engine.build_weekly_briefing("Pacific")

        self.assertGreaterEqual(len(issues), 4)
        self.assertEqual("high", issues[0].severity)
        self.assertTrue(
            {issue.category for issue in issues}.issubset(
                {"sales", "labor", "inventory", "training", "customer_experience"}
            )
        )
        self.assertIn(("104", "training", "high"), [(issue.store_id, issue.category, issue.severity) for issue in issues])
        self.assertIn(("117", "inventory", "high"), [(issue.store_id, issue.category, issue.severity) for issue in issues])

    def test_task_drafts_skip_duplicate_open_tasks(self):
        issues = self.engine.build_weekly_briefing("Pacific")
        existing_tasks = OpsTaskClient(self.data_store).list_tasks()

        drafts = self.engine.draft_high_severity_tasks(issues, existing_tasks)

        self.assertEqual(["117", "117"], [draft.store_id for draft in drafts])
        self.assertTrue(all(draft.severity == "high" for draft in drafts))

    def test_tool_status_defaults_to_deployed_capabilities(self):
        tool_status = {row["tool"]: row["status"] for row in self.engine.tool_status()}

        self.assertEqual("configured", tool_status["Genie Agent"])
        self.assertEqual("enabled", tool_status["Confluence"])
        self.assertEqual("enabled", tool_status["Inventory MCP"])
        self.assertEqual("approval-gated", tool_status["OpsTask"])


if __name__ == "__main__":
    unittest.main()
