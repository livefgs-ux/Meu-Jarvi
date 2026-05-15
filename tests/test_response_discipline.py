import unittest
from pathlib import Path

from core.response_discipline import (
    concise_clarification,
    enforce_portuguese_local_reply,
    is_explicit_language_change_request,
    portuguese_default_instruction,
    tool_truthfulness_instruction,
)


class TestResponseDiscipline(unittest.TestCase):
    def test_default_language_is_portuguese(self):
        self.assertIn("português brasileiro", portuguese_default_instruction().lower())

    def test_explicit_language_change_detected(self):
        self.assertTrue(is_explicit_language_change_request("Responda em inglês, por favor."))

    def test_no_english_generic_reply(self):
        text = enforce_portuguese_local_reply("Understood. Is there anything else I can assist you with?")
        self.assertIn("Entendido", text)
        self.assertNotIn("assist you with", text.lower())

    def test_clarification_is_portuguese(self):
        text = concise_clarification("qual ação?")
        self.assertIn("Não entendi", text)
        self.assertNotIn("understood", text.lower())

    def test_tool_truthfulness_instruction_mentions_no_fake_search(self):
        text = tool_truthfulness_instruction().lower()
        self.assertIn("nunca diga que pesquisou", text)
        self.assertIn("não prometa pesquisa", text)

    def test_response_discipline_does_not_import_actions_ui_main(self):
        path = Path("core") / "response_discipline.py"
        source = path.read_text(encoding="utf-8")
        for forbidden in ("import main", "from main", "import ui", "from ui", "import actions", "from actions"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
