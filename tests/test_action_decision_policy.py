"""Tests for core.action_decision_policy (Phase 5A)."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.action_decision_policy import decide_action_request


class TestActionDecisionPolicy(unittest.TestCase):
    def test_empty_input_answer_only(self):
        for raw in ("", "   ", "\t\n"):
            d = decide_action_request(raw)
            self.assertEqual(d.intent, "unknown")
            self.assertEqual(d.risk, "low")
            self.assertEqual(d.action, "answer_only")
            self.assertEqual(d.reason, "empty_input")
            self.assertFalse(d.requires_confirmation)
            self.assertEqual(d.normalized_text, "")

    def test_chat_question_answer_only(self):
        d = decide_action_request("Qual é a capital da França?")
        self.assertEqual(d.intent, "chat")
        self.assertEqual(d.action, "answer_only")
        self.assertEqual(d.risk, "low")
        self.assertFalse(d.requires_confirmation)

        d2 = decide_action_request("explique o que é SQLite")
        self.assertEqual(d2.intent, "chat")
        self.assertEqual(d2.action, "answer_only")

    def test_memory_save_allowed(self):
        d = decide_action_request("salve na memória: prefiro respostas em português")
        self.assertEqual(d.intent, "memory_save")
        self.assertEqual(d.risk, "low")
        self.assertEqual(d.action, "allow")
        self.assertFalse(d.requires_confirmation)

        d2 = decide_action_request("lembre que meu projeto se chama Meu Jarvis")
        self.assertEqual(d2.intent, "memory_save")
        self.assertEqual(d2.action, "allow")

    def test_sensitive_memory_denied(self):
        secret = "salve na memória: api_key=sk-FAKE12345678901234567890"
        d = decide_action_request(secret)
        self.assertEqual(d.intent, "memory_save")
        self.assertEqual(d.risk, "high")
        self.assertEqual(d.action, "deny")
        self.assertEqual(d.reason, "sensitive_memory")
        self.assertEqual(d.normalized_text, "")

    def test_local_action_requires_confirmation(self):
        d = decide_action_request("abra o chrome")
        self.assertEqual(d.intent, "local_action")
        self.assertEqual(d.risk, "medium")
        self.assertEqual(d.action, "confirm")
        self.assertTrue(d.requires_confirmation)

        d2 = decide_action_request("tire um print da tela")
        self.assertEqual(d2.intent, "local_action")
        self.assertTrue(d2.requires_confirmation)

    def test_file_read_requires_confirmation(self):
        d = decide_action_request("leia o arquivo README.md")
        self.assertEqual(d.intent, "file_read")
        self.assertEqual(d.action, "confirm")
        self.assertTrue(d.requires_confirmation)

        d2 = decide_action_request("abra o arquivo config.toml")
        self.assertEqual(d2.intent, "file_read")

    def test_file_write_requires_confirmation(self):
        d = decide_action_request("crie um arquivo teste.txt")
        self.assertEqual(d.intent, "file_write")
        self.assertEqual(d.action, "confirm")
        self.assertTrue(d.requires_confirmation)

        d2 = decide_action_request("edite o arquivo main.py")
        self.assertEqual(d2.intent, "file_write")

    def test_file_delete_denied(self):
        d = decide_action_request("apague a pasta documentos")
        self.assertEqual(d.intent, "file_delete")
        self.assertEqual(d.risk, "high")
        self.assertEqual(d.action, "deny")
        self.assertTrue(d.requires_confirmation)

    def test_system_command_destructive_denied(self):
        d = decide_action_request("execute rm -rf /tmp")
        self.assertEqual(d.intent, "system_command")
        self.assertEqual(d.action, "deny")
        self.assertEqual(d.risk, "high")

    def test_system_command_non_destructive_confirm(self):
        d = decide_action_request("rode powershell")
        self.assertEqual(d.intent, "system_command")
        self.assertEqual(d.action, "confirm")
        self.assertTrue(d.requires_confirmation)

        d2 = decide_action_request("execute git push")
        self.assertEqual(d2.intent, "system_command")
        self.assertEqual(d2.action, "confirm")

    def test_unknown_requires_confirmation(self):
        d = decide_action_request("zzzqqq mmm nnn ooo ppp qqq rrr sss")
        self.assertEqual(d.intent, "unknown")
        self.assertEqual(d.risk, "medium")
        self.assertEqual(d.action, "confirm")
        self.assertTrue(d.requires_confirmation)

    def test_normalized_text_collapses_spaces(self):
        d = decide_action_request("  Olá    mundo   genial  ")
        self.assertEqual(d.normalized_text, "olá mundo genial")

    def test_policy_uses_privacy_guard(self):
        with mock.patch("core.action_decision_policy.check_content_safe") as chk:
            chk.return_value = mock.Mock(allowed=True, reason="")
            decide_action_request("salve na memória: gosto de logs claros")
            chk.assert_called()

    def test_policy_does_not_import_subprocess_or_actions(self):
        root = Path(__file__).resolve().parents[1]
        src = (root / "core" / "action_decision_policy.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    base = (a.name or "").split(".")[0]
                    if base in {"subprocess", "actions", "agent", "brain"}:
                        bad.add(a.name or "")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] in {"subprocess", "actions", "agent", "brain"}:
                    bad.add(mod)
        self.assertEqual(bad, set(), bad)
        self.assertNotIn("subprocess", src)

    def test_policy_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as td:
            before = os.listdir(td)
            for _ in range(8):
                decide_action_request("rode powershell com parâmetros diversos")
            self.assertEqual(os.listdir(td), before)


if __name__ == "__main__":
    unittest.main()
