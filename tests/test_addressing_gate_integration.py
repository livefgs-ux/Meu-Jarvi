import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.runtime_journal import get_runtime_timeline, list_recent_events


class TestAddressingGateIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()
        sys.modules["sounddevice"] = MagicMock()
        self.main = importlib.import_module("main")
        self.timeline = get_runtime_timeline()
        self.timeline.clear()

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
        jarvis.session = MagicMock()
        jarvis.session.send_tool_response = AsyncMock()
        jarvis.speak = MagicMock()
        jarvis.audio_in_queue = asyncio.Queue()
        jarvis._turn_done_event = asyncio.Event()
        return jarvis

    def _make_response(self, input_text=None, tool_name=None, tool_args=None, data=b"chunk", turn_complete=True):
        input_part = None if input_text is None else types.SimpleNamespace(text=input_text)
        output_part = None
        tool_call = None
        if tool_name:
            fc = types.SimpleNamespace(name=tool_name, args=tool_args or {}, id="call-1")
            tool_call = types.SimpleNamespace(function_calls=[fc])
        return types.SimpleNamespace(
            data=data,
            server_content=types.SimpleNamespace(
                input_transcription=input_part,
                output_transcription=output_part,
                turn_complete=turn_complete,
            ),
            tool_call=tool_call,
        )

    async def _receive_once(self, jarvis, response):
        async def one_response():
            yield response

        jarvis.session.receive = MagicMock(side_effect=[one_response(), RuntimeError("end")])
        with patch("builtins.print"), self.assertRaises(RuntimeError):
            await jarvis._receive_audio()

    async def test_audio_without_wake_word_does_not_call_model_or_tool(self):
        jarvis = self._make_jarvis()
        response = self._make_response("abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})
        with patch("main.open_app") as open_app:
            await self._receive_once(jarvis, response)

        self.assertIsNone(jarvis.last_user_text)
        self.assertFalse(jarvis.speak.called)
        open_app.assert_not_called()
        event_types = [event.event_type for event in list_recent_events()]
        self.assertIn("user_utterance_ignored_not_addressed", event_types)

    async def test_audio_with_wake_word_calls_existing_flow(self):
        jarvis = self._make_jarvis()
        response = self._make_response("Jarvis, abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})

        async def fake_execute(fc):
            return types.SimpleNamespace(response={"result": "ok"})

        jarvis._execute_tool = AsyncMock(side_effect=fake_execute)

        await self._receive_once(jarvis, response)

        self.assertEqual(jarvis.last_user_text, "abre o VS Code")
        jarvis._execute_tool.assert_called_once()

    async def test_audio_with_wake_word_strips_name_before_processing(self):
        jarvis = self._make_jarvis()
        response = self._make_response("Charles, pesquisa novidades sobre IA")

        await self._receive_once(jarvis, response)

        self.assertEqual(jarvis.last_user_text, "pesquisa novidades sobre IA")

    async def test_open_app_not_called_without_wake_word(self):
        jarvis = self._make_jarvis()
        response = self._make_response("abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})
        with patch("main.open_app") as open_app:
            await self._receive_once(jarvis, response)

        open_app.assert_not_called()

    async def test_web_search_not_called_without_wake_word(self):
        jarvis = self._make_jarvis()
        response = self._make_response("pesquisa novidades sobre IA", tool_name="web_search", tool_args={"query": "novidades sobre IA"})
        with patch("main.web_search_action") as web_search_action:
            await self._receive_once(jarvis, response)

        web_search_action.assert_not_called()

    async def test_speech_stop_command_still_works_without_wake_word_when_speaking(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False):
            response = self._make_response("para", turn_complete=True)
            await self._receive_once(jarvis, response)

        self.assertFalse(jarvis._speech_control_state.is_silenced)
        self.assertFalse(jarvis.speak.called)
        event_types = [event.event_type for event in list_recent_events()]
        self.assertIn("speech_interrupted", event_types)

    async def test_journal_records_ignored_utterance(self):
        jarvis = self._make_jarvis()
        response = self._make_response("abre o navegador", tool_name="open_app", tool_args={"app_name": "Chrome"})
        await self._receive_once(jarvis, response)

        event_types = [event.event_type for event in list_recent_events()]
        self.assertIn("user_utterance_ignored_not_addressed", event_types)

    async def test_fail_open_or_fail_closed_policy_is_safe(self):
        jarvis = self._make_jarvis()
        response = self._make_response("Jarvis, abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})
        with patch.object(self.main, "should_process_user_utterance", side_effect=Exception("boom")), patch(
            "main.open_app"
        ) as open_app:
            await self._receive_once(jarvis, response)

        open_app.assert_not_called()
        self.assertFalse(jarvis.speak.called)


if __name__ == "__main__":
    unittest.main()
