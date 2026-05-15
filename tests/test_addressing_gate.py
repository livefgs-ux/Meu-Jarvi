import unittest
from unittest.mock import patch

from core.addressing_gate import (
    GateDecision,
    is_addressed_to_jarvis,
    is_meaningful_followup,
    normalize_address_text,
    should_process_audio_utterance,
    should_process_user_utterance,
    strip_wake_word,
)
from core.voice_activation_state import (
    append_followup_fragment,
    arm_voice_activation,
    clear_followup_buffer,
    clear_voice_activation,
    flush_followup_buffer_if_ready,
    get_followup_buffer,
    get_voice_activation_state,
)


class TestAddressingGate(unittest.TestCase):
    def setUp(self):
        clear_voice_activation()
        clear_followup_buffer()

    def test_jarvis_prefix_allows(self):
        decision = should_process_user_utterance("Jarvis, abre o VS Code")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.stripped_text, "abre o VS Code")
        self.assertEqual(decision.matched_wake_word, "jarvis")

    def test_charles_prefix_allows(self):
        decision = should_process_user_utterance("Charles, pesquisa novidades sobre IA")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.stripped_text, "pesquisa novidades sobre IA")
        self.assertEqual(decision.matched_wake_word, "charles")

    def test_meu_jarvis_prefix_allows(self):
        decision = should_process_user_utterance("Meu Jarvis, abre o navegador")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.stripped_text, "abre o navegador")
        self.assertEqual(decision.matched_wake_word, "meu jarvis")

    def test_no_wake_word_blocks_audio(self):
        decision = should_process_user_utterance("abre o VS Code")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "not_addressed")

    def test_text_input_can_be_allowed_without_wake_word(self):
        decision = should_process_user_utterance("abre o VS Code", mic_mode=False)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.stripped_text, "abre o VS Code")

    def test_strip_wake_word_removes_name(self):
        self.assertEqual(strip_wake_word("Jarvis, abre o VS Code"), "abre o VS Code")

    def test_case_and_accents_are_normalized(self):
        self.assertTrue(is_addressed_to_jarvis("JÁRVIS, abre o navegador"))
        self.assertTrue(is_addressed_to_jarvis("Ei JARVIS, pesquisa algo"))
        self.assertTrue(is_addressed_to_jarvis("ChArLeS, você consegue pesquisar?"))

    def test_does_not_match_inside_word(self):
        self.assertFalse(is_addressed_to_jarvis("jarvisx abre o VS Code"))
        self.assertFalse(is_addressed_to_jarvis("meujarvis abre o VS Code"))
        self.assertFalse(is_addressed_to_jarvis("charlesx, abre o VS Code"))

    def test_punctuation_is_tolerated(self):
        decision = should_process_user_utterance("Jarvis?!   abre... o   navegador!")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.stripped_text, "abre o navegador")

    def test_empty_text_blocks_audio(self):
        decision = should_process_user_utterance("")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "empty_text")

    def test_wake_word_only_does_not_call_model(self):
        decision = should_process_audio_utterance("Jarvis")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "wake_word_only")
        self.assertEqual(decision.stripped_text, "")

    def test_online_after_wake_does_not_consume_window(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("online")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "armed_non_meaningful")
        self.assertTrue(get_voice_activation_state().armed_until > 0)

    def test_noise_after_wake_does_not_consume_window(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("sim")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "armed_non_meaningful")
        self.assertTrue(get_voice_activation_state().armed_until > 0)

    def test_listening_phrase_after_wake_does_not_consume_window(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("tá ouvindo")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "armed_non_meaningful")
        self.assertTrue(get_voice_activation_state().armed_until > 0)

    def test_meaningful_followup_consumes_window(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        self.assertTrue(is_meaningful_followup("pesquisa novidades sobre IA"))
        decision = should_process_audio_utterance("pesquisa novidades sobre IA")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "armed_followup")
        self.assertFalse(get_voice_activation_state().armed_until > 0)

    def test_short_command_open_app_after_wake_is_accepted(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("abre o Cursor")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "armed_followup")
        self.assertEqual(decision.stripped_text, "abre o Cursor")

    def test_fragmented_followup_can_be_buffered(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("abre")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "armed_fragment")
        append_followup_fragment("abre")
        self.assertEqual(get_followup_buffer(), ("abre",))

    def test_buffer_expires_without_calling_model(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            append_followup_fragment("abre")
        with patch("core.addressing_gate.time.time", return_value=102.0):
            expired = flush_followup_buffer_if_ready(now=102.0)
        self.assertEqual(expired, "abre")
        self.assertEqual(get_followup_buffer(), ())

    def test_wake_word_only_arms_window(self):
        decision = should_process_audio_utterance("Jarvis")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "wake_word_only")
        self.assertEqual(decision.stripped_text, "")
        self.assertEqual(decision.matched_wake_word, "jarvis")
        state = get_voice_activation_state()
        self.assertTrue(state.armed_until > 0)
        self.assertEqual(state.matched_wake_word, "jarvis")
        self.assertEqual(state.last_activation_text, "Jarvis")

    def test_followup_allowed_while_armed(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("abre o Cursor")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "armed_followup")
        self.assertEqual(decision.stripped_text, "abre o Cursor")
        self.assertEqual(decision.matched_wake_word, "jarvis")

    def test_followup_consumes_window(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        decision = should_process_audio_utterance("abre o Cursor")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "armed_followup")
        self.assertFalse(get_voice_activation_state().armed_until > 0)

    def test_followup_blocked_after_timeout(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        with patch("core.addressing_gate.time.time", return_value=111.0):
            decision = should_process_audio_utterance("abre o Cursor")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "armed_expired")
        self.assertFalse(get_voice_activation_state().armed_until > 0)

    def test_wake_word_with_command_does_not_need_followup(self):
        decision = should_process_audio_utterance("Jarvis, abre o Cursor")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "wake_word_matched")
        self.assertEqual(decision.stripped_text, "abre o Cursor")
        self.assertFalse(get_voice_activation_state().armed_until > 0)

    def test_no_wake_word_no_armed_blocks(self):
        decision = should_process_audio_utterance("abre o Cursor")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "not_addressed")

    def test_clear_activation_blocks_followup(self):
        arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        clear_voice_activation()
        decision = should_process_audio_utterance("abre o Cursor")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "not_addressed")

    def test_multiple_wake_words_refresh_window(self):
        with patch("core.voice_activation_state.time.time", return_value=100.0):
            first = arm_voice_activation("jarvis", timeout_seconds=10.0, activation_text="Jarvis")
        with patch("core.voice_activation_state.time.time", return_value=105.0):
            second = arm_voice_activation("charles", timeout_seconds=10.0, activation_text="Charles")
        self.assertGreater(second.armed_until, first.armed_until)
        self.assertEqual(second.matched_wake_word, "charles")

    def test_does_not_import_main_ui_actions(self):
        with open("core/addressing_gate.py", "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("import main", src)
        self.assertNotIn("from main", src)
        self.assertNotIn("import ui", src)
        self.assertNotIn("from ui", src)
        self.assertNotIn("import actions", src)
        self.assertNotIn("from actions", src)


if __name__ == "__main__":
    unittest.main()
