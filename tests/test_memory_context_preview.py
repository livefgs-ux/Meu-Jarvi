import ast
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from memory_engine.database import init_db
from memory_engine.writer import create_memory

from tools.memory_context_preview import main


DEFAULT_DB = Path("data") / "jarvis_memory.db"
DEFAULT_JSONL = Path("data") / "raw_events.jsonl"


def _sig(path: Path):
    if not path.exists():
        return None
    st = path.stat()
    return st.st_size, st.st_mtime_ns


class MemoryContextPreviewTests(unittest.TestCase):
    def setUp(self):
        self.runtime_db_sig = _sig(DEFAULT_DB)
        self.runtime_jsonl_sig = _sig(DEFAULT_JSONL)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        self.events = self.root / "events.jsonl"
        init_db(self.db)

    def tearDown(self):
        self.assertEqual(_sig(DEFAULT_DB), self.runtime_db_sig)
        self.assertEqual(_sig(DEFAULT_JSONL), self.runtime_jsonl_sig)
        self.tmp.cleanup()

    def run_preview(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def seed(self, **kwargs):
        return create_memory(db_path=self.db, event_log_path=self.events, **kwargs)

    def test_preview_works_with_explicit_temp_db(self):
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="Rule A", status="validated")
        before_db = _sig(self.db)
        before_events = _sig(self.events)

        code, out, err = self.run_preview(["--db", str(self.db)])
        self.assertEqual(code, 0, err)
        self.assertIn("[READ-ONLY MEMORY CONTEXT]", out)
        self.assertIn("Rule A", out)
        self.assertEqual(_sig(self.db), before_db)
        self.assertEqual(_sig(self.events), before_events)

    def test_preview_respects_max_chars(self):
        self.seed(memory_type="GLOBAL_RULE", scope="global", content="X" * 5000, status="validated")
        code, out, err = self.run_preview(["--db", str(self.db), "--max-chars", "600"])
        self.assertEqual(code, 0, err)
        self.assertIn("[/READ-ONLY MEMORY CONTEXT]", out)
        self.assertLessEqual(len(out), 650)

    def test_preview_missing_db_exits_safely(self):
        missing = self.root / "missing.db"
        code, out, err = self.run_preview(["--db", str(missing)])
        self.assertEqual(code, 2)
        self.assertIn("unavailable", err.lower())
        self.assertFalse(missing.exists())

    def test_preview_does_not_import_forbidden_runtime_modules(self):
        path = Path("tools") / "memory_context_preview.py"
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

    def test_preview_does_not_call_writer_functions(self):
        path = Path("tools") / "memory_context_preview.py"
        text = path.read_text(encoding="utf-8")
        for banned in ("create_memory(", "update_memory_status(", "archive_memory("):
            self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()

