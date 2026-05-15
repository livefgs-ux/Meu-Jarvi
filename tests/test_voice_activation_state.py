import unittest
from unittest.mock import patch

from core.voice_activation_state import (
    arm_voice_activation,
    clear_voice_activation,
    consume_voice_activation,
    get_voice_activation_state,
    is_voice_activation_active,
)


class TestVoiceActivationState(unittest.TestCase):
    def setUp(self):
        clear_voice_activation()

    def tearDown(self):
        clear_voice_activation()

    def test_wake_word_only_arms_window(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            state = arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
            self.assertEqual(state.matched_wake_word, "jarvis")
            self.assertEqual(state.last_activation_text, "Jarvis")
            self.assertAlmostEqual(state.armed_until, 110.0, places=2)
            self.assertTrue(is_voice_activation_active())

    def test_followup_allowed_while_armed(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        with patch("core.voice_activation_state.time.time", return_value=105.0):
            self.assertTrue(consume_voice_activation())

    def test_followup_consumes_window(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
            self.assertTrue(consume_voice_activation())
            self.assertFalse(get_voice_activation_state().armed_until > 0)

    def test_followup_blocked_after_timeout(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        with patch("core.voice_activation_state.time.time", return_value=111.0):
            self.assertFalse(is_voice_activation_active())
            self.assertFalse(consume_voice_activation())
        self.assertFalse(get_voice_activation_state().armed_until > 0)

    def test_clear_activation_blocks_followup(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        clear_voice_activation()
        self.assertFalse(is_voice_activation_active())
        self.assertFalse(consume_voice_activation())

    def test_multiple_wake_words_refresh_window(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            first = arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        with patch("core.voice_activation_state.time.time", return_value=105.0):
            second = arm_voice_activation("charles", timeout_seconds=10.0, activation_text="Charles")
        self.assertGreater(second.armed_until, first.armed_until)
        self.assertEqual(second.matched_wake_word, "charles")
        self.assertEqual(get_voice_activation_state().last_activation_text, "Charles")


if __name__ == "__main__":
    unittest.main()
