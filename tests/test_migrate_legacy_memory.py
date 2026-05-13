import ast
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools.migrate_legacy_memory import (
    apply_privacy_check,
    build_dry_run_report,
    iter_legacy_items,
    load_legacy_memory,
    main,
    map_legacy_item,
    format_report,
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

    def test_iter_legacy_items_supports_list_bucket_for_duplicates(self):
        memory = {
            "preferences": [
                {"key": "favorite_language", "value": "Portuguese"},
                {"key": "favorite_language", "value": "Portuguese"},
            ]
        }
        items = iter_legacy_items(memory)
        self.assertEqual(len(items), 2)

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
            self.assertNotIn("import sqlite3", src)
            self.assertNotIn("memory_engine.writer", src)
            self.assertNotIn("open_db", src)
            self.assertNotIn("init_db", src)
            self.assertNotIn("append_event", src)

    def test_cli_dry_run_success(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", str(legacy_path)])
            self.assertEqual(code, 0)
            self.assertEqual(buf_err.getvalue(), "")

    def test_cli_apply_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", str(legacy_path), "--apply"])
            self.assertEqual(code, 2)
            self.assertIn("not implemented", buf_err.getvalue().lower())

    def test_unknown_category_becomes_review_candidate(self):
        it = iter_legacy_items({"unknown": {"x": {"value": "Y"}}})[0]
        cand = map_legacy_item(it, project="meu-jarvis")
        self.assertEqual(cand.memory_type, "IDEA")
        self.assertEqual(cand.scope, "project:meu-jarvis")
        self.assertTrue(cand.requires_review)
        self.assertTrue(cand.unknown_category)

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

    def test_text_report_does_not_include_candidate_content_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            # Non-secret but sensitive-like value.
            self._write_json(legacy_path, {"notes": {"private_note": {"value": "My private preference text"}}})
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            txt = format_report(report)
            self.assertNotIn("My private preference text", txt)

    def test_text_report_omits_blocked_content(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            token = "sk-THIS_IS_NOT_REAL_BUT_SHOULD_BLOCK_1234567890"
            self._write_json(legacy_path, {"notes": {"api_key": {"value": token}}})
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            txt = format_report(report)
            self.assertNotIn(token, txt)
            self.assertIn("Blocked items (content omitted)", txt)

    def test_json_report_omits_content_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"notes": {"private_note": {"value": "My private preference text"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", str(legacy_path), "--json"])
            self.assertEqual(code, 0)
            out = buf_out.getvalue()
            self.assertNotIn("My private preference text", out)
            self.assertNotIn("\"content\"", out)

    def test_json_include_content_includes_only_non_blocked_content(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            token = "sk-THIS_IS_NOT_REAL_BUT_SHOULD_BLOCK_1234567890"
            self._write_json(
                legacy_path,
                {
                    "preferences": {"favorite_language": {"value": "Portuguese"}},
                    "notes": {"api_key": {"value": token}},
                },
            )
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", str(legacy_path), "--json", "--include-content"])
            self.assertEqual(code, 0)
            out = buf_out.getvalue()
            self.assertIn("Portuguese", out)
            self.assertNotIn(token, out)

    def test_duplicate_candidates_are_marked_and_not_counted_as_migratable(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            # Use list bucket to create duplicates.
            self._write_json(
                legacy_path,
                {
                    "preferences": [
                        {"key": "favorite_language", "value": "Portuguese"},
                        {"key": "favorite_language", "value": "Portuguese"},
                    ]
                },
            )
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            self.assertGreaterEqual(report.duplicate_items, 1)
            dups = [c for c in report.candidates if c.duplicate]
            self.assertTrue(dups)
            # migratable excludes duplicates
            self.assertEqual(
                report.migratable_items,
                sum(1 for c in report.candidates if (not c.blocked) and (not c.duplicate)),
            )

    def test_report_breakdown_by_category_type_scope(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(
                legacy_path,
                {
                    "preferences": {"favorite_language": {"value": "Portuguese"}},
                    "projects": {"meu_jarvis": {"value": "Local assistant project"}},
                },
            )
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            self.assertIn("preferences", report.by_source_category)
            self.assertIn("PREFERENCE", report.by_memory_type)
            self.assertIn("global", report.by_scope)

    def test_missing_file_without_allow_missing_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                build_dry_run_report(missing, project="meu-jarvis", allow_missing=False)

    def test_missing_file_with_allow_missing_returns_empty_report(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            report = build_dry_run_report(missing, project="meu-jarvis", allow_missing=True)
            self.assertTrue(report.missing_source)
            self.assertEqual(report.total_items, 0)
            self.assertEqual(report.migratable_items, 0)
            self.assertEqual(report.blocked_items, 0)
            self.assertEqual(report.review_required_items, 0)
            self.assertEqual(report.duplicate_items, 0)
            self.assertEqual(report.candidates, [])
            self.assertTrue(report.warning)

    def test_cli_missing_file_without_allow_missing_returns_2(self):
        with tempfile.TemporaryDirectory() as td:
            missing = str(Path(td) / "missing.json")
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", missing])
            self.assertEqual(code, 2)
            self.assertIn("not found", buf_err.getvalue().lower())

    def test_cli_missing_file_with_allow_missing_returns_0(self):
        with tempfile.TemporaryDirectory() as td:
            missing = str(Path(td) / "missing.json")
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", missing, "--allow-missing"])
            self.assertEqual(code, 0)
            self.assertEqual(buf_err.getvalue(), "")

    def test_missing_file_text_report_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            report = build_dry_run_report(missing, project="meu-jarvis", allow_missing=True)
            txt = format_report(report)
            self.assertIn("nothing to migrate", txt.lower())
            self.assertNotIn("content", txt.lower())

    def test_missing_file_json_report_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            missing = str(Path(td) / "missing.json")
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", missing, "--allow-missing", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(buf_err.getvalue(), "")
            data = json.loads(buf_out.getvalue())
            self.assertTrue(data.get("missing_source"))
            self.assertTrue(data.get("warning"))
            self.assertEqual(data.get("total_items"), 0)
            self.assertEqual(data.get("candidates"), [])
            # Safe-by-default: should not include any content field.
            self.assertNotIn("content", buf_out.getvalue())

    def test_allow_missing_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            self.assertFalse(missing.exists())
            _ = build_dry_run_report(missing, project="meu-jarvis", allow_missing=True)
            self.assertFalse(missing.exists())

    def test_apply_with_allow_missing_still_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            missing = str(Path(td) / "missing.json")
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", missing, "--allow-missing", "--apply"])
            self.assertEqual(code, 2)
            self.assertIn("apply", buf_err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
