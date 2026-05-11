import ast
import tempfile
import unittest
from pathlib import Path

from memory_engine.database import init_db
from memory_engine.writer import create_memory


def _sig(path: Path):
    if not path.exists():
        return None
    st = path.stat()
    return st.st_size, st.st_mtime_ns


class RuntimeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        self.events = self.root / "events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_db_returns_unavailable_and_does_not_create(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        missing = self.root / "missing.db"
        ctx = load_runtime_memory_context(db_path=missing)
        self.assertFalse(ctx["available"])
        self.assertEqual(ctx["global_rules"], [])
        self.assertFalse(missing.exists())

    def seed(self, **kwargs):
        init_db(self.db)
        return create_memory(db_path=self.db, event_log_path=self.events, **kwargs)

    def test_reads_global_rules(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Rule A", status="validated")
        ctx = load_runtime_memory_context(db_path=self.db)
        self.assertTrue(ctx["available"])
        self.assertEqual(len(ctx["global_rules"]), 1)
        self.assertEqual(ctx["global_rules"][0]["content"], "Rule A")

    def test_reads_project_context_and_separates_types(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        self.seed(
            memory_type="PROJECT_CONTEXT",
            scope="project:Meu-Jarvi",
            project="Meu-Jarvi",
            content="Project context",
            status="confirmed",
        )
        self.seed(
            memory_type="TECHNICAL_STATE",
            scope="project:Meu-Jarvi",
            project="Meu-Jarvi",
            content="Tech state",
            status="observed",
        )
        self.seed(
            memory_type="WARNING",
            scope="project:Meu-Jarvi",
            project="Meu-Jarvi",
            content="Warning",
            status="validated",
        )

        before = _sig(self.db)
        ctx = load_runtime_memory_context(project="Meu-Jarvi", db_path=self.db)
        after = _sig(self.db)
        self.assertEqual(before, after)

        self.assertEqual(len(ctx["project_context"]), 1)
        self.assertEqual(ctx["project_context"][0]["memory_type"], "PROJECT_CONTEXT")
        self.assertEqual(len(ctx["technical_state"]), 1)
        self.assertEqual(ctx["technical_state"][0]["memory_type"], "TECHNICAL_STATE")
        self.assertEqual(len(ctx["warnings"]), 1)
        self.assertEqual(ctx["warnings"][0]["memory_type"], "WARNING")

    def test_excludes_archived_deprecated_conflicted(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Keep", status="validated")
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Archive", status="archived")
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Dep", status="deprecated")
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Conf", status="conflicted")

        ctx = load_runtime_memory_context(db_path=self.db)
        self.assertEqual([r["content"] for r in ctx["global_rules"]], ["Keep"])

    def test_status_priority_and_importance_sorting(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        # Same type/scope, different statuses.
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Observed", status="observed", importance=10)
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Validated", status="validated", importance=1)
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Confirmed", status="confirmed", importance=9)
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Candidate", status="candidate", importance=10)

        ctx = load_runtime_memory_context(db_path=self.db, limit=10)
        ordered = [r["content"] for r in ctx["global_rules"]]
        self.assertEqual(ordered[0], "Validated")
        self.assertEqual(ordered[1], "Confirmed")
        self.assertEqual(ordered[2], "Observed")
        self.assertEqual(ordered[3], "Candidate")

        # Within same status, importance desc.
        self.seed(memory_type="WARNING", scope="project:Meu-Jarvi", project="Meu-Jarvi", content="Low", status="validated", importance=1)
        self.seed(memory_type="WARNING", scope="project:Meu-Jarvi", project="Meu-Jarvi", content="High", status="validated", importance=9)
        ctx2 = load_runtime_memory_context(project="Meu-Jarvi", db_path=self.db, limit=10)
        warnings = [r["content"] for r in ctx2["warnings"]]
        self.assertEqual(warnings[0], "High")
        self.assertEqual(warnings[1], "Low")

    def test_keyword_query_returns_bounded_matches(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        for i in range(20):
            # Use confirmed to avoid v0 conflict resolver auto-marking as conflicted for similar content.
            self.seed(memory_type="IDEA", scope="global", content=f"keyword {i}", status="confirmed")
        ctx = load_runtime_memory_context(query="keyword", db_path=self.db, limit=5)
        self.assertEqual(len(ctx["keyword_matches"]["global"]), 5)

    def test_format_for_prompt_is_bounded(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context, format_memory_context_for_prompt

        self.seed(memory_type="GLOBAL_RULE", scope="global", content="A" * 1000, status="validated")
        ctx = load_runtime_memory_context(db_path=self.db)
        out = format_memory_context_for_prompt(ctx, max_chars=400)
        self.assertIn("[READ-ONLY MEMORY CONTEXT]", out)
        self.assertIn("[/READ-ONLY MEMORY CONTEXT]", out)
        self.assertLessEqual(len(out), 400 + 20)  # allow tiny slack for newline

    def test_adapter_does_not_create_or_modify_event_jsonl(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Rule", status="validated")
        before = _sig(self.events)
        ctx = load_runtime_memory_context(db_path=self.db)
        self.assertTrue(ctx["available"])
        after = _sig(self.events)
        self.assertEqual(before, after)

    def test_adapter_does_not_import_forbidden_modules(self):
        path = Path("memory_engine") / "runtime_adapter.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        forbidden = {
            "main",
            "ui",
            "actions",
            "agent",
            "google.genai",
            "google.generativeai",
            "playwright",
            "pyautogui",
            "graphify",
            "obsidian",
            "memory_engine.writer",
        }
        for name in forbidden:
            self.assertFalse(any(i == name or i.startswith(f"{name}.") for i in imported), name)

    def test_adapter_does_not_call_writer_functions(self):
        path = Path("memory_engine") / "runtime_adapter.py"
        text = path.read_text(encoding="utf-8")
        for banned in ("create_memory(", "update_memory_status(", "archive_memory("):
            self.assertNotIn(banned, text)

    def test_real_runtime_db_log_signatures_unchanged_if_present(self):
        from memory_engine.runtime_adapter import load_runtime_memory_context

        real_db = Path("data") / "jarvis_memory.db"
        real_events = Path("data") / "raw_events.jsonl"
        sig_db_before = _sig(real_db)
        sig_ev_before = _sig(real_events)

        # Read-only attempt should not modify anything if files exist; if missing, signature stays None.
        load_runtime_memory_context(db_path=real_db)

        self.assertEqual(_sig(real_db), sig_db_before)
        self.assertEqual(_sig(real_events), sig_ev_before)


if __name__ == "__main__":
    unittest.main()
