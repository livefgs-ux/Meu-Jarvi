import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from actions.open_app import open_app

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

        # We need to mock resolve_app_command to allow "Internet Explorer" if we want to reach verification
        # actually resolve_app_command is already implemented and might error if not found.
        # Let's mock resolve_app_command too to simulate a "found" but "wrong app opened" scenario
        with patch("actions.open_app.resolve_app_command") as mock_resolve:
            mock_resolve.return_value = {"status": "ok", "command": "iexplore.exe", "label": "Internet Explorer"}
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

        result = open_app({"app_name": "File Explorer"})
        self.assertEqual(result, "Opened File Explorer.")

    @patch("actions.open_app._OS_LAUNCHERS")
    @patch("actions.open_app.get_active_window_info")
    def test_unverifiable_returns_neutral(self, mock_get_win, mock_launchers):
        mock_launcher = MagicMock(return_value=True)
        mock_launchers.get.return_value = mock_launcher

        mock_get_win.return_value = {"status": "unsupported_os"}

        result = open_app({"app_name": "Chrome"})
        self.assertEqual(result, "Opened Chrome.")

if __name__ == "__main__":
    unittest.main()
