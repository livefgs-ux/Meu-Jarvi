import ast
import json
import tempfile
import unittest
from pathlib import Path

from tools.migrate_legacy_memory import (
    apply_privacy_check,
    build_dry_run_report,
    iter_legacy_items,
    load_legacy_memory,
    main,
    map_legacy_item,
)


class TestMigrateLegacyMemoryDryRun(unittest.TestCase):
    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_load_legacy_memory_reads_explicit_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "legacy.json"
            self._write_json(p, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            loaded = load_legacy_memory(p)
            self.assertIn("preferences", loaded)

    def test_load_legacy_memory_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_legacy_memory(p)

    def test_iter_legacy_items_extracts_known_categories(self):
        memory = {
            "identity": {"name": {"value": "Fabricio"}},
            "preferences": {"favorite_language": {"value": "Portuguese"}},
            "projects": {"meu_jarvis": {"value": "Local assistant project"}},
            "relationships": {"sister_name": {"value": "X"}},
            "wishes": {"travel": {"value": "Japan"}},
            "notes": {"todo": {"value": "Refactor later"}},
        }
        items = iter_legacy_items(memory)
        cats = {i.category for i in items}
        self.assertTrue({"identity", "preferences", "projects", "relationships", "wishes", "notes"}.issubset(cats))

    def test_map_preferences_to_global_preference_candidate(self):
        it = iter_legacy_items({"preferences": {"favorite_language": {"value": "Portuguese"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertEqual(cand.memory_type, "PREFERENCE")
        self.assertEqual(cand.scope, "global")
        self.assertEqual(cand.status, "candidate")
        self.assertFalse(cand.requires_review)

    def test_map_projects_to_project_context_candidate(self):
        it = iter_legacy_items({"projects": {"meu_jarvis": {"value": "Local assistant project"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertEqual(cand.memory_type, "PROJECT_CONTEXT")
        self.assertEqual(cand.scope, "project:meu-jarvis")
        self.assertEqual(cand.project, "meu-jarvis")
        self.assertEqual(cand.status, "candidate")

    def test_identity_requires_review(self):
        it = iter_legacy_items({"identity": {"name": {"value": "Fabricio"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertTrue(cand.requires_review)

    def test_relationships_requires_review(self):
        it = iter_legacy_items({"relationships": {"sister": {"value": "X"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertTrue(cand.requires_review)

    def test_notes_requires_review(self):
        it = iter_legacy_items({"notes": {"todo": {"value": "Something"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertTrue(cand.requires_review)

    def test_privacy_guard_blocks_api_key_like_content(self):
        it = iter_legacy_items({"notes": {"api_key": {"value": "sk-THIS_IS_NOT_REAL_BUT_SHOULD_BLOCK_1234567890"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        checked = apply_privacy_check(cand)
        self.assertTrue(checked.blocked)
        self.assertTrue(checked.block_reason)

    def test_dry_run_report_does_not_write_sqlite_or_data(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})

            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            self.assertGreaterEqual(report.total_items, 1)

            # Must not create any runtime db paths under the temp directory.
            self.assertFalse((td_path / "data" / "jarvis_memory.db").exists())
            self.assertFalse((td_path / "data" / "raw_events.jsonl").exists())

            # The tool itself must not import writer or call create_memory.
            src = (Path(__file__).resolve().parents[1] / "tools" / "migrate_legacy_memory.py").read_text(encoding="utf-8")
            self.assertNotIn("create_memory", src)
            self.assertNotIn("update_memory_status", src)
            self.assertNotIn("archive_memory", src)

    def test_cli_dry_run_success(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            code = main(["--legacy-path", str(legacy_path)])
            self.assertEqual(code, 0)

    def test_cli_apply_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            code = main(["--legacy-path", str(legacy_path), "--apply"])
            self.assertEqual(code, 2)

    def test_unknown_category_becomes_review_candidate(self):
        it = iter_legacy_items({"unknown": {"x": {"value": "Y"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertEqual(cand.memory_type, "IDEA")
        self.assertEqual(cand.scope, "project:meu-jarvis")
        self.assertTrue(cand.requires_review)

    def test_empty_values_are_ignored(self):
        items = iter_legacy_items({"preferences": {"empty": {"value": ""}, "blank": ""}})
        self.assertEqual(items, [])

    def test_module_imports_do_not_include_writer(self):
        src_path = Path(__file__).resolve().parents[1] / "tools" / "migrate_legacy_memory.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "memory_engine.writer")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "memory_engine.writer")


if __name__ == "__main__":
    unittest.main()

