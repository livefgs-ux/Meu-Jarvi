import ast
import unittest
from pathlib import Path


FORBIDDEN_IMPORTS = {
    "main",
    "ui",
    "actions",
    "agent",
    "google.genai",
    "google.generativeai",
    "playwright",
    "pyautogui",
    "graphify",
    "obsidian",
}


class NoRuntimeIntegrationTests(unittest.TestCase):
    def test_brain_package_does_not_import_runtime_or_external_modules(self):
        for path in Path("brain").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)

            for forbidden in FORBIDDEN_IMPORTS:
                with self.subTest(path=str(path), forbidden=forbidden):
                    self.assertFalse(
                        any(name == forbidden or name.startswith(f"{forbidden}.") for name in imported),
                        f"{path} imports forbidden module {forbidden}",
                    )


if __name__ == "__main__":
    unittest.main()
