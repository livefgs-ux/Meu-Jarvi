import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from brain.master_agent import JarvisBrain


DEFAULT_DB = Path("data") / "jarvis_memory.db"
DEFAULT_JSONL = Path("data") / "raw_events.jsonl"


def _file_signature(path: Path):
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@contextmanager
def _temporary_cwd(path: Path):
    import os

    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class BrainBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db_signature = _file_signature(DEFAULT_DB)
        self.jsonl_signature = _file_signature(DEFAULT_JSONL)

    def tearDown(self):
        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)

    def test_default_analyze_request_does_not_create_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            isolated_root = Path(tmp)
            with _temporary_cwd(isolated_root):
                brain = JarvisBrain()
                result = brain.analyze_request("explain the memory architecture")

                self.assertEqual(result["mode"], "Memory Engineer")
                self.assertFalse(DEFAULT_DB.exists())
                self.assertFalse(DEFAULT_JSONL.exists())

    def test_default_recall_does_not_create_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            isolated_root = Path(tmp)
            with _temporary_cwd(isolated_root):
                brain = JarvisBrain()
                result = brain.recall(project="Meu-Jarvi", query="memory")

                self.assertEqual(result["global_rules"], [])
                self.assertEqual(result["project_context"], [])
                self.assertEqual(result["matching_memories"], [])
                self.assertFalse(DEFAULT_DB.exists())
                self.assertFalse(DEFAULT_JSONL.exists())

    def test_default_analyze_request_does_not_modify_real_runtime_data_from_repo_root(self):
        brain = JarvisBrain()
        result = brain.analyze_request("explain the memory architecture")

        self.assertEqual(result["mode"], "Memory Engineer")
        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)

    def test_default_recall_does_not_modify_real_runtime_data_from_repo_root(self):
        brain = JarvisBrain()
        brain.recall(project="Meu-Jarvi", query="memory")

        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)

    def test_explicit_paths_create_only_temp_memory_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temp_db = root / "explicit_memory.db"
            temp_jsonl = root / "explicit_events.jsonl"
            brain = JarvisBrain(db_path=temp_db, event_log_path=temp_jsonl)

            brain.remember(
                "GLOBAL_RULE",
                "global",
                "Runtime integration must be explicit.",
                status="validated",
            )

            self.assertTrue(temp_db.exists())
            self.assertTrue(temp_jsonl.exists())
            self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
            self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)


if __name__ == "__main__":
    unittest.main()
