import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestIntentConfidenceIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()
        sys.modules["sounddevice"] = MagicMock()
        self.main = importlib.import_module("main")
        self.actions_web_search = importlib.import_module("actions.web_search")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        try:
            loop = getattr(self, "_jarvis_loop", None)
            if loop and not loop.is_closed():
                loop.close()
        except Exception:
            pass

    def _make_jarvis(self):
        ui = MagicMock()
        jarvis = self.main.JarvisLive(ui)
        jarvis._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(jarvis._loop)
        self._jarvis_loop = jarvis._loop
        jarvis.session = AsyncMock()
        jarvis.session.send_client_content = MagicMock()
        jarvis.speak = MagicMock()
        return jarvis

    async def test_blocks_game_updater_from_bad_transcript(self):
        jarvis = self._make_jarvis()
        jarvis.last_user_text = "Ti nha contato esquerdamento?"
        fc = MagicMock()
        fc.name = "game_updater"
        fc.args = {"action": "schedule_status"}
        fc.id = "bad_game"

        with patch("main.game_updater") as game_updater:
            res = await jarvis._execute_tool(fc)

        self.assertEqual(res.response["result"], "blocked_low_confidence")
        game_updater.assert_not_called()
        jarvis.speak.assert_called()
        self.assertIn("Não entendi", jarvis.speak.call_args.args[0])

    async def test_allows_web_search_from_clear_search_request(self):
        jarvis = self._make_jarvis()
        jarvis.last_user_text = "pesquisa na internet sobre novidades sobre IA"
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "novidades sobre IA"}
        fc.id = "good_search"

        with patch("main.web_search_action", return_value="Busca em português"):
            res = await jarvis._execute_tool(fc)

        self.assertIn("Busca em português", res.response["result"])
        jarvis.speak.assert_not_called()

    async def test_blocks_tool_when_user_text_missing_evidence(self):
        jarvis = self._make_jarvis()
        jarvis.last_user_text = "agendamento status"
        fc = MagicMock()
        fc.name = "open_app"
        fc.args = {"app_name": "Chrome"}
        fc.id = "missing_evidence"

        with patch("main.open_app") as open_app:
            res = await jarvis._execute_tool(fc)

        self.assertEqual(res.response["result"], "blocked_low_confidence")
        open_app.assert_not_called()

    async def test_blocked_tool_returns_function_response_without_execution(self):
        jarvis = self._make_jarvis()
        jarvis.last_user_text = "Ti nha contato esquerdamento?"
        fc = MagicMock()
        fc.name = "browser_control"
        fc.args = {"action": "go_to", "browser": "chrome"}
        fc.id = "blocked_browser"

        with patch("main.browser_control") as browser_control:
            res = await jarvis._execute_tool(fc)

        self.assertTrue(hasattr(res, "response"))
        self.assertEqual(res.response["result"], "blocked_low_confidence")
        browser_control.assert_not_called()

    async def test_blocked_tool_speaks_portuguese_clarification(self):
        jarvis = self._make_jarvis()
        jarvis.last_user_text = "agendamento status"
        fc = MagicMock()
        fc.name = "file_controller"
        fc.args = {"action": "delete", "path": "important.txt"}
        fc.id = "blocked_file"

        with patch("main.file_controller") as file_controller:
            await jarvis._execute_tool(fc)

        file_controller.assert_not_called()
        self.assertTrue(jarvis.speak.called)
        msg = jarvis.speak.call_args.args[0]
        self.assertIn("Não entendi", msg)
        self.assertNotIn("understood", msg.lower())

    def test_web_search_prompt_forces_portuguese(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = types.SimpleNamespace(
            candidates=[
                types.SimpleNamespace(
                    content=types.SimpleNamespace(
                        parts=[types.SimpleNamespace(text="Resposta em português.")]
                    )
                )
            ]
        )
        with patch("actions.web_search.genai.Client", return_value=mock_client):
            result = self.actions_web_search.web_search({"query": "novidades sobre IA"})

        self.assertIn("Resposta em português", result)
        contents = mock_client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("português brasileiro", contents.lower())
        self.assertIn("não prometa", contents.lower())

    async def test_unknown_text_preserves_existing_flow_when_not_action(self):
        jarvis = self._make_jarvis()
        with patch.object(self.main.asyncio, "run_coroutine_threadsafe") as run_threadsafe:
            jarvis._on_text_command("Qual é a capital da França?")

        run_threadsafe.assert_called_once()

    async def test_no_real_tools_executed(self):
        jarvis = self._make_jarvis()
        jarvis.last_user_text = "agendamento status"
        fc = MagicMock()
        fc.name = "game_updater"
        fc.args = {"action": "schedule_status"}
        fc.id = "real_tools"

        with patch("main.game_updater") as game_updater, patch("main.open_app") as open_app:
            await jarvis._execute_tool(fc)

        game_updater.assert_not_called()
        open_app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
