"""Phase 4B: save_memory + JARVIS_MEMORY_DECISION_POLICY integration (AST-loaded helpers)."""

from __future__ import annotations

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


class TestSaveMemoryPolicyIntegration(unittest.TestCase):
    def setUp(self):
        self.ns = _load_main_helpers()

    def test_policy_disabled_preserves_legacy_default(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {"JARVIS_MEMORY_WRITE_BACKEND": "legacy"}
        with mock.patch.dict(os.environ, env, clear=False):
            ok, err = self.ns["_execute_save_memory"]("notes", "k", "some real content here")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        update_memory.assert_called_once()

    def test_policy_enabled_blocks_low_signal(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "true",
            "JARVIS_MEMORY_WRITE_BACKEND": "legacy",
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            importlib, "import_module"
        ) as import_module:
            ok, err = self.ns["_execute_save_memory"]("preferences", "k", "ok")
        self.assertFalse(ok)
        self.assertEqual(err, "skipped:low_signal")
        update_memory.assert_not_called()
        import_module.assert_not_called()

    def test_policy_enabled_blocks_temporary_state(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "1",
            "JARVIS_MEMORY_WRITE_BACKEND": "legacy",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            ok, err = self.ns["_execute_save_memory"](
                "projects",
                "mood",
                "hoje estou cansado demais para gravar isto",
            )
        self.assertFalse(ok)
        self.assertEqual(err, "skipped:temporary_state")
        update_memory.assert_not_called()

    def test_policy_enabled_blocks_sensitive_content(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        secret = "api_key=sk-THIS_IS_FAKE_BUT_SHOULD_BLOCK_1234567890"
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "yes",
            "JARVIS_MEMORY_WRITE_BACKEND": "legacy",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            ok, err = self.ns["_execute_save_memory"]("preferences", "k", secret)
        self.assertFalse(ok)
        self.assertEqual(err, "skipped:sensitive_content")
        self.assertNotIn("sk-", err)
        self.assertNotIn("THIS_IS_FAKE", err)
        update_memory.assert_not_called()

    def test_policy_enabled_allows_preference_legacy_backend(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "true",
            "JARVIS_MEMORY_WRITE_BACKEND": "legacy",
        }
        body = "prefiro respostas em português para revisões técnicas"
        with mock.patch.dict(os.environ, env, clear=False):
            ok, err = self.ns["_execute_save_memory"]("preferences", "lang", body)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        update_memory.assert_called_once()

    def test_policy_enabled_allows_project_sqlite_backend(self):
        from memory_engine.retriever import search_memories

        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "pol.db")
            log_path = str(Path(td) / "pol.jsonl")
            marker = "Policy sqlite roundtrip marker único"
            env = {
                "JARVIS_MEMORY_DECISION_POLICY": "true",
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
            }
            with mock.patch.dict(os.environ, env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("projects", "info", marker)
            self.assertTrue(ok, err)
            self.assertEqual(err, "")
            update_memory.assert_not_called()
            rows = search_memories(query=marker, db_path=db_path, limit=10)
            self.assertGreaterEqual(len(rows), 1)

    def test_policy_enabled_skips_requires_review_by_default(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "true",
            "JARVIS_MEMORY_WRITE_BACKEND": "legacy",
        }
        body = "Prefiro ser chamado de Alex no dia a dia do projeto Jarvis"
        with mock.patch.dict(os.environ, env, clear=False):
            ok, err = self.ns["_execute_save_memory"]("identity", "display", body)
        self.assertFalse(ok)
        self.assertEqual(err, "skipped:requires_review")
        update_memory.assert_not_called()

    def test_policy_enabled_allows_review_when_flag_enabled(self):
        from memory_engine.retriever import search_memories

        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "id.db")
            log_path = str(Path(td) / "id.jsonl")
            marker = "identity review save sqlite test phrase"
            env = {
                "JARVIS_MEMORY_DECISION_POLICY": "true",
                "JARVIS_MEMORY_ALLOW_REVIEW_SAVE": "true",
                "JARVIS_MEMORY_WRITE_BACKEND": "sqlite",
                "JARVIS_MEMORY_DB": db_path,
                "JARVIS_MEMORY_EVENT_LOG": log_path,
            }
            with mock.patch.dict(os.environ, env, clear=False):
                ok, err = self.ns["_execute_save_memory"]("identity", "nick", marker)
            self.assertTrue(ok, err)
            self.assertEqual(err, "")
            update_memory.assert_not_called()
            rows = search_memories(query=marker, db_path=db_path, limit=10)
            self.assertGreaterEqual(len(rows), 1)

    def test_policy_off_does_not_call_decide_memory_save(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        with mock.patch.dict(os.environ, {"JARVIS_MEMORY_WRITE_BACKEND": "legacy"}, clear=False):
            with mock.patch("memory_engine.decision_policy.decide_memory_save") as decide:
                ok, err = self.ns["_execute_save_memory"](
                    "preferences",
                    "k",
                    "prefiro respostas curtas e objetivas",
                )
        self.assertTrue(ok)
        decide.assert_not_called()
        update_memory.assert_called_once()

    def test_invalid_backend_still_errors_even_with_policy(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "true",
            "JARVIS_MEMORY_WRITE_BACKEND": "banana",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("memory_engine.decision_policy.decide_memory_save") as decide:
                ok, err = self.ns["_execute_save_memory"]("notes", "k", "conteúdo técnico com sqlite e detalhes")
        self.assertFalse(ok)
        self.assertIn("Invalid JARVIS_MEMORY_WRITE_BACKEND", err)
        decide.assert_not_called()
        update_memory.assert_not_called()

    def test_policy_false_string_preserves_legacy_path(self):
        update_memory = mock.Mock()
        self.ns["update_memory"] = update_memory
        env = {
            "JARVIS_MEMORY_DECISION_POLICY": "false",
            "JARVIS_MEMORY_WRITE_BACKEND": "legacy",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("memory_engine.decision_policy.decide_memory_save") as decide:
                ok, err = self.ns["_execute_save_memory"]("notes", "k", "ok")
        decide.assert_not_called()
        self.assertTrue(ok)
        update_memory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
