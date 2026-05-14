"""Phase 3B: end-to-end validation — sqlite save_memory → read-only runtime context.

Does not import or run main.py; reuses the same AST/exec helper extraction as test_save_memory_backend.
"""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_engine.retriever import search_memories
from memory_engine.runtime_context import build_readonly_memory_context_from_env


def _load_main_helpers():
    src = Path("main.py").read_text(encoding="utf-8")
    mod = ast.parse(src)
    helper_names = {
        "_get_memory_write_backend",
        "_save_memory_legacy",
        "_map_save_memory_sqlite",
        "_save_memory_sqlite",
        "_execute_save_memory",
    }
    body = [n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name in helper_names]
    ns: dict = {"os": os}
    code = compile(ast.Module(body=body, type_ignores=[]), filename="main.py<helpers>", mode="exec")
    exec(code, ns, ns)
    missing = helper_names - set(ns.keys())
    if missing:
        raise AssertionError(f"Missing helpers in main.py: {sorted(missing)}")
    return ns


def _sig(path: Path) -> tuple[int, float] | None:
    if not path.exists():
        return None
    st = path.stat()
    return (st.st_size, st.st_mtime)


class TestRuntimeMemoryRoundtrip(unittest.TestCase):
    """SQLite save_memory (extracted helpers) → search_memories → build_readonly_memory_context_from_env."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.real_db = cls.repo_root / "data" / "jarvis_memory.db"
        cls.real_events = cls.repo_root / "data" / "raw_events.jsonl"
        cls.api_keys = cls.repo_root / "config" / "api_keys.json"
        cls.long_term = cls.repo_root / "memory" / "long_term.json"

    def setUp(self):
        self.ns = _load_main_helpers()
        self._snap_real_db = _sig(self.real_db)
        self._snap_real_events = _sig(self.real_events)
        self._snap_api_keys = _sig(self.api_keys)
        self._snap_long_term_existed = self.long_term.exists()
        self._snap_long_term = _sig(self.long_term) if self.long_term.exists() else None

    def tearDown(self):
        self.assertEqual(
            _sig(self.real_db),
            self._snap_real_db,
            "data/jarvis_memory.db must not change during roundtrip tests",
        )
        self.assertEqual(
            _sig(self.real_events),
            self._snap_real_events,
            "data/raw_events.jsonl must not change during roundtrip tests",
        )
        self.assertEqual(_sig(self.api_keys), self._snap_api_keys, "config/api_keys.json must not change")
        self.assertEqual(self.long_term.exists(), self._snap_long_term_existed, "memory/long_term.json presence must not change")
        if self._snap_long_term is not None:
            self.assertEqual(_sig(self.long_term), self._snap_long_term, "memory/long_term.json must not change if it existed")

    def test_sqlite_save_memory_then_readonly_context_can_read(self):
        safe_phrase = "Runtime memory roundtrip test"
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "runtime_memory.db")
            log_path = str(Path(td) / "runtime_events.jsonl")
            write_env = {
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
            }
            with mock.patch.dict(os.environ, write_env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("projects", "roundtrip_test", safe_phrase)
            self.assertTrue(ok, err)
            self.assertEqual(err, "")

            self.assertTrue(Path(db_path).is_file())
            self.assertTrue(Path(log_path).is_file())

            rows = search_memories(query=safe_phrase, db_path=db_path, limit=10)
            self.assertGreaterEqual(len(rows), 1)

            read_env = {
                "JARVIS_READONLY_MEMORY": "true",
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
                "JARVIS_MEMORY_DB": db_path,
            }
            out = build_readonly_memory_context_from_env(environ=read_env)
            self.assertTrue(out.strip(), "read-only context must be non-empty when enabled")
            self.assertIn("[READ-ONLY MEMORY CONTEXT]", out)
            self.assertIn(safe_phrase, out)

    def test_readonly_context_off_by_default_after_sqlite_write(self):
        safe_phrase = "Opt-in read-only remains off"
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "runtime_memory.db")
            log_path = str(Path(td) / "runtime_events.jsonl")
            write_env = {
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
            }
            with mock.patch.dict(os.environ, write_env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("projects", "opt_in", safe_phrase)
            self.assertTrue(ok, err)

            rows = search_memories(query=safe_phrase, db_path=db_path, limit=5)
            self.assertGreaterEqual(len(rows), 1)

            read_env = {
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
                "JARVIS_MEMORY_DB": db_path,
            }
            out = build_readonly_memory_context_from_env(environ=read_env)
            self.assertEqual(out, "")

    def test_roundtrip_uses_temp_db_not_real_data(self):
        safe_phrase = "Temp DB only roundtrip"
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "runtime_memory.db")
            log_path = str(Path(td) / "runtime_events.jsonl")
            write_env = {
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
            }
            with mock.patch.dict(os.environ, write_env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("projects", "temp_only", safe_phrase)
            self.assertTrue(ok, err)

            read_env = {
                "JARVIS_READONLY_MEMORY": "1",
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
                "JARVIS_MEMORY_DB": db_path,
            }
            out = build_readonly_memory_context_from_env(environ=read_env)
            self.assertIn(safe_phrase, out)

        if not self._snap_long_term_existed:
            self.assertFalse(self.long_term.exists(), "memory/long_term.json must not be created")
        self.assertEqual(_sig(self.real_db), self._snap_real_db)
        self.assertEqual(_sig(self.real_events), self._snap_real_events)

    def test_roundtrip_project_scope(self):
        """projects category maps to project meu-jarvis; readonly env must match for retrieval."""
        marker = "project_scope_roundtrip_marker"
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "runtime_memory.db")
            log_path = str(Path(td) / "runtime_events.jsonl")
            write_env = {
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
            }
            with mock.patch.dict(os.environ, write_env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("projects", "roundtrip_test", marker)
            self.assertTrue(ok, err)

            scoped = search_memories(
                query=marker,
                db_path=db_path,
                memory_type="PROJECT_CONTEXT",
                scope="project:meu-jarvis",
                project="meu-jarvis",
                limit=10,
            )
            self.assertGreaterEqual(len(scoped), 1)

            read_env = {
                "JARVIS_READONLY_MEMORY": "true",
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
                "JARVIS_MEMORY_DB": db_path,
            }
            out = build_readonly_memory_context_from_env(environ=read_env)
            self.assertIn(marker, out)

    def test_roundtrip_blocks_secret_before_read_context(self):
        secret_tail = "THIS_IS_FAKE_BUT_SHOULD_BLOCK_1234567890"
        secret_value = f"api_key=sk-{secret_tail}"
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "runtime_memory.db")
            log_path = str(Path(td) / "runtime_events.jsonl")
            write_env = {
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
            }
            with mock.patch.dict(os.environ, write_env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("projects", "leak_attempt", secret_value)
            self.assertFalse(ok)
            self.assertIn("secret", err.lower())
            self.assertNotIn(secret_value, err)
            self.assertNotIn(secret_tail, err)

            read_env = {
                "JARVIS_READONLY_MEMORY": "true",
                "JARVIS_MEMORY_PROJECT": "meu-jarvis",
                "JARVIS_MEMORY_DB": db_path,
            }
            out = build_readonly_memory_context_from_env(environ=read_env)
            self.assertNotIn(secret_tail, out)
            self.assertNotIn("sk-", out)


if __name__ == "__main__":
    unittest.main()
