import inspect
import unittest
from pathlib import Path

from core.intent_confidence import (
    classify_user_intent,
    normalize_transcript,
    transcript_quality_score,
    validate_tool_call_against_user_text,
)


class TestIntentConfidence(unittest.TestCase):
    def test_high_confidence_web_search_portuguese(self):
        res = classify_user_intent("pesquisa na internet sobre novidades sobre IA")
        self.assertEqual(res["intent"], "web_search")
        self.assertGreater(res["confidence"], 0.7)

    def test_high_confidence_web_search_ai_news(self):
        res = classify_user_intent("quero novidades sobre IA na internet")
        self.assertEqual(res["intent"], "web_search")
        self.assertGreater(res["confidence"], 0.7)

    def test_low_quality_transcript_blocks_action_tool(self):
        res = validate_tool_call_against_user_text(
            "game_updater",
            {"action": "schedule_status"},
            "Ti nha contato esquerdamento?",
        )
        self.assertFalse(res["allow"])
        self.assertIn("clarification", res)
        self.assertIsNotNone(res["clarification"])

    def test_game_updater_requires_game_context(self):
        res = validate_tool_call_against_user_text(
            "game_updater",
            {"action": "update"},
            "agende a atualização do jogo na Steam",
        )
        self.assertTrue(res["allow"])
        self.assertEqual(res["intent"], "game_update")

    def test_game_updater_allows_steam_update(self):
        res = validate_tool_call_against_user_text(
            "game_updater",
            {"action": "update"},
            "atualizar jogo da Steam",
        )
        self.assertTrue(res["allow"])
        self.assertEqual(res["intent"], "game_update")

    def test_game_updater_blocks_vague_schedule_status(self):
        res = validate_tool_call_against_user_text(
            "game_updater",
            {"action": "schedule_status"},
            "agendamento status",
        )
        self.assertFalse(res["allow"])
        self.assertIn(res["intent"], {"unknown", "context_query"})

    def test_open_app_requires_open_app_evidence(self):
        res = validate_tool_call_against_user_text(
            "open_app",
            {"app_name": "Chrome"},
            "abra o Chrome",
        )
        self.assertTrue(res["allow"])
        self.assertEqual(res["intent"], "open_app")

    def test_file_controller_requires_file_evidence(self):
        res = validate_tool_call_against_user_text(
            "file_controller",
            {"action": "read", "path": "README.md"},
            "faça isso",
        )
        self.assertFalse(res["allow"])
        self.assertIn("clarification", res)

    def test_unknown_intent_low_confidence(self):
        res = classify_user_intent("Ti nha contato esquerdamento?")
        self.assertEqual(res["intent"], "unknown")
        self.assertLess(res["confidence"], 0.5)

    def test_short_noise_is_not_false_positive(self):
        res = classify_user_intent("hmm")
        self.assertIn(res["intent"], {"unknown", "context_query"})
        self.assertLess(res["confidence"], 0.7)

    def test_transcript_quality_handles_broken_spacing(self):
        broken = transcript_quality_score("Ti nha contato esquerdamento?")
        clear = transcript_quality_score("pesquisa na internet sobre novidades sobre IA")
        self.assertLess(broken, clear)
        self.assertGreaterEqual(clear, 0.0)
        self.assertLessEqual(clear, 1.0)

    def test_does_not_import_actions_ui_main(self):
        path = Path("core") / "intent_confidence.py"
        source = path.read_text(encoding="utf-8")
        for forbidden in ("import main", "from main", "import ui", "from ui", "import actions", "from actions"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
