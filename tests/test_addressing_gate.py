import unittest

from core.addressing_gate import (
    GateDecision,
    is_addressed_to_jarvis,
    normalize_address_text,
    should_process_user_utterance,
    strip_wake_word,
)


class TestAddressingGate(unittest.TestCase):
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
