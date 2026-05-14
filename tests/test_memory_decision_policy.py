"""Tests for memory_engine.decision_policy (Phase 4A)."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_engine.decision_policy import MemoryDecision, decide_memory_save


class TestMemoryDecisionPolicy(unittest.TestCase):
    def test_empty_content_is_not_saved(self):
        for val in ("", "   ", None):
            d = decide_memory_save(category="notes", key="k", value=val)  # type: ignore[arg-type]
            self.assertIsInstance(d, MemoryDecision)
            self.assertFalse(d.should_save)
            self.assertEqual(d.reason, "empty_content")
            self.assertEqual(d.normalized_content, "")

    def test_low_signal_content_is_not_saved(self):
        for phrase in ("ok", "  SIM ", "Não", "talvez", "haha", "obrigado", "valeu"):
            d = decide_memory_save(category="preferences", key="k", value=phrase)
            self.assertFalse(d.should_save, phrase)
            self.assertEqual(d.reason, "low_signal")

    def test_temporary_state_is_not_saved(self):
        samples = (
            "Hoje estou cansado e não quero gravar isso",
            "Agora estou com sono",
            "Neste momento estou ocupado com outra coisa",
            "Amanhã eu vejo isso",
        )
        for text in samples:
            d = decide_memory_save(category="projects", key="mood", value=text)
            self.assertFalse(d.should_save, text)
            self.assertEqual(d.reason, "temporary_state")

    def test_sensitive_content_is_not_saved(self):
        secret = "api_key=sk-THIS_IS_FAKE_BUT_SHOULD_BLOCK_1234567890"
        d = decide_memory_save(category="preferences", key="k", value=secret)
        self.assertFalse(d.should_save)
        self.assertEqual(d.reason, "sensitive_content")
        self.assertEqual(d.normalized_content, "")
        self.assertNotIn("sk-", d.reason)
        self.assertNotIn("THIS_IS_FAKE", d.reason)

    def test_preferences_are_saved_as_global_preference(self):
        d = decide_memory_save(
            category="preferences",
            key="lang",
            value="prefiro respostas em português",
        )
        self.assertTrue(d.should_save)
        self.assertEqual(d.memory_type, "PREFERENCE")
        self.assertEqual(d.scope, "global")
        self.assertIsNone(d.project)
        self.assertFalse(d.requires_review)
        self.assertGreaterEqual(d.confidence, 0.7)

    def test_project_context_is_saved_as_project_context(self):
        d = decide_memory_save(
            category="projects",
            key="stack",
            value="O Jarvis usa SQLite Memory Engine para persistência local",
        )
        self.assertTrue(d.should_save)
        self.assertEqual(d.memory_type, "PROJECT_CONTEXT")
        self.assertEqual(d.scope, "project:meu-jarvis")
        self.assertEqual(d.project, "meu-jarvis")
        self.assertFalse(d.requires_review)
        self.assertGreaterEqual(d.confidence, 0.7)

    def test_notes_technical_state_is_saved_for_project(self):
        body = "save_memory sqlite exige JARVIS_MEMORY_DB e JARVIS_MEMORY_EVENT_LOG"
        d = decide_memory_save(category="notes", key="env", value=body)
        self.assertTrue(d.should_save)
        self.assertEqual(d.memory_type, "TECHNICAL_STATE")
        self.assertEqual(d.scope, "project:meu-jarvis")
        self.assertEqual(d.project, "meu-jarvis")
        self.assertFalse(d.requires_review)
        self.assertGreaterEqual(d.confidence, 0.7)

    def test_identity_requires_review(self):
        d = decide_memory_save(
            category="identity",
            key="display",
            value="Prefiro ser chamado de Alex no dia a dia do projeto",
        )
        self.assertTrue(d.should_save)
        self.assertTrue(d.requires_review)
        self.assertEqual(d.memory_type, "PREFERENCE")
        self.assertEqual(d.scope, "global")

    def test_relationships_require_review(self):
        d = decide_memory_save(
            category="relationships",
            key="team",
            value="Trabalho de perto com a equipe que mantém o Jarvis neste repositório",
        )
        self.assertTrue(d.should_save)
        self.assertTrue(d.requires_review)
        self.assertEqual(d.memory_type, "PREFERENCE")

    def test_unknown_category_requires_review_or_blocks_low_signal(self):
        low = decide_memory_save(category="unknown_cat", key="k", value="talvez")
        self.assertFalse(low.should_save)
        self.assertEqual(low.reason, "low_signal")

        tech = decide_memory_save(
            category="unknown_cat",
            key="k",
            value="O módulo memory_engine usa SQLite com WAL e migrações incrementais",
        )
        self.assertTrue(tech.should_save)
        self.assertTrue(tech.requires_review)
        self.assertEqual(tech.memory_type, "IDEA")
        self.assertEqual(tech.scope, "project:meu-jarvis")

    def test_normalized_content_collapses_spaces(self):
        d = decide_memory_save(category="preferences", key="tone", value="  gosto   de   respostas   diretas  ")
        self.assertTrue(d.should_save)
        self.assertIn("gosto de respostas diretas", d.normalized_content)
        self.assertNotIn("  ", d.normalized_content)

    def test_decision_policy_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as td:
            before = os.listdir(td)
            for _ in range(12):
                decide_memory_save(
                    category="projects",
                    key="x",
                    value="Texto com sqlite e detalhes técnicos suficientes para passar no filtro",
                )
            self.assertEqual(os.listdir(td), before)

    def test_decision_policy_does_not_import_writer_or_sqlite(self):
        root = Path(__file__).resolve().parents[1]
        src = (root / "memory_engine" / "decision_policy.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = (alias.name or "").split(".")[0].lower()
                    if name in {"sqlite3", "sqlite"}:
                        bad_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").lower()
                if "writer" in mod or mod.startswith("sqlite"):
                    bad_modules.add(node.module or "")
        self.assertEqual(bad_modules, set(), f"Unexpected imports: {bad_modules}")
        self.assertNotIn("sqlite3", src)
        self.assertNotIn("create_memory", src)

    def test_decision_policy_uses_privacy_guard(self):
        with mock.patch("memory_engine.decision_policy.check_content_safe") as chk:
            chk.return_value = mock.Mock(allowed=True, reason="")
            decide_memory_save(category="preferences", key="k", value="prefiro logs verbosos")
            chk.assert_called()
            args, _ = chk.call_args
            self.assertTrue(args[0])

    def test_custom_project_parameter(self):
        d = decide_memory_save(
            category="projects",
            key="k",
            value="O serviço roda no cluster kubernetes interno",
            project="other-proj",
        )
        self.assertTrue(d.should_save)
        self.assertEqual(d.scope, "project:other-proj")
        self.assertEqual(d.project, "other-proj")


if __name__ == "__main__":
    unittest.main()
