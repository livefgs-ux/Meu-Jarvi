import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.runtime_journal import get_runtime_timeline, list_recent_events
from core.voice_activation_state import clear_voice_activation


class TestAddressingGateIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()
        clear_voice_activation()
        sys.modules["sounddevice"] = MagicMock()
        self.main = importlib.import_module("main")
        self.timeline = get_runtime_timeline()
        self.timeline.clear()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        clear_voice_activation()
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

    async def _receive_two(self, jarvis, response_one, response_two):
        async def one_response():
            yield response_one

        async def two_response():
            yield response_two

        jarvis.session.receive = MagicMock(side_effect=[one_response(), two_response(), RuntimeError("end")])
        with patch("builtins.print"), self.assertRaises(RuntimeError):
            await jarvis._receive_audio()

    async def test_audio_without_wake_word_does_not_call_model_or_tool(self):
        jarvis = self._make_jarvis()
        response = self._make_response("abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})
        jarvis._execute_tool = AsyncMock(return_value=types.SimpleNamespace(response={"result": "ok"}))
        await self._receive_once(jarvis, response)

        self.assertIsNone(jarvis.last_user_text)
        self.assertFalse(jarvis.speak.called)
        jarvis._execute_tool.assert_not_called()
        event_types = [event.event_type for event in list_recent_events()]
        self.assertIn("user_utterance_ignored_not_addressed", event_types)

    async def test_audio_wake_word_only_does_not_call_tool(self):
        jarvis = self._make_jarvis()
        response = self._make_response("Jarvis")
        with patch("main.open_app") as open_app:
            await self._receive_once(jarvis, response)

        open_app.assert_not_called()
        self.assertTrue(jarvis.speak.called)
        self.assertEqual(jarvis.speak.call_args.args[0], "Sim?")

    async def test_audio_wake_word_only_speaks_short_ack(self):
        jarvis = self._make_jarvis()
        response = self._make_response("Jarvis")

        await self._receive_once(jarvis, response)

        self.assertTrue(jarvis.speak.called)
        self.assertEqual(jarvis.speak.call_args.args[0], "Sim?")

    async def test_audio_followup_after_wake_word_calls_existing_flow(self):
        jarvis = self._make_jarvis()
        response_one = self._make_response("Jarvis")
        response_two = self._make_response("abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})

        jarvis._execute_tool = AsyncMock(return_value=types.SimpleNamespace(response={"result": "ok"}))
        await self._receive_two(jarvis, response_one, response_two)

        self.assertEqual(jarvis.last_user_text, "abre o VS Code")
        jarvis._execute_tool.assert_called_once()

    async def test_audio_followup_after_wake_word_strips_nothing_extra(self):
        jarvis = self._make_jarvis()
        response_one = self._make_response("Jarvis")
        response_two = self._make_response("abre o Cursor", tool_name="open_app", tool_args={"app_name": "Cursor"})

        await self._receive_two(jarvis, response_one, response_two)

        self.assertEqual(jarvis.last_user_text, "abre o Cursor")

    async def test_audio_followup_without_wake_word_and_not_armed_ignored(self):
        jarvis = self._make_jarvis()
        response = self._make_response("abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})
        jarvis._execute_tool = AsyncMock(return_value=types.SimpleNamespace(response={"result": "ok"}))
        await self._receive_once(jarvis, response)

        jarvis._execute_tool.assert_not_called()
        self.assertIsNone(jarvis.last_user_text)

    async def test_open_app_after_wake_word_then_command_is_called(self):
        jarvis = self._make_jarvis()
        response_one = self._make_response("Jarvis")
        response_two = self._make_response("abre o Cursor", tool_name="open_app", tool_args={"app_name": "Cursor"})
        jarvis._execute_tool = AsyncMock(return_value=types.SimpleNamespace(response={"result": "ok"}))
        await self._receive_two(jarvis, response_one, response_two)

        jarvis._execute_tool.assert_called_once()
        self.assertEqual(jarvis._execute_tool.call_args.args[0].name, "open_app")
        self.assertEqual(jarvis.last_user_text, "abre o Cursor")

    async def test_web_search_after_wake_word_then_command_is_called(self):
        jarvis = self._make_jarvis()
        response_one = self._make_response("Jarvis")
        response_two = self._make_response("pesquisa novidades sobre IA", tool_name="web_search", tool_args={"query": "novidades sobre IA"})
        jarvis._execute_tool = AsyncMock(return_value=types.SimpleNamespace(response={"result": "ok"}))
        await self._receive_two(jarvis, response_one, response_two)

        jarvis._execute_tool.assert_called_once()
        self.assertEqual(jarvis._execute_tool.call_args.args[0].name, "web_search")
        self.assertEqual(jarvis.last_user_text, "pesquisa novidades sobre IA")

    async def test_stop_speech_still_works_without_wake_word_when_speaking(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False):
            response = self._make_response("para", turn_complete=True)
            await self._receive_once(jarvis, response)

        self.assertFalse(jarvis._speech_control_state.is_silenced)
        self.assertFalse(jarvis.speak.called)
        event_types = [event.event_type for event in list_recent_events()]
        self.assertIn("speech_interrupted", event_types)

    async def test_journal_records_activation_armed_and_consumed(self):
        jarvis = self._make_jarvis()
        response_one = self._make_response("Jarvis")
        response_two = self._make_response("abre o VS Code")

        await self._receive_two(jarvis, response_one, response_two)

        event_types = [event.event_type for event in list_recent_events()]
        self.assertIn("voice_activation_armed", event_types)
        self.assertIn("voice_activation_consumed", event_types)

    async def test_fail_open_or_fail_closed_policy_is_safe(self):
        jarvis = self._make_jarvis()
        response = self._make_response("Jarvis, abre o VS Code", tool_name="open_app", tool_args={"app_name": "VS Code"})
        jarvis._execute_tool = AsyncMock(return_value=types.SimpleNamespace(response={"result": "ok"}))
        with patch.object(self.main, "should_process_audio_utterance", side_effect=Exception("boom")):
            await self._receive_once(jarvis, response)

        jarvis._execute_tool.assert_not_called()
        self.assertFalse(jarvis.speak.called)


if __name__ == "__main__":
    unittest.main()
