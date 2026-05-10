import json
import tempfile
import unittest
from pathlib import Path

from memory_engine.database import init_db
from memory_engine.retriever import (
    get_memory_by_id,
    list_active_global_rules,
    list_project_context,
    retrieve_context,
    search_memories,
)
from memory_engine.writer import archive_memory, create_memory, update_memory_status


class MemoryEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "test_memory.db"
        self.event_log_path = root / "raw_events.jsonl"
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_global_rule_and_retrieve(self):
        record = create_memory(
            "GLOBAL_RULE",
            "global",
            "Diagnose before changing.",
            status="validated",
            importance=9,
            confidence=0.95,
            source="unit_test",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

        fetched = get_memory_by_id(record.memory_id, db_path=self.db_path)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.memory_type, "GLOBAL_RULE")
        self.assertEqual(fetched.scope, "global")

        rules = list_active_global_rules(db_path=self.db_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].content, "Diagnose before changing.")

    def test_create_project_context_and_retrieve(self):
        create_memory(
            "PROJECT_CONTEXT",
            "project:Meu-Jarvi",
            "The new memory engine must remain isolated from the running Jarvis app.",
            status="confirmed",
            importance=8,
            confidence=0.9,
            source="unit_test",
            project="Meu-Jarvi",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

        project_context = list_project_context("Meu-Jarvi", db_path=self.db_path)
        self.assertEqual(len(project_context), 1)
        self.assertEqual(project_context[0].memory_type, "PROJECT_CONTEXT")

    def test_valid_project_context_with_project_scope_is_accepted(self):
        record = create_memory(
            "PROJECT_CONTEXT",
            "project:Meu-Jarvi",
            "Project context must stay scoped to Meu-Jarvi.",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

        self.assertEqual(record.scope, "project:Meu-Jarvi")
        self.assertEqual(len(search_memories(db_path=self.db_path)), 1)

    def test_valid_technical_state_with_project_scope_is_accepted(self):
        record = create_memory(
            "TECHNICAL_STATE",
            "project:Meu-Jarvi",
            "Memory engine tests use temporary database paths.",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

        self.assertEqual(record.memory_type, "TECHNICAL_STATE")
        self.assertEqual(record.scope, "project:Meu-Jarvi")

    def test_valid_global_rule_with_global_scope_is_accepted(self):
        record = create_memory(
            "GLOBAL_RULE",
            "global",
            "Do not store secrets.",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

        self.assertEqual(record.memory_type, "GLOBAL_RULE")
        self.assertEqual(record.scope, "global")

    def test_project_context_global_scope_is_rejected_without_rows_or_events(self):
        with self.assertRaisesRegex(ValueError, "PROJECT_CONTEXT.*cannot use scope='global'"):
            create_memory(
                "PROJECT_CONTEXT",
                "global",
                "Meu-Jarvi uses a local SQLite memory engine.",
                db_path=self.db_path,
                event_log_path=self.event_log_path,
            )

        self.assertEqual(search_memories(db_path=self.db_path, include_archived=True), [])
        self.assertFalse(self.event_log_path.exists())

    def test_technical_state_global_scope_is_rejected_without_rows_or_events(self):
        with self.assertRaisesRegex(ValueError, "TECHNICAL_STATE.*cannot use scope='global'"):
            create_memory(
                "TECHNICAL_STATE",
                "global",
                "Meu-Jarvi currently has memory_engine as an isolated package.",
                db_path=self.db_path,
                event_log_path=self.event_log_path,
            )

        self.assertEqual(search_memories(db_path=self.db_path, include_archived=True), [])
        self.assertFalse(self.event_log_path.exists())

    def test_global_rule_project_scope_is_rejected_without_rows_or_events(self):
        with self.assertRaisesRegex(ValueError, "GLOBAL_RULE.*scope='global'"):
            create_memory(
                "GLOBAL_RULE",
                "project:Meu-Jarvi",
                "Always use SQLite for this project.",
                db_path=self.db_path,
                event_log_path=self.event_log_path,
            )

        self.assertEqual(search_memories(db_path=self.db_path, include_archived=True), [])
        self.assertFalse(self.event_log_path.exists())

    def test_update_and_archive_memory_status(self):
        record = create_memory(
            "WARNING",
            "project:Meu-Jarvi",
            "Do not connect the new memory engine to Gemini yet.",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )
        updated = update_memory_status(
            record.memory_id,
            "confirmed",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )
        self.assertEqual(updated.status, "confirmed")

        archived = archive_memory(
            record.memory_id,
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )
        self.assertEqual(archived.status, "archived")
        active = search_memories(query="Gemini", db_path=self.db_path)
        self.assertEqual(active, [])

    def test_jsonl_event_log_appended(self):
        create_memory(
            "PROCEDURE",
            "global",
            "Use temporary database paths in tests.",
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )
        self.assertTrue(self.event_log_path.exists())
        lines = self.event_log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["event_type"], "memory_created")

    def test_retrieve_context_ordering(self):
        create_memory(
            "GLOBAL_RULE",
            "global",
            "Validated rule",
            status="validated",
            importance=5,
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )
        create_memory(
            "GLOBAL_RULE",
            "global",
            "Observed rule",
            status="observed",
            importance=10,
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

        context = retrieve_context(db_path=self.db_path)
        self.assertEqual(context["global_rules"][0].content, "Validated rule")


if __name__ == "__main__":
    unittest.main()
