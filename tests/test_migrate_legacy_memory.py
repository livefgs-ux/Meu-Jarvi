import ast
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from memory_engine.retriever import search_memories

from tools.migrate_legacy_memory import (
    apply_privacy_check,
    apply_report,
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

    def test_load_legacy_memory_reads_utf8_bom_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "legacy_bom.json"
            p.write_text(
                json.dumps({"preferences": {"favorite_language": {"value": "Portuguese"}}}),
                encoding="utf-8-sig",
            )
            loaded = load_legacy_memory(p)
            self.assertIn("preferences", loaded)

    def test_invalid_json_with_bom_still_fails_clearly(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad_bom.json"
            p.write_text("{not valid json", encoding="utf-8-sig")
            with self.assertRaises(ValueError) as ctx:
                load_legacy_memory(p)
            self.assertIn("Invalid legacy JSON", str(ctx.exception))

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

            # Phase 2A allows create_memory, but still forbids direct sqlite/manual DB access
            # and non-create writer operations.
            src = (Path(__file__).resolve().parents[1] / "tools" / "migrate_legacy_memory.py").read_text(encoding="utf-8")
            self.assertNotIn("update_memory_status", src)
            self.assertNotIn("archive_memory", src)
            self.assertNotIn("import sqlite3", src)
            self.assertNotIn("open_db", src)
            self.assertNotIn("init_db", src)
            self.assertNotIn("append_event", src)
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

    def test_apply_requires_db_path(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--event-log-path",
                        str(Path(td) / "events.jsonl"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("db-path", buf_err.getvalue().lower())
            self.assertIn("refusing to write", buf_err.getvalue().lower())

    def test_apply_requires_event_log_path(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        str(Path(td) / "mem.db"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("event-log-path", buf_err.getvalue().lower())
            self.assertIn("refusing to write", buf_err.getvalue().lower())

    def test_apply_requires_confirm_apply(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = Path(td) / "mem.db"
            log_path = Path(td) / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("confirm-apply", buf_err.getvalue().lower())
            self.assertFalse(db_path.exists())
            self.assertFalse(log_path.exists())

    def test_apply_same_db_and_log_path_message_clear(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            same = str(Path(td) / "same.path")
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        same,
                        "--event-log-path",
                        same,
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("must be different files", buf_err.getvalue().lower())

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

    def test_no_forbidden_imports_after_apply_mode(self):
        src_path = Path(__file__).resolve().parents[1] / "tools" / "migrate_legacy_memory.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module or "", {"sqlite3"})
                if node.module == "memory_engine.writer":
                    self.assertEqual([a.name for a in node.names], ["create_memory"])
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "sqlite3")

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
            self.assertIn("Blocked Items (content omitted)", txt)

    def test_text_report_includes_apply_summary_counts(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
            txt = format_report(applied)
            self.assertIn("Summary", txt)
            self.assertIn("- Applied:", txt)
            self.assertIn("- Skipped:", txt)

    def test_text_report_lists_skipped_reasons_without_content(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"identity": {"name": {"value": "My private preference text"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
            txt = format_report(applied)
            self.assertIn("Skipped Items", txt)
            self.assertIn("requires_review", txt)
            self.assertNotIn("My private preference text", txt)

    def test_text_report_lists_unknown_categories_without_content(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"weird_category": {"k": {"value": "Secret-ish but not blocked"}}})
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            txt = format_report(report)
            self.assertIn("Unknown Categories", txt)
            self.assertIn("Unknown Category Items", txt)
            self.assertNotIn("Secret-ish but not blocked", txt)

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

    def test_json_report_includes_apply_counts(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            data = json.loads(buf_out.getvalue())
            self.assertIn("applied_items", data)
            self.assertIn("skipped_items", data)
            self.assertTrue(data.get("apply_requested"))
            self.assertTrue(data.get("apply_confirmed"))
            self.assertTrue(data.get("apply_target_db"))
            self.assertTrue(data.get("apply_event_log"))
            self.assertNotIn("content", buf_out.getvalue())

    def test_json_report_includes_breakdowns(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(["--legacy-path", str(legacy_path), "--json"])
            self.assertEqual(code, 0)
            data = json.loads(buf_out.getvalue())
            self.assertIn("breakdown_by_source_category", data)
            self.assertIn("breakdown_by_memory_type", data)
            self.assertIn("breakdown_by_scope", data)

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
            self.assertIn("summary", txt.lower())

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

    def test_apply_rejects_real_default_db_path(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        "data/jarvis_memory.db",
                        "--event-log-path",
                        str(Path(td) / "events.jsonl"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("refusing to write", buf_err.getvalue().lower())
            self.assertIn("data/jarvis_memory.db", buf_err.getvalue().lower())

    def test_apply_rejects_real_default_event_log_path(self):
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        str(Path(td) / "mem.db"),
                        "--event-log-path",
                        "data/raw_events.jsonl",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("refusing to write", buf_err.getvalue().lower())
            self.assertIn("data/raw_events.jsonl", buf_err.getvalue().lower())

    def test_apply_writes_to_temp_sqlite_only_and_retriever_can_read(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"

            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
            self.assertGreaterEqual(applied.applied_items, 1)
            self.assertTrue(db_path.exists())
            self.assertTrue(log_path.exists())

            rows = search_memories(db_path=db_path, limit=20)
            self.assertTrue(rows)

    def test_apply_text_report_includes_apply_target_metadata_without_content(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                    ]
                )
            self.assertEqual(code, 0)
            out = buf_out.getvalue()
            self.assertIn("Apply target DB", out)
            self.assertIn("Apply event log", out)
            self.assertNotIn("Portuguese", out)

    def test_apply_skips_blocked_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            token = "sk-THIS_IS_NOT_REAL_BUT_SHOULD_BLOCK_1234567890"
            self._write_json(legacy_path, {"notes": {"api_key": {"value": token}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"

            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=True)
            self.assertEqual(applied.applied_items, 0)
            self.assertGreaterEqual(applied.skipped_items, 1)

    def test_apply_skips_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(
                legacy_path,
                {"preferences": [{"key": "favorite_language", "value": "Portuguese"}, {"key": "favorite_language", "value": "Portuguese"}]},
            )
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"

            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
            self.assertEqual(applied.applied_items, 1)
            self.assertGreaterEqual(applied.skipped_items, 1)

    def test_apply_skips_review_required_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"identity": {"name": {"value": "Fabricio"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"

            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
            self.assertEqual(applied.applied_items, 0)
            self.assertGreaterEqual(applied.skipped_items, 1)
            self.assertTrue(any(c.skip_reason == "requires_review" for c in applied.candidates))

    def test_apply_include_review_applies_review_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"identity": {"name": {"value": "Fabricio"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"

            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=True)
            self.assertEqual(applied.applied_items, 1)

    def test_apply_allow_missing_does_not_create_db_or_log(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            missing_legacy = td_path / "missing.json"
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(missing_legacy),
                        "--allow-missing",
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertFalse(db_path.exists())
            self.assertFalse(log_path.exists())
            self.assertIn("nothing to migrate", buf_out.getvalue().lower())

    def test_apply_allow_missing_still_requires_confirm_apply(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            missing_legacy = td_path / "missing.json"
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(missing_legacy),
                        "--allow-missing",
                        "--apply",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("confirm-apply", buf_err.getvalue().lower())
            self.assertFalse(db_path.exists())
            self.assertFalse(log_path.exists())

    def test_apply_never_creates_legacy_long_term(self):
        repo_root = Path(__file__).resolve().parents[1]
        legacy_long_term = repo_root / "memory" / "long_term.json"
        self.assertFalse(legacy_long_term.exists())
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            _ = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
        self.assertFalse(legacy_long_term.exists())

    def test_json_apply_report_omits_content_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            self._write_json(legacy_path, {"preferences": {"favorite_language": {"value": "Portuguese"}}})
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertNotIn("\"content\"", buf_out.getvalue())

    def test_json_apply_include_content_still_hides_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            token = "sk-THIS_IS_NOT_REAL_BUT_SHOULD_BLOCK_1234567890"
            self._write_json(
                legacy_path,
                {
                    "preferences": {"favorite_language": {"value": "Portuguese"}},
                    "notes": {"api_key": {"value": token}},
                },
            )
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main(
                    [
                        "--legacy-path",
                        str(legacy_path),
                        "--apply",
                        "--confirm-apply",
                        "--include-review",
                        "--db-path",
                        str(db_path),
                        "--event-log-path",
                        str(log_path),
                        "--json",
                        "--include-content",
                    ]
                )
            self.assertEqual(code, 0)
            out = buf_out.getvalue()
            self.assertIn("Portuguese", out)
            self.assertNotIn(token, out)

    def test_apply_report_tracks_skip_reason_counts(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            legacy_path = td_path / "legacy.json"
            token = "sk-THIS_IS_NOT_REAL_BUT_SHOULD_BLOCK_1234567890"
            self._write_json(
                legacy_path,
                {
                    "preferences": [{"key": "favorite_language", "value": "Portuguese"}, {"key": "favorite_language", "value": "Portuguese"}],
                    "notes": {"api_key": {"value": token}},
                    "identity": {"name": {"value": "Fabricio"}},
                },
            )
            db_path = td_path / "mem.db"
            log_path = td_path / "events.jsonl"
            report = build_dry_run_report(legacy_path, project="meu-jarvis")
            applied = apply_report(report, db_path=db_path, event_log_path=log_path, include_review=False)
            # Expect at least one skipped due to blocked, duplicate, and requires_review.
            reasons = {c.skip_reason for c in applied.candidates if c.skipped}
            self.assertIn("blocked", reasons)
            self.assertIn("duplicate", reasons)
            self.assertIn("requires_review", reasons)

    def test_direct_script_execution_allow_missing(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            self.assertFalse(missing.exists())
            cmd = [
                sys.executable,
                str(repo_root / "tools" / "migrate_legacy_memory.py"),
                "--legacy-path",
                str(missing),
                "--project",
                "meu-jarvis",
                "--allow-missing",
            ]
            proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("nothing to migrate", proc.stdout.lower())
            self.assertFalse(missing.exists())

    def test_module_execution_allow_missing(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            self.assertFalse(missing.exists())
            cmd = [
                sys.executable,
                "-m",
                "tools.migrate_legacy_memory",
                "--legacy-path",
                str(missing),
                "--project",
                "meu-jarvis",
                "--allow-missing",
            ]
            proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("nothing to migrate", proc.stdout.lower())
            self.assertFalse(missing.exists())

    def test_direct_script_execution_without_allow_missing_returns_2(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            self.assertFalse(missing.exists())
            cmd = [
                sys.executable,
                str(repo_root / "tools" / "migrate_legacy_memory.py"),
                "--legacy-path",
                str(missing),
                "--project",
                "meu-jarvis",
            ]
            proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("not found", (proc.stderr or proc.stdout).lower())
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
