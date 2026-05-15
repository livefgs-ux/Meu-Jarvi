import unittest
from pathlib import Path

from core.speech_control import SpeechCommandType, detect_speech_control_command


class TestSpeechControl(unittest.TestCase):
    def test_detect_interrupt_speech_portuguese(self):
        result = detect_speech_control_command("Para de falar, Jarvis.")
        self.assertEqual(result["command_type"], SpeechCommandType.INTERRUPT_SPEECH.value)

    def test_detect_interrupt_speech_english(self):
        result = detect_speech_control_command("stop talking now")
        self.assertEqual(result["command_type"], SpeechCommandType.INTERRUPT_SPEECH.value)

    def test_detect_interrupt_speech_german_simple(self):
        result = detect_speech_control_command("halt")
        self.assertEqual(result["command_type"], SpeechCommandType.INTERRUPT_SPEECH.value)

    def test_detect_temporary_silence(self):
        result = detect_speech_control_command("fica quieto por um tempo")
        self.assertEqual(result["command_type"], SpeechCommandType.TEMPORARY_SILENCE.value)

    def test_detect_resume_speech(self):
        result = detect_speech_control_command("pode falar")
        self.assertEqual(result["command_type"], SpeechCommandType.RESUME_SPEECH.value)

    def test_detect_cancel_task_is_not_interrupt_speech(self):
        result = detect_speech_control_command("cancela essa tarefa")
        self.assertEqual(result["command_type"], SpeechCommandType.CANCEL_TASK.value)

    def test_detect_concise_mode(self):
        result = detect_speech_control_command("seja direto")
        self.assertEqual(result["command_type"], SpeechCommandType.CONCISE_MODE.value)

    def test_detect_normal_mode(self):
        result = detect_speech_control_command("volta ao normal")
        self.assertEqual(result["command_type"], SpeechCommandType.NORMAL_MODE.value)

    def test_short_noise_is_not_false_positive(self):
        for noise in ("stopper", "paralelepipedo", "hello there", "random noise"):
            with self.subTest(noise=noise):
                result = detect_speech_control_command(noise)
                self.assertEqual(result["command_type"], SpeechCommandType.NONE.value)

    def test_speech_control_does_not_import_main_ui_actions(self):
        src = Path("core/speech_control.py").read_text(encoding="utf-8")
        banned = ("import main", "from main", "import ui", "from ui", "import actions", "from actions")
        for needle in banned:
            self.assertNotIn(needle, src)
