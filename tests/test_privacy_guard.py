import tempfile
import unittest
from pathlib import Path

from memory_engine.privacy_guard import check_content_safe
from memory_engine.writer import create_memory


class PrivacyGuardTests(unittest.TestCase):
    def test_blocks_secret_like_content(self):
        result = check_content_safe("API_KEY=supersecretvalue123456789")
        self.assertFalse(result.allowed)

    def test_writer_refuses_secret_like_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                create_memory(
                    "PROJECT_CONTEXT",
                    "project:test",
                    "password = hunter2-but-long-enough",
                    db_path=root / "test.db",
                    event_log_path=root / "events.jsonl",
                )

    def test_allows_non_secret_content(self):
        result = check_content_safe("Do not mix project context with global rules.")
        self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
