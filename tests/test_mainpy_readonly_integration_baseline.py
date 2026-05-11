import ast
import unittest
from pathlib import Path


def _sig(path: Path) -> tuple[int, float] | None:
    if not path.exists():
        return None
    st = path.stat()
    return (st.st_size, st.st_mtime)


class TestMainPyReadonlyIntegrationBaseline(unittest.TestCase):
    """Baseline guardrails before Phase 7E.

    This test inspects main.py as text/AST only. It MUST NOT import main.py,
    because importing it can trigger runtime-only dependencies (audio, UI, Gemini).

    Future Phase 7E will intentionally update these assertions when a minimal
    toggle-gated read-only integration is added.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.main_py = cls.repo_root / "main.py"
        cls.real_db = cls.repo_root / "data" / "jarvis_memory.db"
        cls.real_events = cls.repo_root / "data" / "raw_events.jsonl"

        cls.real_db_sig_before = _sig(cls.real_db)
        cls.real_events_sig_before = _sig(cls.real_events)

        cls.source = cls.main_py.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

        cls.real_db_sig_after_read = _sig(cls.real_db)
        cls.real_events_sig_after_read = _sig(cls.real_events)

    def test_01_main_py_exists(self):
        self.assertTrue(self.main_py.exists())

    def test_02_jarvislive_class_exists(self):
        classes = {n.name for n in self.tree.body if isinstance(n, ast.ClassDef)}
        self.assertIn("JarvisLive", classes)

    def test_03_build_config_exists(self):
        jarvis = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
        methods = {n.name for n in jarvis.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("_build_config", methods)

    def test_04_build_config_constructs_liveconnectconfig(self):
        # We detect a call whose attribute/id ends with LiveConnectConfig.
        jarvis = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
        build = next(n for n in jarvis.body if isinstance(n, ast.FunctionDef) and n.name == "_build_config")

        def is_liveconnect_call(node: ast.AST) -> bool:
            if not isinstance(node, ast.Call):
                return False
            fn = node.func
            if isinstance(fn, ast.Attribute):
                return fn.attr == "LiveConnectConfig"
            if isinstance(fn, ast.Name):
                return fn.id == "LiveConnectConfig"
            return False

        calls = [n for n in ast.walk(build) if is_liveconnect_call(n)]
        self.assertTrue(calls, "Expected _build_config to call types.LiveConnectConfig(...)")

    def test_05_build_config_loads_legacy_memory_and_core_prompt(self):
        # Baseline checks by text presence (robust against refactors that keep the same names).
        self.assertIn("load_memory", self.source)
        self.assertIn("format_memory_for_prompt", self.source)
        self.assertIn("_load_system_prompt", self.source)

    def test_06_tool_declarations_exists(self):
        assigns = [n for n in self.tree.body if isinstance(n, ast.Assign)]
        names = set()
        for a in assigns:
            for t in a.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        self.assertIn("TOOL_DECLARATIONS", names)

    def test_07_save_memory_tool_declared(self):
        # Strong signal: the literal "save_memory" should exist in TOOL_DECLARATIONS.
        self.assertIn('"save_memory"', self.source)
        self.assertIn("save_memory", self.source)

    def test_08_execute_tool_handles_save_memory_via_update_memory(self):
        self.assertIn("if name == \"save_memory\"", self.source)
        self.assertIn("update_memory", self.source)

    def test_09_tool_declarations_passed_to_liveconnectconfig(self):
        # Baseline: LiveConnectConfig tools kwarg should reference TOOL_DECLARATIONS somewhere.
        self.assertIn("function_declarations", self.source)
        self.assertIn("TOOL_DECLARATIONS", self.source)

    def test_10_no_runtime_context_import_yet(self):
        # Phase 7E intentionally adds the runtime_context wrapper import.
        self.assertIn("memory_engine.runtime_context", self.source)
        self.assertIn("build_readonly_memory_context_from_env", self.source)

    def test_11_no_tools_cli_imports(self):
        self.assertNotIn("tools.memory_cli", self.source)
        self.assertNotIn("tools.memory_context_preview", self.source)

    def test_12_no_memory_engine_writer_import(self):
        self.assertNotIn("memory_engine.writer", self.source)

    def test_13_no_memory_engine_writer_calls(self):
        for needle in ("create_memory(", "update_memory_status(", "archive_memory("):
            self.assertNotIn(needle, self.source)

    def test_14_no_direct_reference_to_runtime_db_paths(self):
        self.assertNotIn("data/jarvis_memory.db", self.source)
        self.assertNotIn("data\\jarvis_memory.db", self.source)

    def test_15_no_direct_reference_to_runtime_event_log_paths(self):
        self.assertNotIn("data/raw_events.jsonl", self.source)
        self.assertNotIn("data\\raw_events.jsonl", self.source)

    def test_16_reading_main_does_not_mutate_runtime_signatures(self):
        self.assertEqual(self.real_db_sig_after_read, self.real_db_sig_before)
        self.assertEqual(self.real_events_sig_after_read, self.real_events_sig_before)

    def test_17_forbidden_imports_not_present(self):
        banned_imports = {
            "memory_engine.writer",
            "memory_engine.runtime_adapter",
            "tools.memory_cli",
            "tools.memory_context_preview",
        }

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, banned_imports)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn(mod, banned_imports)

    def test_18_imports_runtime_context_wrapper_only(self):
        found = False
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "") == "memory_engine.runtime_context":
                names = {a.name for a in node.names}
                if "build_readonly_memory_context_from_env" in names:
                    found = True
        self.assertTrue(found, "Expected import of build_readonly_memory_context_from_env from memory_engine.runtime_context")

    def test_19_build_config_calls_wrapper(self):
        jarvis = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
        build = next(n for n in jarvis.body if isinstance(n, ast.FunctionDef) and n.name == "_build_config")

        calls = [
            n for n in ast.walk(build)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "build_readonly_memory_context_from_env"
        ]
        self.assertTrue(calls, "Expected _build_config() to call build_readonly_memory_context_from_env()")

    def test_20_wrapper_call_is_not_at_module_level(self):
        # Ensure wrapper isn't called globally at import time.
        for node in self.tree.body:
            if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Call):
                call = node.value
                if isinstance(call.func, ast.Name) and call.func.id == "build_readonly_memory_context_from_env":
                    self.fail("build_readonly_memory_context_from_env() must not be called at module level")

    def test_21_wrapper_result_appended_conditionally(self):
        jarvis = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
        build = next(n for n in jarvis.body if isinstance(n, ast.FunctionDef) and n.name == "_build_config")

        # We expect an If statement: if ro_memory_context: parts.append(ro_memory_context)
        found = False
        for node in ast.walk(build):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "ro_memory_context":
                # Look for parts.append(ro_memory_context) in the if body.
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                        if inner.func.attr == "append" and isinstance(inner.func.value, ast.Name) and inner.func.value.id == "parts":
                            if inner.args and isinstance(inner.args[0], ast.Name) and inner.args[0].id == "ro_memory_context":
                                found = True
        self.assertTrue(found, "Expected conditional parts.append(ro_memory_context) guarded by if ro_memory_context")

    def test_22_readonly_memory_append_occurs_before_sys_prompt_append(self):
        jarvis = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
        build = next(n for n in jarvis.body if isinstance(n, ast.FunctionDef) and n.name == "_build_config")

        def is_parts_append_name(stmt: ast.stmt, name: str) -> bool:
            if not isinstance(stmt, ast.Expr):
                return False
            call = stmt.value
            if not isinstance(call, ast.Call):
                return False
            if not isinstance(call.func, ast.Attribute):
                return False
            if call.func.attr != "append":
                return False
            if not isinstance(call.func.value, ast.Name) or call.func.value.id != "parts":
                return False
            return bool(call.args) and isinstance(call.args[0], ast.Name) and call.args[0].id == name

        def is_if_appending_ro(stmt: ast.stmt) -> bool:
            if not isinstance(stmt, ast.If):
                return False
            if not isinstance(stmt.test, ast.Name) or stmt.test.id != "ro_memory_context":
                return False
            for inner in stmt.body:
                if is_parts_append_name(inner, "ro_memory_context"):
                    return True
            return False

        sys_prompt_append_idx = None
        ro_append_idx = None
        for idx, stmt in enumerate(build.body):
            if is_parts_append_name(stmt, "sys_prompt"):
                sys_prompt_append_idx = idx
            if is_if_appending_ro(stmt):
                ro_append_idx = idx

        self.assertIsNotNone(ro_append_idx, "Expected if ro_memory_context: parts.append(ro_memory_context) in _build_config body")
        self.assertIsNotNone(sys_prompt_append_idx, "Expected parts.append(sys_prompt) in _build_config body")
        self.assertLess(ro_append_idx, sys_prompt_append_idx, "Expected read-only memory append to occur before sys_prompt append")


if __name__ == "__main__":
    unittest.main()
