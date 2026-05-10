import tempfile
import unittest
from pathlib import Path

from brain.master_agent import JarvisBrain


class MasterAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "brain_memory.db"
        self.event_log_path = root / "brain_events.jsonl"
        self.brain = JarvisBrain(db_path=self.db_path, event_log_path=self.event_log_path)
        self.brain.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_remember_accepts_valid_global_rule(self):
        record = self.brain.remember(
            "GLOBAL_RULE",
            "global",
            "Separate global rules from project context.",
            status="validated",
        )
        self.assertEqual(record.memory_type, "GLOBAL_RULE")
        self.assertEqual(record.scope, "global")

    def test_remember_rejects_technical_state_global(self):
        with self.assertRaises(ValueError):
            self.brain.remember(
                "TECHNICAL_STATE",
                "global",
                "This project uses a temporary database for tests.",
            )

    def test_analyze_request_returns_recommended_mode(self):
        result = self.brain.analyze_request("Please explain why this traceback failed")
        self.assertEqual(result["recommended_mode"], "Debugger")
        self.assertEqual(result["mode"], "Debugger")

    def test_recall_retrieves_global_rules_and_project_context(self):
        self.brain.remember(
            "GLOBAL_RULE",
            "global",
            "Do not store secrets.",
            status="validated",
        )
        self.brain.remember(
            "PROJECT_CONTEXT",
            "project:Meu-Jarvi",
            "The brain foundation is standalone in Phase 3.",
            project="Meu-Jarvi",
            status="confirmed",
        )

        result = self.brain.recall(project="Meu-Jarvi", query="standalone")
        self.assertEqual(len(result["global_rules"]), 1)
        self.assertEqual(len(result["project_context"]), 1)
        self.assertEqual(len(result["matching_memories"]), 1)


if __name__ == "__main__":
    unittest.main()
