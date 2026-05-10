import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools.memory_cli import main


DEFAULT_DB = Path("data") / "jarvis_memory.db"
DEFAULT_JSONL = Path("data") / "raw_events.jsonl"


def _file_signature(path: Path):
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class MemoryCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "cli_memory.db"
        self.events_path = root / "cli_events.jsonl"
        self.db_signature = _file_signature(DEFAULT_DB)
        self.jsonl_signature = _file_signature(DEFAULT_JSONL)

    def tearDown(self):
        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)
        self.tmp.cleanup()

    def run_cli(self, args):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def run_cli_subprocess(self, args):
        return subprocess.run(
            args,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_init_creates_db_only_at_explicit_temp_path(self):
        code, out, err = self.run_cli(["init", "--db", str(self.db_path), "--events", str(self.events_path)])

        self.assertEqual(code, 0, err)
        self.assertTrue(self.db_path.exists())
        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertIn("Initialized memory database", out)

    def test_add_valid_global_rule_works(self):
        code, out, err = self.run_cli([
            "add",
            "--type", "GLOBAL_RULE",
            "--scope", "global",
            "--content", "Do not mix global rules with project context.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertEqual(code, 0, err)
        self.assertTrue(self.db_path.exists())
        self.assertTrue(self.events_path.exists())
        self.assertIn("Created memory ID:", out)

    def test_add_invalid_project_context_global_fails_without_events(self):
        code, out, err = self.run_cli([
            "add",
            "--type", "PROJECT_CONTEXT",
            "--scope", "global",
            "--content", "Meu-Jarvi uses a local memory CLI.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertEqual(code, 2)
        self.assertIn("cannot use scope='global'", err)
        self.assertFalse(self.db_path.exists())
        self.assertFalse(self.events_path.exists())

    def test_add_secret_like_content_fails(self):
        code, out, err = self.run_cli([
            "add",
            "--type", "GLOBAL_RULE",
            "--scope", "global",
            "--content", "API_KEY=supersecretvalue123456789",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertEqual(code, 2)
        self.assertIn("secret or credential", err)

    def test_list_returns_saved_memory(self):
        self.run_cli([
            "add",
            "--type", "GLOBAL_RULE",
            "--scope", "global",
            "--content", "List command should show this memory.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        code, out, err = self.run_cli(["list", "--scope", "global", "--db", str(self.db_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("GLOBAL_RULE", out)
        self.assertIn("List command should show this memory.", out)

    def test_search_returns_matching_memory(self):
        self.run_cli([
            "add",
            "--type", "PROJECT_CONTEXT",
            "--scope", "project:Meu-Jarvi",
            "--project", "Meu-Jarvi",
            "--content", "Python 3.12 is used in this test context.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        code, out, err = self.run_cli(["search", "Python 3.12", "--project", "Meu-Jarvi", "--db", str(self.db_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("Python 3.12", out)

    def test_context_shows_global_rules_and_project_context(self):
        self.run_cli([
            "add",
            "--type", "GLOBAL_RULE",
            "--scope", "global",
            "--content", "Context command shows global rules.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.run_cli([
            "add",
            "--type", "PROJECT_CONTEXT",
            "--scope", "project:Meu-Jarvi",
            "--project", "Meu-Jarvi",
            "--content", "Context command shows project context.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        code, out, err = self.run_cli(["context", "--project", "Meu-Jarvi", "--db", str(self.db_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("Global Rules", out)
        self.assertIn("Project Context", out)
        self.assertIn("Context command shows global rules.", out)
        self.assertIn("Context command shows project context.", out)

    def test_status_works_with_explicit_temp_db(self):
        self.run_cli(["init", "--db", str(self.db_path), "--events", str(self.events_path)])

        code, out, err = self.run_cli(["status", "--db", str(self.db_path), "--events", str(self.events_path)])
        self.assertEqual(code, 0, err)
        self.assertIn(f"DB path: {self.db_path}", out)
        self.assertIn("DB exists: True", out)
        self.assertIn("Memory count: 0", out)

    def test_direct_script_invocation_status_works(self):
        result = self.run_cli_subprocess([
            sys.executable,
            "tools/memory_cli.py",
            "status",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DB exists: False", result.stdout)
        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)

    def test_module_invocation_status_still_works(self):
        result = self.run_cli_subprocess([
            sys.executable,
            "-m", "tools.memory_cli",
            "status",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DB exists: False", result.stdout)

    def test_direct_script_add_works_with_explicit_temp_paths(self):
        result = self.run_cli_subprocess([
            sys.executable,
            "tools/memory_cli.py",
            "add",
            "--type", "GLOBAL_RULE",
            "--scope", "global",
            "--content", "Direct script invocation works.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created memory ID:", result.stdout)
        self.assertTrue(self.db_path.exists())
        self.assertTrue(self.events_path.exists())
        self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
        self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)

    def test_cli_operations_do_not_modify_real_runtime_data(self):
        commands = (
            ["status", "--db", str(self.db_path), "--events", str(self.events_path)],
            ["init", "--db", str(self.db_path), "--events", str(self.events_path)],
            [
                "add",
                "--type", "GLOBAL_RULE",
                "--scope", "global",
                "--content", "CLI temp-path write must not touch runtime data.",
                "--db", str(self.db_path),
                "--events", str(self.events_path),
            ],
            ["list", "--db", str(self.db_path)],
            ["search", "temp-path", "--db", str(self.db_path)],
            ["context", "--db", str(self.db_path)],
        )
        for args in commands:
            with self.subTest(args=args):
                code, out, err = self.run_cli(args)
                self.assertEqual(code, 0, err)
                self.assertEqual(_file_signature(DEFAULT_DB), self.db_signature)
                self.assertEqual(_file_signature(DEFAULT_JSONL), self.jsonl_signature)

    def test_context_output_separates_project_types(self):
        self.run_cli([
            "add",
            "--type", "PROJECT_CONTEXT",
            "--scope", "project:Meu-Jarvi",
            "--project", "Meu-Jarvi",
            "--content", "Project-only context marker.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.run_cli([
            "add",
            "--type", "TECHNICAL_STATE",
            "--scope", "project:Meu-Jarvi",
            "--project", "Meu-Jarvi",
            "--content", "Technical-only state marker.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.run_cli([
            "add",
            "--type", "WARNING",
            "--scope", "project:Meu-Jarvi",
            "--project", "Meu-Jarvi",
            "--content", "Warning-only marker.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        code, out, err = self.run_cli(["context", "--project", "Meu-Jarvi", "--db", str(self.db_path)])
        self.assertEqual(code, 0, err)
        project_section = out.split("Technical State", 1)[0]
        technical_section = out.split("Technical State", 1)[1].split("Warnings", 1)[0]
        warnings_section = out.split("Warnings", 1)[1].split("Decisions", 1)[0]

        self.assertIn("Project Context", project_section)
        self.assertIn("Project-only context marker.", project_section)
        self.assertNotIn("Technical-only state marker.", project_section)
        self.assertNotIn("Warning-only marker.", project_section)
        self.assertIn("Technical-only state marker.", technical_section)
        self.assertIn("Warning-only marker.", warnings_section)

    def test_invalid_project_context_global_returns_nonzero(self):
        result = self.run_cli_subprocess([
            sys.executable,
            "-m", "tools.memory_cli",
            "add",
            "--type", "PROJECT_CONTEXT",
            "--scope", "global",
            "--content", "Invalid global project context.",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot use scope='global'", result.stderr)

    def test_secret_like_content_returns_nonzero(self):
        result = self.run_cli_subprocess([
            sys.executable,
            "-m", "tools.memory_cli",
            "add",
            "--type", "GLOBAL_RULE",
            "--scope", "global",
            "--content", "API_KEY=supersecretvalue123456789",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("secret or credential", result.stderr)

    def test_missing_id_show_returns_nonzero(self):
        result = self.run_cli_subprocess([
            sys.executable,
            "-m", "tools.memory_cli",
            "show",
            "--id", "404",
            "--db", str(self.db_path),
        ])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("memory not found", result.stderr)

    def test_valid_list_search_context_status_return_zero(self):
        self.create_sample_memory("Searchable memory marker.")
        for args in (
            ["list", "--db", str(self.db_path)],
            ["search", "Searchable", "--db", str(self.db_path)],
            ["context", "--db", str(self.db_path)],
            ["status", "--db", str(self.db_path), "--events", str(self.events_path)],
        ):
            with self.subTest(args=args):
                code, out, err = self.run_cli(args)
                self.assertEqual(code, 0, err)

    def create_sample_memory(self, content="Lifecycle memory content.", memory_type="GLOBAL_RULE", scope="global"):
        code, out, err = self.run_cli([
            "add",
            "--type", memory_type,
            "--scope", scope,
            "--content", content,
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.assertEqual(code, 0, err)
        return int(out.strip().split(":")[-1])

    def event_count(self):
        if not self.events_path.exists():
            return 0
        return len([line for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def test_show_returns_created_memory(self):
        memory_id = self.create_sample_memory("Show command returns this memory.")

        code, out, err = self.run_cli(["show", "--id", str(memory_id), "--db", str(self.db_path)])
        self.assertEqual(code, 0, err)
        self.assertIn(f"id: {memory_id}", out)
        self.assertIn("type: GLOBAL_RULE", out)
        self.assertIn("content: Show command returns this memory.", out)

    def test_show_missing_id_fails_safely(self):
        code, out, err = self.run_cli(["show", "--id", "999", "--db", str(self.db_path)])
        self.assertEqual(code, 2)
        self.assertIn("memory not found", err)

    def test_set_status_changes_observed_to_validated(self):
        memory_id = self.create_sample_memory()

        code, out, err = self.run_cli([
            "set-status",
            "--id", str(memory_id),
            "--status", "validated",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.assertEqual(code, 0, err)
        self.assertIn("status: validated", out)

        code, show_out, show_err = self.run_cli(["show", "--id", str(memory_id), "--db", str(self.db_path)])
        self.assertEqual(code, 0, show_err)
        self.assertIn("status: validated", show_out)

    def test_set_status_invalid_status_fails_safely(self):
        memory_id = self.create_sample_memory()
        before = self.event_count()

        with self.assertRaises(SystemExit):
            self.run_cli([
                "set-status",
                "--id", str(memory_id),
                "--status", "trusted",
                "--db", str(self.db_path),
                "--events", str(self.events_path),
            ])
        self.assertEqual(self.event_count(), before)

    def test_set_status_missing_id_fails_safely(self):
        self.run_cli(["init", "--db", str(self.db_path), "--events", str(self.events_path)])
        before = self.event_count()

        code, out, err = self.run_cli([
            "set-status",
            "--id", "999",
            "--status", "validated",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.assertEqual(code, 2)
        self.assertIn("Memory not found", err)
        self.assertEqual(self.event_count(), before)

    def test_archive_changes_status_to_archived(self):
        memory_id = self.create_sample_memory()

        code, out, err = self.run_cli([
            "archive",
            "--id", str(memory_id),
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.assertEqual(code, 0, err)
        self.assertIn(f"Archived memory ID: {memory_id}", out)

        code, show_out, show_err = self.run_cli(["show", "--id", str(memory_id), "--db", str(self.db_path)])
        self.assertEqual(code, 0, show_err)
        self.assertIn("status: archived", show_out)

    def test_archive_missing_id_fails_safely(self):
        self.run_cli(["init", "--db", str(self.db_path), "--events", str(self.events_path)])
        before = self.event_count()

        code, out, err = self.run_cli([
            "archive",
            "--id", "999",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.assertEqual(code, 2)
        self.assertIn("Memory not found", err)
        self.assertEqual(self.event_count(), before)

    def test_audit_prints_counts_without_full_memory_contents(self):
        full_content = "This exact long memory body should not appear in audit output."
        self.create_sample_memory(full_content)

        code, out, err = self.run_cli(["audit", "--db", str(self.db_path), "--events", str(self.events_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("Total memories: 1", out)
        self.assertIn("GLOBAL_RULE: 1", out)
        self.assertIn("global: 1", out)
        self.assertIn("observed: 1", out)
        self.assertIn("Event log exists: yes", out)
        self.assertNotIn(full_content, out)

    def test_rejected_set_status_does_not_append_jsonl_event(self):
        memory_id = self.create_sample_memory()
        before = self.event_count()

        with self.assertRaises(SystemExit):
            self.run_cli([
                "set-status",
                "--id", str(memory_id),
                "--status", "not_a_status",
                "--db", str(self.db_path),
                "--events", str(self.events_path),
            ])
        self.assertEqual(self.event_count(), before)

    def test_rejected_archive_does_not_append_jsonl_event(self):
        self.run_cli(["init", "--db", str(self.db_path), "--events", str(self.events_path)])
        before = self.event_count()

        code, out, err = self.run_cli([
            "archive",
            "--id", "12345",
            "--db", str(self.db_path),
            "--events", str(self.events_path),
        ])
        self.assertEqual(code, 2)
        self.assertEqual(self.event_count(), before)


if __name__ == "__main__":
    unittest.main()
