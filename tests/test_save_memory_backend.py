import ast
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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


class TestSaveMemoryBackend(unittest.TestCase):
    def setUp(self):
        self.ns = _load_main_helpers()

    def test_save_memory_default_uses_legacy_backend(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        with mock.patch.dict(os.environ, {"JARVIS_MEMORY_WRITE_BACKEND": ""}, clear=False):
            ok, err = self.ns["_execute_save_memory"]("notes", "k", "v")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        update_memory.assert_called_once()

    def test_save_memory_legacy_backend_uses_update_memory(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        with mock.patch.dict(os.environ, {"JARVIS_MEMORY_WRITE_BACKEND": "legacy"}, clear=False):
            ok, err = self.ns["_execute_save_memory"]("notes", "k", "v")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        update_memory.assert_called_once()

    def test_save_memory_sqlite_backend_uses_create_memory_and_is_retrievable(self):
        from memory_engine.retriever import search_memories

        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "mem.db")
            log_path = str(Path(td) / "events.jsonl")
            with mock.patch.dict(
                os.environ,
                {
                    "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                    "JARVIS_MEMORY_DB": db_path,
                    "JARVIS_MEMORY_EVENT_LOG": log_path,
                },
                clear=False,
            ):
                ok, err = self.ns["_execute_save_memory"]("preferences", "favorite_language", "Portuguese")
            self.assertTrue(ok)
            self.assertEqual(err, "")

            self.assertTrue(Path(db_path).exists())
            self.assertTrue(Path(log_path).exists())

            rows = search_memories(query="Portuguese", db_path=db_path, limit=10)
            self.assertGreaterEqual(len(rows), 1)

    def test_sqlite_backend_requires_memory_db_env(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory

        with tempfile.TemporaryDirectory() as td:
            missing_db = str(Path(td) / "mem.db")
            log_path = str(Path(td) / "events.jsonl")
            with mock.patch.dict(
                os.environ,
                {
                    "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                    "JARVIS_MEMORY_EVENT_LOG": log_path,
                },
                clear=False,
            ), mock.patch.object(importlib, "import_module") as import_module:
                ok, err = self.ns["_execute_save_memory"]("preferences", "k", "v")
            self.assertFalse(ok)
            self.assertIn("JARVIS_MEMORY_DB", err)
            update_memory.assert_not_called()
            import_module.assert_not_called()
            self.assertFalse(Path(missing_db).exists())
            self.assertFalse(Path(log_path).exists())

    def test_sqlite_backend_requires_event_log_env(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory

        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "mem.db")
            missing_log = str(Path(td) / "events.jsonl")
            with mock.patch.dict(
                os.environ,
                {
                    "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                    "JARVIS_MEMORY_DB": db_path,
                },
                clear=False,
            ), mock.patch.object(importlib, "import_module") as import_module:
                ok, err = self.ns["_execute_save_memory"]("preferences", "k", "v")
            self.assertFalse(ok)
            self.assertIn("JARVIS_MEMORY_EVENT_LOG", err)
            update_memory.assert_not_called()
            import_module.assert_not_called()
            self.assertFalse(Path(db_path).exists())
            self.assertFalse(Path(missing_log).exists())

    def test_save_memory_invalid_backend_returns_error_and_writes_nowhere(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "mem.db")
            log_path = str(Path(td) / "events.jsonl")
            with mock.patch.dict(
                os.environ,
                {
                    "JARVIS_MEMORY_WRITE_BACKEND": "banana",
                    "JARVIS_MEMORY_DB": db_path,
                    "JARVIS_MEMORY_EVENT_LOG": log_path,
                },
                clear=False,
            ):
                ok, err = self.ns["_execute_save_memory"]("notes", "k", "v")
            self.assertFalse(ok)
            self.assertIn("Invalid JARVIS_MEMORY_WRITE_BACKEND", err)
            update_memory.assert_not_called()
            self.assertFalse(Path(db_path).exists())
            self.assertFalse(Path(log_path).exists())

    def test_save_memory_sqlite_blocks_secret_and_does_not_echo_value(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "mem.db")
            log_path = str(Path(td) / "events.jsonl")
            secret_value = "api_key=sk-THIS_IS_FAKE_BUT_SHOULD_BLOCK_1234567890"
            with mock.patch.dict(
                os.environ,
                {
                    "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                    "JARVIS_MEMORY_DB": db_path,
                    "JARVIS_MEMORY_EVENT_LOG": log_path,
                },
                clear=False,
            ):
                ok, err = self.ns["_execute_save_memory"]("notes", "k", secret_value)
            self.assertFalse(ok)
            self.assertIn("secret", err.lower())
            self.assertNotIn(secret_value, err)

    def test_save_memory_sqlite_category_mapping_preferences(self):
        mapped = self.ns["_map_save_memory_sqlite"]("preferences", "k", "v")
        self.assertEqual(mapped["memory_type"], "PREFERENCE")
        self.assertEqual(mapped["scope"], "global")
        self.assertIsNone(mapped["project"])

    def test_save_memory_sqlite_category_mapping_projects(self):
        mapped = self.ns["_map_save_memory_sqlite"]("projects", "k", "v")
        self.assertEqual(mapped["memory_type"], "PROJECT_CONTEXT")
        self.assertEqual(mapped["scope"], "project:meu-jarvis")
        self.assertEqual(mapped["project"], "meu-jarvis")

    def test_save_memory_sqlite_unknown_category_is_candidate_idea(self):
        mapped = self.ns["_map_save_memory_sqlite"]("unknown_cat", "k", "v")
        self.assertEqual(mapped["memory_type"], "IDEA")
        self.assertEqual(mapped["scope"], "project:meu-jarvis")
        self.assertEqual(mapped["project"], "meu-jarvis")
        self.assertEqual(mapped["status"], "candidate")
