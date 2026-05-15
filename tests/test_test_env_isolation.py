import os
import unittest
from pathlib import Path


class TestTestEnvIsolation(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "test_clean_env.ps1"

    def test_clean_env_script_exists(self):
        self.assertTrue(self.script.exists())

    def test_clean_env_script_mentions_required_jarvis_vars(self):
        text = self.script.read_text(encoding="utf-8")
        for var in [
            "JARVIS_LIVE_RESILIENCE",
            "JARVIS_CONCURRENT_TASK_RUNTIME",
            "JARVIS_SPEECH_CONTROL",
            "JARVIS_ACTION_DECISION_GATE",
            "JARVIS_TOOL_CALL_GATE",
            "JARVIS_MEMORY_DECISION_POLICY",
            "JARVIS_MEMORY_WRITE_BACKEND",
            "JARVIS_READONLY_MEMORY",
        ]:
            self.assertIn(var, text)

    def test_script_runs_unittest_discover_tests(self):
        text = self.script.read_text(encoding="utf-8")
        self.assertIn(".\\.venv\\Scripts\\python.exe -m unittest discover tests", text)

    def test_script_does_not_delete_project_files(self):
        text = self.script.read_text(encoding="utf-8")
        for forbidden in ["data/", "config/api_keys.json", "memory/long_term.json"]:
            self.assertNotIn(forbidden, text)

    def test_script_uses_venv_python(self):
        text = self.script.read_text(encoding="utf-8")
        self.assertIn(".\\.venv\\Scripts\\python.exe", text)


if __name__ == "__main__":
    unittest.main()
