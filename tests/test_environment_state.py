import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.environment_state import (
    get_known_folders,
    normalize_app_identity,
    verify_app_match,
    detect_blocking_ui,
    build_environment_snapshot
)

class TestEnvironmentState(unittest.TestCase):

    def test_known_folders_returns_dict(self):
        folders = get_known_folders()
        self.assertIsInstance(folders, dict)
        self.assertIn("home", folders)
        self.assertIn("desktop", folders)

    def test_known_folders_contains_desktop_key(self):
        folders = get_known_folders()
        self.assertIsNotNone(folders["desktop"])
        # Should be an absolute path
        self.assertTrue(os.path.isabs(folders["desktop"]))

    def test_known_folders_does_not_hardcode_user_desktop_only(self):
        # We can't easily verify if it resolved OneDrive vs Local in a generic test,
        # but we can verify it's not a dummy string.
        folders = get_known_folders()
        self.assertTrue(len(folders["desktop"]) > 5)

    def test_normalize_browser_identities(self):
        self.assertEqual(normalize_app_identity("chrome")["normalized"], "Google Chrome")
        self.assertEqual(normalize_app_identity("Google Chrome")["normalized"], "Google Chrome")
        self.assertEqual(normalize_app_identity("edge")["normalized"], "Microsoft Edge")
        self.assertEqual(normalize_app_identity("msedge")["normalized"], "msedge") # Raw if not in map

    def test_normalize_editor_identities(self):
        self.assertEqual(normalize_app_identity("vs code")["normalized"], "Visual Studio Code")
        self.assertEqual(normalize_app_identity("cursor")["normalized"], "Cursor")

    def test_internet_explorer_not_equal_file_explorer(self):
        ie = normalize_app_identity("internet explorer")["normalized"]
        fe = normalize_app_identity("explorer")["normalized"]
        self.assertNotEqual(ie, fe)

    def test_vscode_not_equal_cursor(self):
        vs = normalize_app_identity("vscode")["normalized"]
        cur = normalize_app_identity("cursor")["normalized"]
        self.assertNotEqual(vs, cur)

    def test_verify_app_match_detects_vscode_cursor_mismatch(self):
        res = verify_app_match("VS Code", "cursor.exe")
        self.assertFalse(res["match"])
        self.assertIn("forbidden_overlap", res["reason"])

    def test_verify_app_match_detects_internet_explorer_explorer_mismatch(self):
        res = verify_app_match("Internet Explorer", "explorer.exe")
        self.assertFalse(res["match"])
        self.assertIn("forbidden_overlap", res["reason"])

    def test_verify_app_match_detects_file_explorer_match(self):
        res = verify_app_match("File Explorer", "explorer.exe")
        self.assertTrue(res["match"])
        self.assertEqual(res["reason"], "exe_match")

    def test_detect_blocking_ui_google_consent(self):
        res = detect_blocking_ui("Before you continue to Google Search")
        self.assertTrue(res["detected"])
        self.assertEqual(res["type"], "consent")

    def test_detect_blocking_ui_login(self):
        res = detect_blocking_ui("Login to your account")
        self.assertTrue(res["detected"])
        self.assertEqual(res["type"], "auth")

    def test_detect_blocking_ui_permission_denied(self):
        res = detect_blocking_ui("Permission denied to access this folder")
        self.assertTrue(res["detected"])
        self.assertEqual(res["type"], "denial")

    def test_detect_blocking_ui_captcha(self):
        res = detect_blocking_ui("Please solve the captcha")
        self.assertTrue(res["detected"])
        self.assertEqual(res["type"], "security")

    def test_environment_snapshot_is_safe_dict(self):
        snap = build_environment_snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn("timestamp", snap)
        self.assertIn("known_folders", snap)

    def test_module_does_not_import_actions(self):
        # Check the source code for the string "import actions" or "from actions"
        # to avoid pollution from other tests in sys.modules
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'core', 'environment_state.py'))
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertNotIn("import actions", content)
            self.assertNotIn("from actions", content)

    def test_module_does_not_write_files(self):
        # This is a behavior test. We can patch open() to ensure no 'w' mode is used.
        with patch("builtins.open", MagicMock(side_effect=IOError("Write blocked during test"))) as mock_open:
            try:
                build_environment_snapshot()
            except IOError:
                self.fail("Environment snapshot attempted to write a file!")

    def test_module_does_not_open_apps(self):
        # Patch subprocess.Popen to ensure it's never called
        with patch("subprocess.Popen") as mock_popen:
            build_environment_snapshot()
            mock_popen.assert_not_called()

if __name__ == "__main__":
    unittest.main()
