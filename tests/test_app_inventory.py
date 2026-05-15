import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from core.app_inventory import (
    AppCandidate, AppInventory, normalize_app_query, 
    resolve_trusted_app, save_inventory_cache, load_inventory_cache,
    classify_candidate
)

class TestAppInventory(unittest.TestCase):

    def test_normalize_app_query_vscode_cursor_codex(self):
        self.assertEqual(normalize_app_query("VSCode"), "visual studio code")
        self.assertEqual(normalize_app_query("vs code"), "visual studio code")
        self.assertEqual(normalize_app_query("code"), "visual studio code")
        self.assertEqual(normalize_app_query("Cursor"), "cursor")
        self.assertEqual(normalize_app_query("codex"), "codex")

    def test_registry_only_without_exe_is_stale(self):
        # A candidate from registry with no exe path should be registry_only
        # If it has a path that doesn't exist, it's stale.
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = os.path.join(tmp, "missing.exe")
            c = AppCandidate(name="FakeApp", normalized_name="fakeapp", executable_path=fake_exe, source="registry")
            c.status = classify_candidate(c)
            self.assertEqual(c.status, "stale")
            
            c2 = AppCandidate(name="FakeApp", normalized_name="fakeapp", executable_path=None, source="registry")
            c2.status = classify_candidate(c2)
            self.assertEqual(c2.status, "registry_only")

    def test_broken_shortcut_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = os.path.join(tmp, "gone.exe")
            c = AppCandidate(name="Broken", normalized_name="broken", executable_path=fake_exe, source="shortcut")
            c.status = classify_candidate(c)
            self.assertEqual(c.status, "stale")

    def test_valid_executable_is_installed_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_exe = os.path.join(tmp, "exists.exe")
            Path(real_exe).touch()
            c = AppCandidate(name="RealApp", normalized_name="realapp", executable_path=real_exe, source="registry")
            c.status = classify_candidate(c)
            self.assertEqual(c.status, "installed_verified")

    def test_vscode_does_not_resolve_to_cursor(self):
        inventory = AppInventory()
        # Add a "Cursor" candidate that mentions "code.exe" (sometimes happens if based on VS Code)
        inventory.candidates.append(AppCandidate(
            name="Cursor", normalized_name="cursor", 
            executable_path="C:\\Users\\User\\AppData\\Local\\Programs\\Cursor\\resources\\app\\bin\\code.exe",
            status="installed_verified", source="registry"
        ))
        
        res = resolve_trusted_app("VS Code", inventory)
        self.assertEqual(res["status"], "not_found")
        
        res_cursor = resolve_trusted_app("Cursor", inventory)
        # Even if it has code.exe in path, it should match "cursor" query
        # But our guard in _add_candidate prevents this overlap during scan.
        # Here we added it manually to test the resolver's secondary guard.
        self.assertEqual(res_cursor["candidate"].normalized_name, "cursor")

    def test_vscode_does_not_resolve_to_codex(self):
        inventory = AppInventory()
        inventory.candidates.append(AppCandidate(
            name="Codex", normalized_name="codex", executable_path="C:\\Apps\\codex.exe",
            status="installed_verified"
        ))
        res = resolve_trusted_app("VS Code", inventory)
        self.assertEqual(res["status"], "not_found")

    def test_cursor_does_not_resolve_to_vscode(self):
        inventory = AppInventory()
        inventory.candidates.append(AppCandidate(
            name="Visual Studio Code", normalized_name="visual studio code", 
            executable_path="C:\\Program Files\\VSCode\\Code.exe",
            status="installed_verified"
        ))
        res = resolve_trusted_app("Cursor", inventory)
        self.assertEqual(res["status"], "not_found")

    def test_internet_explorer_does_not_resolve_to_file_explorer(self):
        inventory = AppInventory()
        inventory.candidates.append(AppCandidate(
            name="Windows Explorer", normalized_name="windows file explorer", 
            executable_path="C:\\Windows\\explorer.exe",
            status="installed_verified"
        ))
        res = resolve_trusted_app("Internet Explorer", inventory)
        self.assertEqual(res["status"], "not_found")

    def test_ambiguous_candidates_return_ambiguous(self):
        inventory = AppInventory()
        # Two different apps matching a vague query
        inventory.candidates.append(AppCandidate(
            name="My App A", normalized_name="my app a", executable_path="C:\\a.exe",
            status="installed_verified", confidence=0.9
        ))
        inventory.candidates.append(AppCandidate(
            name="My App B", normalized_name="my app b", executable_path="C:\\b.exe",
            status="installed_verified", confidence=0.9
        ))
        # Query "My App" matches both
        res = resolve_trusted_app("My App", inventory)
        self.assertEqual(res["status"], "ambiguous")

    def test_not_found_returns_not_found(self):
        inventory = AppInventory()
        res = resolve_trusted_app("Non Existent App", inventory)
        self.assertEqual(res["status"], "not_found")

    def test_cache_roundtrip_uses_tempdir(self):
        inventory = AppInventory()
        inventory.candidates.append(AppCandidate(name="Test", normalized_name="test", status="running"))
        
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "cache.json")
            save_inventory_cache(inventory, cache_path)
            self.assertTrue(os.path.exists(cache_path))
            
            loaded = load_inventory_cache(cache_path)
            self.assertEqual(len(loaded.candidates), 1)
            self.assertEqual(loaded.candidates[0].name, "Test")

    def test_inventory_does_not_open_apps(self):
        # We check the code doesn't call subprocess.Popen or os.startfile etc.
        # This is a static check of the source code.
        path = Path(__file__).parent.parent / "core" / "app_inventory.py"
        content = path.read_text(encoding="utf-8")
        forbidden = ["subprocess.Popen", "os.startfile", "subprocess.call", "subprocess.run"]
        for f in forbidden:
            # Note: subprocess.run might be used for light scanning in some impls, 
            # but here we avoided it.
            self.assertNotIn(f, content, f"Forbidden call found: {f}")

    def test_inventory_does_not_import_pyautogui(self):
        path = Path(__file__).parent.parent / "core" / "app_inventory.py"
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("import pyautogui", content)

    def test_inventory_does_not_touch_data_config_memory(self):
        # Verify no file operations outside .local_state or temp dirs
        path = Path(__file__).parent.parent / "core" / "app_inventory.py"
        content = path.read_text(encoding="utf-8")
        restricted = ["data/", "config/", "memory/", "api_keys.json", "long_term.json"]
        for r in restricted:
            self.assertNotIn(f'"{r}"', content)
            self.assertNotIn(f"'{r}'", content)

if __name__ == "__main__":
    unittest.main()
