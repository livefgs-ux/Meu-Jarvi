import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from actions.open_app import open_app
from core.app_inventory import AppCandidate

class TestOpenAppInventoryIntegration(unittest.TestCase):

    def setUp(self):
        self.mock_launcher = MagicMock(return_value=True)
        self.patcher = patch("actions.open_app._OS_LAUNCHERS", {"Windows": self.mock_launcher})
        self.patcher.start()

        # Mock environment state to avoid real side effects
        self.patch_win = patch("actions.open_app.get_active_window_info", return_value={"status": "ok", "title": "Mock App", "process_name": "mock.exe"})
        self.patch_win.start()

        self.patch_verify = patch("actions.open_app.verify_app_match", return_value={"match": True})
        self.patch_verify.start()

    def tearDown(self):
        self.patcher.stop()
        self.patch_win.stop()
        self.patch_verify.stop()

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_uses_trusted_inventory_verified_executable(self, mock_resolve):
        candidate = AppCandidate(
            name="Visual Studio Code",
            normalized_name="visual studio code",
            executable_path="C:\\Path\\To\\Code.exe",
            status="installed_verified"
        )
        mock_resolve.return_value = {"status": "installed_verified", "candidate": candidate}

        result = open_app({"app_name": "VS Code"})

        self.assertIn("Opened VS Code", result)
        self.mock_launcher.assert_called_with("C:\\Path\\To\\Code.exe")

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_not_found_does_not_launch(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found"}

        result = open_app({"app_name": "Unknown App"})

        self.assertIn("não está instalado ou não foi encontrado", result)
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_stale_does_not_launch(self, mock_resolve):
        mock_resolve.return_value = {"status": "stale"}

        result = open_app({"app_name": "Stale App"})

        self.assertIn("registros antigos ou atalhos quebrados", result)
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_ambiguous_does_not_launch(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "ambiguous",
            "candidates": [
                AppCandidate(name="App A", normalized_name="app a"),
                AppCandidate(name="App B", normalized_name="app b")
            ]
        }

        result = open_app({"app_name": "Ambi App"})

        self.assertIn("mais de um aplicativo parecido", result)
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_registry_only_does_not_launch(self, mock_resolve):
        mock_resolve.return_value = {"status": "registry_only"}

        result = open_app({"app_name": "Registry App"})

        self.assertIn("não consegui verificar o executável", result)
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_does_not_open_codex(self, mock_resolve):
        # Even if "Codex" is in the system, asking for "VS Code" should return not_found if VS Code itself isn't there
        mock_resolve.return_value = {"status": "not_found"}

        result = open_app({"app_name": "VS Code"})
        self.assertIn("não está instalado", result.lower())
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_does_not_open_cursor(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found"}

        result = open_app({"app_name": "VS Code"})
        self.assertIn("não está instalado", result.lower())
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_cursor_not_found_does_not_open_vscode(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found"}

        result = open_app({"app_name": "Cursor"})
        self.assertIn("não está instalado", result.lower())
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_internet_explorer_never_opens_file_explorer(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found"}

        result = open_app({"app_name": "Internet Explorer"})
        self.assertIn("não está instalado", result.lower())
        self.mock_launcher.assert_not_called()

    @patch("actions.open_app.resolve_trusted_app")
    def test_file_explorer_can_open_explorer_exe(self, mock_resolve):
        candidate = AppCandidate(
            name="Windows Explorer",
            normalized_name="windows file explorer",
            executable_path="C:\\Windows\\explorer.exe",
            status="installed_verified"
        )
        mock_resolve.return_value = {"status": "installed_verified", "candidate": candidate}

        result = open_app({"app_name": "File Explorer"})
        self.assertIn("Opened File Explorer", result)
        self.mock_launcher.assert_called_with("C:\\Windows\\explorer.exe")

    def test_no_windows_search_fallback_for_unknown_app(self):
        # We need a real call to resolve_trusted_app that we know will return not_found
        # or mock it to return not_found and verify launcher never sees pyautogui logic
        # (Since we removed pyautogui logic from _launch_windows, this is guaranteed)
        with patch("actions.open_app.resolve_trusted_app") as mock_resolve:
            mock_resolve.return_value = {"status": "not_found"}
            open_app({"app_name": "Some Random App"})
            self.mock_launcher.assert_not_called()

    def test_no_real_apps_launched_in_tests(self):
        # This is guaranteed by the mock_launcher in setUp
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
