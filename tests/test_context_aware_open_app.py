import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from actions.open_app import open_app
from core.app_inventory import AppCandidate

class TestContextAwareOpenApp(unittest.TestCase):

    @patch("actions.open_app._OS_LAUNCHERS")
    @patch("actions.open_app.get_active_window_info")
    def test_vscode_mismatch_cursor(self, mock_get_win, mock_launchers):
        # Setup mock launcher to return True (success)
        mock_launcher = MagicMock(return_value=True)
        mock_launchers.get.return_value = mock_launcher

        # Setup mock window info to return Cursor
        mock_get_win.return_value = {
            "status": "ok",
            "title": "Cursor - main.py",
            "process_name": "Cursor.exe"
        }

        # Setup mock trusted resolver
        mock_candidate = AppCandidate(name="VS Code", normalized_name="visual studio code", executable_path="C:\\Path\\To\\Code.exe", status="installed_verified")
        with patch("actions.open_app.resolve_trusted_app") as mock_resolve:
            mock_resolve.return_value = {"status": "installed_verified", "candidate": mock_candidate}
            result = open_app({"app_name": "VS Code"})
            self.assertIn("might not be VS Code", result)
            self.assertIn("Detected: Cursor - main.py", result)

    @patch("actions.open_app._OS_LAUNCHERS")
    @patch("actions.open_app.get_active_window_info")
    def test_internet_explorer_mismatch_explorer(self, mock_get_win, mock_launchers):
        mock_launcher = MagicMock(return_value=True)
        mock_launchers.get.return_value = mock_launcher

        mock_get_win.return_value = {
            "status": "ok",
            "title": "Downloads",
            "process_name": "explorer.exe"
        }

        # Setup mock trusted resolver
        mock_candidate = AppCandidate(name="Internet Explorer", normalized_name="internet explorer", executable_path="C:\\Path\\To\\iexplore.exe", status="installed_verified")
        with patch("actions.open_app.resolve_trusted_app") as mock_resolve:
            mock_resolve.return_value = {"status": "installed_verified", "candidate": mock_candidate}
            result = open_app({"app_name": "Internet Explorer"})
            self.assertIn("might not be Internet Explorer", result)

    @patch("actions.open_app._OS_LAUNCHERS")
    @patch("actions.open_app.get_active_window_info")
    def test_file_explorer_match_explorer(self, mock_get_win, mock_launchers):
        mock_launcher = MagicMock(return_value=True)
        mock_launchers.get.return_value = mock_launcher

        mock_get_win.return_value = {
            "status": "ok",
            "title": "Documents",
            "process_name": "explorer.exe"
        }

        # Setup mock trusted resolver
        mock_candidate = AppCandidate(name="File Explorer", normalized_name="windows file explorer", executable_path="C:\\Windows\\explorer.exe", status="installed_verified")
        with patch("actions.open_app.resolve_trusted_app") as mock_resolve:
            mock_resolve.return_value = {"status": "installed_verified", "candidate": mock_candidate}
            result = open_app({"app_name": "File Explorer"})
            self.assertEqual(result, "Opened File Explorer.")

    @patch("actions.open_app._OS_LAUNCHERS")
    @patch("actions.open_app.get_active_window_info")
    def test_unverifiable_returns_neutral(self, mock_get_win, mock_launchers):
        mock_launcher = MagicMock(return_value=True)
        mock_launchers.get.return_value = mock_launcher

        mock_get_win.return_value = {"status": "unsupported_os"}

        # Setup mock trusted resolver
        mock_candidate = AppCandidate(name="Chrome", normalized_name="google chrome", executable_path="C:\\Path\\To\\chrome.exe", status="installed_verified")
        with patch("actions.open_app.resolve_trusted_app") as mock_resolve:
            mock_resolve.return_value = {"status": "installed_verified", "candidate": mock_candidate}
            result = open_app({"app_name": "Chrome"})
            self.assertEqual(result, "Opened Chrome.")

if __name__ == "__main__":
    unittest.main()
