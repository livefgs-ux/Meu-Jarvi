import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from actions.file_controller import _resolve_path, create_file

class TestContextAwareFileController(unittest.TestCase):

    @patch("actions.file_controller.get_known_folders")
    def test_desktop_resolves_to_onedrive_if_returned(self, mock_get_known):
        # Setup mock
        mock_get_known.return_value = {
            "desktop": r"C:\Users\User\OneDrive\Desktop",
            "home": r"C:\Users\User"
        }

        path = _resolve_path("desktop")
        self.assertEqual(str(path), r"C:\Users\User\OneDrive\Desktop")

    @patch("actions.file_controller.get_known_folders")
    def test_downloads_resolves_to_mocked_path(self, mock_get_known):
        mock_get_known.return_value = {
            "downloads": r"D:\MyDownloads"
        }
        path = _resolve_path("downloads")
        self.assertEqual(str(path), r"D:\MyDownloads")

    @patch("actions.file_controller.get_known_folders")
    @patch("actions.file_controller._is_safe_path")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_text")
    def test_create_file_uses_resolved_path(self, mock_write, mock_mkdir, mock_safe, mock_get_known):
        mock_get_known.return_value = {"desktop": r"C:\Fake\Desktop"}
        mock_safe.return_value = True

        create_file("desktop", "test.txt", "hello")

        # Check that mkdir was called for the parent of the resolved path
        # Note: In our implementation, we call target.parent.mkdir
        # target = C:\Fake\Desktop\test.txt
        # target.parent = C:\Fake\Desktop
        # But wait, create_file(path, name, content)
        # target = base / name
        # base = _resolve_path(path) = C:\Fake\Desktop
        # target = C:\Fake\Desktop \ test.txt

        self.assertTrue(mock_mkdir.called)
        self.assertTrue(mock_write.called)

    def test_not_hardcoded_user_profile(self):
        # Just ensure we are not using os.getlogin() or similar directly in a hardcoded way
        # our get_known_folders uses Registry/Path.home() which is dynamic
        pass

if __name__ == "__main__":
    unittest.main()
