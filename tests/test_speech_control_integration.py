import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class TestSpeechControlIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()
        sys.modules["sounddevice"] = MagicMock()
        self.main = importlib.import_module("main")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def _make_jarvis(self):
        ui = MagicMock()
        jarvis = self.main.JarvisLive(ui)
        jarvis._loop = MagicMock()
        jarvis.session = MagicMock()
        jarvis.session.send_client_content = MagicMock()
        return jarvis

    async def test_feature_flag_off_preserves_existing_flow(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "false"}, clear=False), patch.object(
            self.main.asyncio, "run_coroutine_threadsafe"
        ) as run_threadsafe:
            jarvis._on_text_command("stop")

        run_threadsafe.assert_called_once()
        self.assertFalse(jarvis._suppress_audio_until_turn_complete)

    async def test_text_stop_command_does_not_send_to_gemini(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main.asyncio, "run_coroutine_threadsafe"
        ) as run_threadsafe:
            jarvis._on_text_command("stop")

        run_threadsafe.assert_not_called()
        self.assertTrue(jarvis._suppress_audio_until_turn_complete)

    async def test_text_stop_command_stops_audio_queue(self):
        jarvis = self._make_jarvis()
        jarvis.audio_in_queue = asyncio.Queue()
        jarvis.audio_in_queue.put_nowait(b"chunk-1")
        jarvis.audio_in_queue.put_nowait(b"chunk-2")

        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False):
            handled = jarvis._handle_speech_control_command("para", source="text")

        self.assertTrue(handled)
        self.assertTrue(jarvis.audio_in_queue.empty())
        self.assertTrue(jarvis._suppress_audio_until_turn_complete)

    async def test_stop_speech_does_not_cancel_running_task(self):
        jarvis = self._make_jarvis()
        runtime = MagicMock()
        runtime.cancel = MagicMock()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main, "get_task_runtime", return_value=runtime
        ):
            jarvis._handle_speech_control_command("cala a boca", source="text")

        runtime.cancel.assert_not_called()
        self.assertFalse(jarvis._speech_control_state.is_silenced)

    async def test_temporary_silence_prevents_speak(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main.asyncio, "run_coroutine_threadsafe"
        ) as run_threadsafe:
            jarvis._handle_speech_control_command("fica quieto por um tempo", source="text")
            jarvis.speak("Hello, sir.")

        run_threadsafe.assert_not_called()
        self.assertTrue(jarvis._speech_control_state.is_silenced)

    async def test_resume_speech_allows_speak_again(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main.asyncio, "run_coroutine_threadsafe"
        ) as run_threadsafe:
            jarvis._handle_speech_control_command("fica quieto por um tempo", source="text")
            jarvis.speak("Should be suppressed.")
            jarvis._handle_speech_control_command("pode falar", source="text")
            jarvis.speak("Now speak again.")

        self.assertEqual(run_threadsafe.call_count, 1)
        self.assertFalse(jarvis._speech_control_state.is_silenced)

    async def test_concise_mode_sets_state(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main, "_speech_control_enabled", return_value=True
        ):
            jarvis._handle_speech_control_command("seja direto", source="text")

        self.assertTrue(jarvis._speech_control_state.concise_mode)
        self.assertTrue(jarvis._apply_concise_hint("Oi").startswith("Responda de forma curta e direta."))

    async def test_cancel_task_command_not_treated_as_speech_stop(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False):
            handled = jarvis._handle_speech_control_command("cancela essa tarefa", source="text")

        self.assertTrue(handled)
        self.assertFalse(jarvis._speech_control_state.is_silenced)
        self.assertFalse(jarvis._suppress_audio_until_turn_complete)

    async def test_audio_suppression_until_turn_complete(self):
        jarvis = self._make_jarvis()
        jarvis.audio_in_queue = asyncio.Queue()
        jarvis._turn_done_event = asyncio.Event()
        jarvis._suppress_audio_until_turn_complete = True

        response = types.SimpleNamespace(
            data=b"abc",
            server_content=types.SimpleNamespace(
                input_transcription=None,
                output_transcription=None,
                turn_complete=True,
            ),
            tool_call=None,
        )

        async def one_response():
            yield response

        jarvis.session.receive = MagicMock(side_effect=[one_response(), RuntimeError("end")])

        with patch("builtins.print"), self.assertRaises(RuntimeError):
            await jarvis._receive_audio()

        self.assertTrue(jarvis.audio_in_queue.empty())
        self.assertFalse(jarvis._suppress_audio_until_turn_complete)

    async def test_journal_records_speech_events(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main, "record_event"
        ) as record_event:
            jarvis._handle_speech_control_command("para", source="text")
            jarvis._handle_speech_control_command("seja direto", source="text")

        event_types = [call.args[0] for call in record_event.call_args_list]
        self.assertIn("speech_control_detected", event_types)
        self.assertIn("speech_interrupted", event_types)
        self.assertIn("concise_mode_enabled", event_types)

    async def test_existing_behavior_preserved_when_speech_control_fails(self):
        jarvis = self._make_jarvis()
        with patch.dict(os.environ, {"JARVIS_SPEECH_CONTROL": "true"}, clear=False), patch.object(
            self.main, "detect_speech_control_command", side_effect=Exception("boom")
        ), patch.object(self.main.asyncio, "run_coroutine_threadsafe") as run_threadsafe:
            jarvis._on_text_command("hello there")

        run_threadsafe.assert_called_once()
