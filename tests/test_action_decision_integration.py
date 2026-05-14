import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Import the helpers from main. 
# We patch modules that might have side effects on import if necessary.
# In this environment, we assume dependencies are present.

class TestActionDecisionIntegration(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Ensure we can import main
        sys.path.append(os.getcwd())

    def setUp(self):
        # Save original environ
        self._orig_env = os.environ.copy()
        if "JARVIS_ACTION_DECISION_GATE" in os.environ:
            del os.environ["JARVIS_ACTION_DECISION_GATE"]

    def tearDown(self):
        # Restore original environ
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_gate_off_preserves_flow(self):
        from main import _apply_action_decision_gate
        with patch("core.action_decision_policy.decide_action_request") as mock_decide:
            allowed, msg = _apply_action_decision_gate("any text")
            self.assertTrue(allowed)
            self.assertIsNone(msg)
            mock_decide.assert_not_called()

    def test_gate_false_preserves_flow(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "false"
        with patch("core.action_decision_policy.decide_action_request") as mock_decide:
            allowed, msg = _apply_action_decision_gate("any text")
            self.assertTrue(allowed)
            self.assertIsNone(msg)
            mock_decide.assert_not_called()

    def test_gate_on_chat_allows(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        # Real call to policy (smoke test)
        allowed, msg = _apply_action_decision_gate("Qual é o sentido da vida?")
        self.assertTrue(allowed)
        self.assertIsNone(msg)

    def test_gate_on_memory_save_allows(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        allowed, msg = _apply_action_decision_gate("salve na memória: gosto de café")
        self.assertTrue(allowed)
        self.assertIsNone(msg)

    def test_gate_on_local_action_requires_confirmation(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        allowed, msg = _apply_action_decision_gate("abra o bloco de notas")
        self.assertFalse(allowed)
        self.assertIn("confirm explicitly", msg)
        self.assertIn("local_action", msg)

    def test_gate_on_file_write_requires_confirmation(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        allowed, msg = _apply_action_decision_gate("crie um arquivo texto.txt")
        self.assertFalse(allowed)
        self.assertIn("confirm explicitly", msg)
        self.assertIn("file_write", msg)

    def test_gate_on_file_delete_denies(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        # "apague todos" is a pattern
        allowed, msg = _apply_action_decision_gate("apague todos os arquivos")
        self.assertFalse(allowed)
        self.assertIn("high risk", msg)
        self.assertIn("file_delete", msg)

    def test_gate_on_destructive_command_denies(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        allowed, msg = _apply_action_decision_gate("execute rm -rf /")
        self.assertFalse(allowed)
        self.assertIn("high risk", msg)
        self.assertIn("system_command", msg)

    def test_gate_on_unknown_requires_confirmation(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        allowed, msg = _apply_action_decision_gate("quero que você faça algo estranho agora")
        self.assertFalse(allowed)
        self.assertIn("confirm explicitly", msg)
        self.assertIn("unknown", msg)

    def test_gate_messages_do_not_include_sensitive_content(self):
        from main import _apply_action_decision_gate
        os.environ["JARVIS_ACTION_DECISION_GATE"] = "true"
        # "password = secret" triggers pattern 11 in privacy_guard
        sensitive_text = "salve na memória: password = secret123"
        allowed, msg = _apply_action_decision_gate(sensitive_text)
        self.assertFalse(allowed)
        self.assertNotIn("secret123", msg)
        self.assertIn("high risk", msg)

    def test_no_actions_or_subprocess_imported_in_gate(self):
        from main import _apply_action_decision_gate
        import inspect
        source = inspect.getsource(_apply_action_decision_gate)
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("from actions", source)
        self.assertNotIn("import actions", source)

if __name__ == "__main__":
    unittest.main()
