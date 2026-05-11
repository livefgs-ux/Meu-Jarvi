import ast
import os
import tempfile
import time
import unittest
from pathlib import Path

from memory_engine.database import init_db
from memory_engine.runtime_context import (
    build_readonly_memory_context,
    build_readonly_memory_context_from_env,
)
from memory_engine.writer import create_memory


def _sig(path: Path) -> tuple[int, float] | None:
    if not path.exists():
        return None
    st = path.stat()
    return (st.st_size, st.st_mtime)


def _seed_minimal_db(db_path: Path, *, project: str = "Meu-Jarvi") -> None:
    init_db(str(db_path))
    event_path = db_path.with_suffix(".jsonl")
    create_memory(
        db_path=str(db_path),
        event_log_path=str(event_path),
        memory_type="GLOBAL_RULE",
        scope="global",
        project=None,
        content="Do not mix global rules with project-specific context.",
        status="validated",
        importance=10,
        confidence=1.0,
        source="test",
    )
    create_memory(
        db_path=str(db_path),
        event_log_path=str(event_path),
        memory_type="PROJECT_CONTEXT",
        scope=f"project:{project}",
        project=project,
        content="Project context for read-only test.",
        status="confirmed",
        importance=8,
        confidence=0.9,
        source="test",
    )


class TestRuntimeContext(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.real_db = self.repo_root / "data" / "jarvis_memory.db"
        self.real_events = self.repo_root / "data" / "raw_events.jsonl"
        self.real_db_sig_before = _sig(self.real_db)
        self.real_events_sig_before = _sig(self.real_events)

    def tearDown(self):
        self.assertEqual(_sig(self.real_db), self.real_db_sig_before)
        self.assertEqual(_sig(self.real_events), self.real_events_sig_before)

    def test_default_disabled_returns_empty(self):
        out = build_readonly_memory_context()
        self.assertEqual(out, "")

    def test_explicit_enabled_false_returns_empty(self):
        out = build_readonly_memory_context(enabled=False, project="Meu-Jarvi")
        self.assertEqual(out, "")

    def test_env_disabled_or_missing_returns_empty(self):
        out = build_readonly_memory_context_from_env(environ={})
        self.assertEqual(out, "")
        out = build_readonly_memory_context_from_env(environ={"JARVIS_READONLY_MEMORY": "0"})
        self.assertEqual(out, "")

    def test_env_enabled_but_no_project_returns_empty(self):
        out = build_readonly_memory_context_from_env(environ={"JARVIS_READONLY_MEMORY": "1"})
        self.assertEqual(out, "")

    def test_env_enabled_with_project_returns_context_from_temp_db(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            db_path = td_path / "mem.db"
            _seed_minimal_db(db_path, project="Meu-Jarvi")

            env = {"JARVIS_READONLY_MEMORY": "true", "JARVIS_MEMORY_PROJECT": "Meu-Jarvi"}
            out = build_readonly_memory_context_from_env(environ=env, db_path=db_path)
            self.assertIn("[READ-ONLY MEMORY CONTEXT]", out)
            self.assertIn("[/READ-ONLY MEMORY CONTEXT]", out)
            self.assertIn("Global Rules:", out)

    def test_missing_db_returns_empty_and_does_not_create(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missing.db"
            self.assertFalse(db_path.exists())
            out = build_readonly_memory_context(enabled=True, project="Meu-Jarvi", db_path=db_path)
            self.assertEqual(out, "")
            self.assertFalse(db_path.exists())

    def test_invalid_env_numeric_values_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "mem.db"
            _seed_minimal_db(db_path, project="Meu-Jarvi")

            env = {
                "JARVIS_READONLY_MEMORY": "1",
                "JARVIS_MEMORY_PROJECT": "Meu-Jarvi",
                "JARVIS_MEMORY_MAX_CHARS": "not-an-int",
                "JARVIS_MEMORY_LIMIT": "-5",
            }
            out = build_readonly_memory_context_from_env(environ=env, db_path=db_path)
            self.assertIn("[READ-ONLY MEMORY CONTEXT]", out)

    def test_max_chars_respected(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "mem.db"
            init_db(str(db_path))
            event_path = Path(td) / "events.jsonl"
            create_memory(
                db_path=str(db_path),
                event_log_path=str(event_path),
                memory_type="GLOBAL_RULE",
                scope="global",
                project=None,
                content="X" * 2000,
                status="validated",
                importance=10,
                confidence=1.0,
                source="test",
            )
            out = build_readonly_memory_context(enabled=True, project="Meu-Jarvi", db_path=db_path, max_chars=200)
            self.assertLessEqual(len(out), 200)

    def test_db_signature_unchanged_after_wrapper_call(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "mem.db"
            _seed_minimal_db(db_path, project="Meu-Jarvi")
            before = _sig(db_path)
            events_before = _sig(db_path.with_suffix(".jsonl"))
            time.sleep(0.02)
            _ = build_readonly_memory_context(enabled=True, project="Meu-Jarvi", db_path=db_path)
            after = _sig(db_path)
            events_after = _sig(db_path.with_suffix(".jsonl"))
            self.assertEqual(before, after)
            self.assertEqual(events_before, events_after)

    def test_jsonl_signature_unchanged_if_exists(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            jsonl = td_path / "events.jsonl"
            jsonl.write_text('{"event":"seed"}\n', encoding="utf-8")
            before = _sig(jsonl)
            time.sleep(0.02)
            _ = build_readonly_memory_context(enabled=True, project="Meu-Jarvi", db_path=td_path / "missing.db")
            after = _sig(jsonl)
            self.assertEqual(before, after)

    def test_no_forbidden_imports_in_runtime_context_module(self):
        src_path = self.repo_root / "memory_engine" / "runtime_context.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))

        banned = {
            "main",
            "ui",
            "actions",
            "agent",
            "google",
            "google.genai",
            "google.generativeai",
            "playwright",
            "pyautogui",
            "graphify",
            "obsidian",
            "tools.memory_cli",
            "tools.memory_context_preview",
            "memory_engine.writer",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    self.assertNotIn(name, banned)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn(mod, banned)

    def test_writer_functions_not_called(self):
        # runtime_context must not call writer; we also ensure "create_memory(" isn't referenced here.
        src_path = self.repo_root / "memory_engine" / "runtime_context.py"
        text = src_path.read_text(encoding="utf-8")
        self.assertNotIn("create_memory(", text)
        self.assertNotIn("update_memory_status(", text)
        self.assertNotIn("archive_memory(", text)

    def test_real_runtime_signatures_unchanged(self):
        # setUp/tearDown already enforce this; keep explicit assertion for the contract.
        self.assertEqual(_sig(self.real_db), self.real_db_sig_before)
        self.assertEqual(_sig(self.real_events), self.real_events_sig_before)


if __name__ == "__main__":
    unittest.main()
