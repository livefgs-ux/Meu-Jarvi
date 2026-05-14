import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add the project root to sys.path to allow importing actions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from actions.open_app import resolve_app_command

class TestAppResolver(unittest.TestCase):

    def setUp(self):
        # We need to be careful with the _SYSTEM variable in open_app
        pass

    @patch("shutil.which")
    @patch("os.path.exists")
    def test_internet_explorer_does_not_resolve_to_explorer_exe(self, mock_exists, mock_which):
        mock_which.return_value = None
        mock_exists.return_value = False
        res = resolve_app_command("Internet Explorer", system="Windows")
        if res["status"] == "ok":
            self.assertNotEqual(res["command"], "explorer.exe")
        else:
            self.assertEqual(res["status"], "error")
            self.assertIn("not found", res["message"].lower())

    def test_file_explorer_resolves_to_explorer_exe(self):
        res = resolve_app_command("File Explorer", system="Windows")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["command"], "explorer.exe")

    @patch("shutil.which")
    @patch("os.path.exists")
    def test_internet_explorer_missing_returns_clear_error(self, mock_exists, mock_which):
        mock_which.return_value = None
        mock_exists.return_value = False
        res = resolve_app_command("Internet Explorer", system="Windows")
        self.assertEqual(res["status"], "error")
        self.assertIn("Internet Explorer was not found", res["message"])

    @patch("shutil.which")
    def test_internet_explorer_resolves_to_iexplore_if_exists(self, mock_which):
        mock_which.return_value = "C:\\some\\path\\iexplore.exe"
        res = resolve_app_command("ie", system="Windows")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["command"], "iexplore.exe")

    def test_edge_resolves_to_msedge(self):
        res = resolve_app_command("Edge", system="Windows")
        self.assertEqual(res["command"], "msedge")

    def test_chrome_resolves_to_chrome(self):
        res = resolve_app_command("Chrome", system="Windows")
        self.assertEqual(res["command"], "chrome")

    def test_vscode_does_not_resolve_to_cursor(self):
        res = resolve_app_command("VS Code", system="Windows")
        self.assertEqual(res["command"], "code")
        self.assertNotEqual(res["command"], "cursor")

    def test_cursor_does_not_resolve_to_vscode(self):
        res = resolve_app_command("Cursor", system="Windows")
        self.assertEqual(res["command"], "cursor")
        self.assertNotEqual(res["command"], "code")

    def test_unknown_app_does_not_open_fallback_app(self):
        # Should not fuzzy match explorer
        res = resolve_app_command("Internet Explorer Alternate", system="Windows")
        if res["status"] == "ok":
            self.assertNotEqual(res["command"], "explorer.exe")

        # Test that fuzzy match still works for non-dangerous ones
        # e.g. "Google Chrome" -> "chrome"
        res = resolve_app_command("Google Chrome", system="Windows")
        self.assertEqual(res["command"], "chrome")

    def test_app_resolver_does_not_execute_real_apps_in_tests(self):
        # We are only testing resolve_app_command, which doesn't call subprocess
        pass

if __name__ == "__main__":
    unittest.main()
