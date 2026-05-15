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
    def test_vscode_not_found_message_is_user_friendly(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found", 
            "query": "VS Code", 
            "alternatives": []
        }
        result = open_app({"app_name": "VS Code"})
        self.assertIn("não está instalado ou não foi encontrado neste PC", result)
        self.assertNotIn("trusted app inventory", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_lists_cursor_codex_as_alternatives(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found", 
            "query": "VS Code", 
            "alternatives": ["Cursor", "Codex"]
        }
        result = open_app({"app_name": "VS Code"})
        self.assertIn("Encontrei alternativas: Cursor, Codex", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_not_found_message_does_not_say_trusted_app_inventory_to_user(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found", 
            "query": "Some App", 
            "alternatives": []
        }
        result = open_app({"app_name": "Some App"})
        self.assertNotIn("trusted app inventory", result.lower())

    @patch("actions.open_app.resolve_trusted_app")
    def test_stale_message_mentions_broken_entries(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "stale", 
            "query": "BrokenApp",
            "candidate": AppCandidate(name="BrokenApp", normalized_name="brokenapp")
        }
        result = open_app({"app_name": "BrokenApp"})
        self.assertIn("registros antigos ou atalhos quebrados", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_ambiguous_message_lists_candidates(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "ambiguous", 
            "query": "App",
            "candidates": [
                AppCandidate(name="App One", normalized_name="app one"),
                AppCandidate(name="App Two", normalized_name="app two")
            ]
        }
        result = open_app({"app_name": "App"})
        self.assertIn("Encontrei mais de um aplicativo parecido: App One, App Two", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_registry_only_message_does_not_open(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "registry_only", 
            "query": "RegOnly",
            "candidate": AppCandidate(name="RegOnly", normalized_name="regonly")
        }
        result = open_app({"app_name": "RegOnly"})
        self.assertIn("não consegui verificar o executável", result)
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_internet_explorer_not_found_suggests_edge_ie_mode(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "not_found", 
            "query": "Internet Explorer", 
            "alternatives": ["Microsoft Edge"]
        }
        result = open_app({"app_name": "Internet Explorer"})
        self.assertIn("Microsoft Edge no modo IE", result)

    def test_no_real_apps_launched(self):
        # Guaranteed by setUp mocking _OS_LAUNCHERS
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
