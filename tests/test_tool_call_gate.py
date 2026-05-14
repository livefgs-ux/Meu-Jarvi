import unittest
import os
import sys
from unittest.mock import patch, MagicMock

class TestToolCallGate(unittest.TestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()
        if "JARVIS_TOOL_CALL_GATE" in os.environ:
            del os.environ["JARVIS_TOOL_CALL_GATE"]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_tool_gate_off_allows_everything(self):
        from main import _apply_tool_call_gate
        allowed, msg, action = _apply_tool_call_gate("file_controller", {"action": "delete", "path": "important.txt"})
        self.assertTrue(allowed)
        self.assertIsNone(msg)
        self.assertEqual(action, "allow")

    def test_gate_on_open_app_requested_is_allowed(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("open_app", {"app_name": "Chrome"}, "Abra o Chrome")
        self.assertTrue(allowed)
        self.assertEqual(action, "allow")

    def test_gate_on_open_app_not_requested_requires_confirmation(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("open_app", {"app_name": "Chrome"}, "O que é SQLite?")
        self.assertFalse(allowed)
        self.assertEqual(action, "confirm")
        self.assertIn("Confirm to proceed?", msg)

    def test_gate_on_create_file_requested_is_allowed(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("file_controller", {"action": "create_file", "path": "teste.txt"}, "Crie um arquivo teste.txt")
        self.assertTrue(allowed)
        self.assertEqual(action, "allow")

    def test_gate_on_read_file_requested_is_allowed(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("file_controller", {"action": "read", "path": "README.md"}, "Leia o README.md")
        self.assertTrue(allowed)
        self.assertEqual(action, "allow")

    def test_gate_on_delete_file_requires_confirmation(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("file_controller", {"action": "delete", "path": "somefile.txt"}, "Delete esse arquivo")
        self.assertFalse(allowed)
        self.assertEqual(action, "confirm")
        self.assertIn("Risk: medium (file_delete)", msg)

    def test_gate_on_delete_all_files_denied(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("file_controller", {"action": "delete", "path": "*"}, "Delete todos os arquivos")
        self.assertFalse(allowed)
        self.assertEqual(action, "deny")
        self.assertIn("dangerous: bulk_file_operation", msg)

    def test_gate_on_edit_main_py_requires_confirmation(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("file_controller", {"action": "write", "path": "main.py"}, "Altere o main.py")
        self.assertFalse(allowed)
        self.assertEqual(action, "confirm")
        self.assertIn("critical_path_modification", msg)

    def test_gate_on_shell_command_requires_confirmation_or_deny(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("code_helper", {"action": "run", "file_path": "script.py"})
        self.assertFalse(allowed)
        self.assertEqual(action, "confirm")
        self.assertIn("code_run", msg)

    def test_gate_on_destructive_command_denied(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("computer_control", {"action": "type", "text": "rm -rf /"})
        self.assertFalse(allowed)
        self.assertEqual(action, "deny")
        self.assertIn("destructive_command", msg)

    def test_gate_on_save_memory_allowed(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("save_memory", {"category": "notes", "key": "fav", "value": "pizza"})
        self.assertTrue(allowed)
        self.assertEqual(action, "allow")

    def test_gate_message_does_not_leak_sensitive_args(self):
        from main import _apply_tool_call_gate
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        allowed, msg, action = _apply_tool_call_gate("code_helper", {"action": "edit", "code": "API_KEY = 'sk-1234567890abcdef12345678'"})
        self.assertFalse(allowed)
        self.assertNotIn("1234567890abcdef", msg)
        self.assertIn("[REDACTED]", msg)

    def test_no_subprocess_or_actions_imported_by_gate(self):
        from main import _apply_tool_call_gate
        import inspect
        from main import _classify_tool_call, _tool_was_clearly_requested, _format_tool_confirmation
        funcs = [_apply_tool_call_gate, _classify_tool_call, _tool_was_clearly_requested, _format_tool_confirmation]
        for f in funcs:
            source = inspect.getsource(f)
            self.assertNotIn("import subprocess", source)
            self.assertNotIn("from actions", source)
            self.assertNotIn("import actions", source)

if __name__ == "__main__":
    unittest.main()
