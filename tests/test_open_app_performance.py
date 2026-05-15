import builtins
import unittest
from unittest.mock import MagicMock, patch

from actions.open_app import open_app


class TestOpenAppPerformance(unittest.TestCase):
    def setUp(self):
        self.mock_launcher = MagicMock(return_value=True)
        self.patcher = patch("actions.open_app._OS_LAUNCHERS", {"Windows": self.mock_launcher})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    @patch("actions.open_app.resolve_trusted_app")
    @patch("actions.open_app.time.time", side_effect=[100.0, 100.012])
    def test_open_app_not_found_with_cache_returns_fast(self, mock_time, mock_resolve):
        mock_resolve.return_value = {"status": "not_found", "query": "VS Code"}

        result = open_app({"app_name": "VS Code"})

        self.assertIn("não parece estar instalado neste PC", result)
        self.assertNotIn("Cursor", result)
        self.assertNotIn("Codex", result)
        mock_resolve.assert_called_once()

    @patch("actions.open_app.resolve_trusted_app")
    @patch("builtins.print")
    @patch("actions.open_app.time.time", side_effect=[10.0, 10.05])
    def test_open_app_logs_resolution_duration(self, mock_time, mock_print, mock_resolve):
        mock_resolve.return_value = {"status": "not_found", "query": "VS Code"}

        open_app({"app_name": "VS Code"})

        mock_print.assert_any_call("[open_app] Resolution for 'VS Code' took 50.0ms (Status: not_found)")

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_does_not_trigger_deep_scan_by_default(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found", "query": "VS Code"}

        open_app({"app_name": "VS Code"})

        mock_resolve.assert_called_once_with("VS Code", include_alternatives=False)
        self.assertNotIn("force_refresh", mock_resolve.call_args.kwargs)

    @patch("actions.open_app.resolve_trusted_app")
    def test_open_app_force_refresh_not_used_by_normal_call(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found", "query": "VS Code"}

        open_app({"app_name": "VS Code"})

        self.assertFalse(mock_resolve.call_args.kwargs.get("force_refresh", False))

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_does_not_suggest_cursor_by_default(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found", "query": "VS Code"}

        result = open_app({"app_name": "VS Code"})

        self.assertIn("VS Code não parece estar instalado neste PC", result)
        self.assertNotIn("Cursor", result)
        self.assertNotIn("Codex", result)

    @patch("actions.open_app.resolve_trusted_app")
    def test_vscode_not_found_offers_install_help(self, mock_resolve):
        mock_resolve.return_value = {"status": "not_found", "query": "VS Code"}

        result = open_app({"app_name": "VS Code"})

        self.assertIn("Posso te ajudar a instalar?", result)


if __name__ == "__main__":
    unittest.main()
