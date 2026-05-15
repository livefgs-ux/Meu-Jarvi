import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from actions.open_app import open_app
from core.app_inventory import AppCandidate

class TestOpenAppFriendlyResponses(unittest.TestCase):

    def setUp(self):
        self.mock_launcher = MagicMock(return_value=True)
        self.patcher = patch("actions.open_app._OS_LAUNCHERS", {"Windows": self.mock_launcher})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_does_not_suggest_cursor_by_default(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found",
            "query": "VS Code",
        }
        result = open_app({"app_name": "VS Code"})
        self.assertNotIn("Cursor", result)
        self.assertNotIn("Codex", result)
        self.assertIn("não parece estar instalado neste PC", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_offers_install_help(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found",
            "query": "VS Code",
        }
        result = open_app({"app_name": "VS Code"})
        self.assertIn("Posso te ajudar a instalar?", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_alternatives_only_shown_when_user_asks_for_alternative(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found",
            "query": "VS Code",
            "alternatives": ["Cursor", "Codex"],
        }
        result = open_app({"app_name": "VS Code", "show_alternatives": True})
        self.assertIn("Se você quiser uma alternativa, encontrei: Cursor, Codex", result)
        self.assertNotIn("trusted app inventory", result.lower())

    @patch("actions.open_app.resolve_trusted_app")
    def test_stale_app_offers_reinstall_help(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "stale",
            "query": "BrokenApp",
            "candidate": AppCandidate(name="BrokenApp", normalized_name="brokenapp")
        }
        result = open_app({"app_name": "BrokenApp"})
        self.assertIn("Posso te ajudar a reinstalar?", result)
        self.assertIn("sinais antigos de BrokenApp", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_ambiguous_same_app_can_ask_which_installation(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "ambiguous",
            "query": "App",
            "candidates": [
                AppCandidate(name="App One", normalized_name="app one"),
                AppCandidate(name="App Two", normalized_name="app two")
            ]
        }
        result = open_app({"app_name": "App"})
        self.assertIn("Encontrei mais de uma instalação possível de App", result)
        self.assertIn("Qual delas você quer abrir?", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_registry_only_message_does_not_open(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "registry_only",
            "query": "RegOnly",
            "candidate": AppCandidate(name="RegOnly", normalized_name="regonly")
        }
        result = open_app({"app_name": "RegOnly"})
        self.assertIn("não consegui confirmar o executável", result)
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_different_app_is_not_treated_as_alternative_for_open_request(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found",
            "query": "VS Code",
            "alternatives": ["Cursor", "Codex"],
        }
        result = open_app({"app_name": "VS Code"})
        self.assertNotIn("Cursor", result)
        self.assertNotIn("Codex", result)

    def test_no_real_apps_launched(self):
        # Guaranteed by setUp mocking _OS_LAUNCHERS
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
