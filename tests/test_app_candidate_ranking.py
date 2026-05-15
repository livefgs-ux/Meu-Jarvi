import unittest
from core.app_inventory import AppCandidate, AppInventory, resolve_trusted_app, normalize_app_query, rank_candidate, classify_candidate_kind

class TestAppCandidateRanking(unittest.TestCase):
    def setUp(self):
        self.inventory = AppInventory()

    def test_cursor_gui_beats_cursor_tunnel(self):
        # Cursor GUI
        c_gui = AppCandidate(
            name="Cursor (User)",
            normalized_name="cursor",
            executable_path="C:\\Users\\User\\AppData\\Local\\Programs\\cursor\\Cursor.exe",
            source="registry",
            status="installed_verified"
        )
        # Cursor Tunnel
        c_tunnel = AppCandidate(
            name="cursor-tunnel",
            normalized_name="cursor",
            executable_path="C:\\Users\\User\\AppData\\Local\\Programs\\cursor\\resources\\app\\bin\\cursor-tunnel.exe",
            source="path",
            status="installed_verified"
        )
        
        self.inventory.candidates = [c_gui, c_tunnel]
        res = resolve_trusted_app("Cursor", self.inventory)
        
        self.assertEqual(res["status"], "installed_verified")
        self.assertEqual(res["candidate"].name, "Cursor (User)")
        self.assertTrue(res["candidate"].rank_score > c_tunnel.rank_score)

    def test_cursor_gui_beats_cursor_cli(self):
        # Cursor GUI
        c_gui = AppCandidate(
            name="Cursor",
            normalized_name="cursor",
            executable_path="C:\\Users\\User\\AppData\\Local\\Programs\\cursor\\Cursor.exe",
            source="shortcut",
            status="shortcut_valid"
        )
        # Cursor CLI
        c_cli = AppCandidate(
            name="cursor",
            normalized_name="cursor",
            executable_path="C:\\Users\\User\\AppData\\Local\\Programs\\cursor\\resources\\app\\bin\\cursor.exe",
            source="path",
            status="installed_verified"
        )
        
        self.inventory.candidates = [c_gui, c_cli]
        res = resolve_trusted_app("Cursor", self.inventory)
        
        self.assertEqual(res["candidate"].name, "Cursor")
        self.assertEqual(res["candidate"].source, "shortcut")

    def test_cursor_ambiguous_only_when_two_gui_candidates(self):
        c1 = AppCandidate(name="Cursor User", normalized_name="cursor", source="shortcut", status="shortcut_valid")
        c2 = AppCandidate(name="Cursor System", normalized_name="cursor", source="shortcut", status="shortcut_valid")
        
        self.inventory.candidates = [c1, c2]
        res = resolve_trusted_app("Cursor", self.inventory)
        self.assertEqual(res["status"], "ambiguous")

    def test_powershell_generic_does_not_choose_ise(self):
        ps = AppCandidate(name="PowerShell", normalized_name="powershell", executable_path="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", source="path")
        ise = AppCandidate(name="Windows PowerShell ISE", normalized_name="powershell", executable_path="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell_ise.exe", source="path")
        
        self.inventory.candidates = [ps, ise]
        res = resolve_trusted_app("PowerShell", self.inventory)
        
        self.assertEqual(res["candidate"].name, "PowerShell")
        self.assertNotIn("ISE", res["candidate"].name)

    def test_powershell_ise_selected_when_requested(self):
        ps = AppCandidate(name="PowerShell", normalized_name="powershell", executable_path="powershell.exe")
        ise = AppCandidate(name="Windows PowerShell ISE", normalized_name="powershell", executable_path="powershell_ise.exe")
        
        self.inventory.candidates = [ps, ise]
        res = resolve_trusted_app("PowerShell ISE", self.inventory)
        
        self.assertEqual(res["candidate"].name, "Windows PowerShell ISE")

    def test_developer_powershell_selected_only_when_requested(self):
        ps = AppCandidate(name="PowerShell", normalized_name="powershell", executable_path="powershell.exe")
        dev = AppCandidate(name="Developer PowerShell for VS 2022", normalized_name="powershell", executable_path="LaunchDevShell.ps1")
        
        self.inventory.candidates = [ps, dev]
        
        # Generic request
        res1 = resolve_trusted_app("PowerShell", self.inventory)
        self.assertEqual(res1["candidate"].name, "PowerShell")
        
        # Specific request
        res2 = resolve_trusted_app("Developer PowerShell", self.inventory)
        self.assertEqual(res2["candidate"].name, "Developer PowerShell for VS 2022")

    def test_installer_and_uninstaller_are_not_auto_selected(self):
        app = AppCandidate(name="My App", normalized_name="my app", executable_path="myapp.exe", source="registry")
        inst = AppCandidate(name="My App Installer", normalized_name="my app", executable_path="setup.exe", source="path")
        uninst = AppCandidate(name="My App Uninstall", normalized_name="my app", executable_path="uninstall.exe", source="path")
        
        self.inventory.candidates = [inst, uninst]
        res = resolve_trusted_app("My App", self.inventory)
        # Should not find them because they are filtered out from auto-selection
        self.assertEqual(res["status"], "not_found")
        
        # But should find if explicitly asked
        res_explicit = resolve_trusted_app("My App Installer", self.inventory)
        self.assertEqual(res_explicit["candidate"].name, "My App Installer")

    def test_helper_service_updater_are_low_priority(self):
        app = AppCandidate(name="Chrome", normalized_name="google chrome", executable_path="chrome.exe", source="registry")
        helper = AppCandidate(name="Chrome Helper", normalized_name="google chrome", executable_path="chrome_helper.exe", source="path")
        updater = AppCandidate(name="Chrome Update", normalized_name="google chrome", executable_path="GoogleUpdate.exe", source="path")
        
        self.inventory.candidates = [app, helper, updater]
        res = resolve_trusted_app("Chrome", self.inventory)
        self.assertEqual(res["candidate"].name, "Chrome")
        self.assertTrue(app.rank_score > helper.rank_score)
        self.assertTrue(helper.rank_score > updater.rank_score)

    def test_start_menu_human_shortcut_boosts_gui_candidate(self):
        c1 = AppCandidate(name="Code", normalized_name="visual studio code", executable_path="C:\\path\\code.exe", source="path")
        c2 = AppCandidate(name="Visual Studio Code", normalized_name="visual studio code", source="shortcut")
        
        self.inventory.candidates = [c1, c2]
        res = resolve_trusted_app("VS Code", self.inventory)
        self.assertEqual(res["candidate"].name, "Visual Studio Code")
        self.assertEqual(res["candidate"].source, "shortcut")

    def test_vscode_still_does_not_resolve_to_cursor_or_codex(self):
        vscode = AppCandidate(name="VS Code", normalized_name="visual studio code", executable_path="code.exe")
        cursor = AppCandidate(name="Cursor", normalized_name="cursor", executable_path="cursor.exe")
        
        self.inventory.candidates = [vscode, cursor]
        res = resolve_trusted_app("VS Code", self.inventory)
        self.assertEqual(res["candidate"].name, "VS Code")
        
        # Overlap check
        self.inventory.candidates = [cursor]
        res2 = resolve_trusted_app("VS Code", self.inventory)
        self.assertEqual(res2["status"], "not_found")

    def test_internet_explorer_still_does_not_resolve_to_file_explorer(self):
        ie = AppCandidate(name="Internet Explorer", normalized_name="internet explorer", executable_path="iexplore.exe")
        fe = AppCandidate(name="File Explorer", normalized_name="windows file explorer", executable_path="explorer.exe")
        
        self.inventory.candidates = [ie, fe]
        res = resolve_trusted_app("Internet Explorer", self.inventory)
        self.assertEqual(res["candidate"].name, "Internet Explorer")
        
        self.inventory.candidates = [fe]
        res2 = resolve_trusted_app("Internet Explorer", self.inventory)
        self.assertEqual(res2["status"], "not_found")

    def test_ambiguous_candidates_are_equivalent_safe_apps(self):
        c1 = AppCandidate(name="PowerShell 7", normalized_name="powershell", executable_path="pwsh.exe", source="shortcut", status="shortcut_valid")
        c2 = AppCandidate(name="Windows PowerShell", normalized_name="powershell", executable_path="powershell.exe", source="shortcut", status="shortcut_valid")
        
        self.inventory.candidates = [c1, c2]
        res = resolve_trusted_app("PowerShell", self.inventory)
        self.assertEqual(res["status"], "ambiguous")

    def test_candidate_kind_is_serialized_in_cache(self):
        import tempfile
        import os
        from core.app_inventory import save_inventory_cache, load_inventory_cache
        
        c = AppCandidate(name="Test", normalized_name="test", candidate_kind="gui_app", rank_score=100)
        self.inventory.candidates = [c]
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
            
        try:
            save_inventory_cache(self.inventory, tmp_path)
            loaded_inv, ts = load_inventory_cache(tmp_path)
            
            loaded_c = loaded_inv.candidates[0]
            self.assertEqual(loaded_c.candidate_kind, "gui_app")
            self.assertEqual(loaded_c.rank_score, 100)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_existing_cache_load_handles_missing_candidate_kind_backward_compatibly(self):
        import tempfile
        import os
        import json
        from core.app_inventory import load_inventory_cache
        
        # Create a legacy cache without the new fields
        legacy_data = {
            "timestamp": 123456789,
            "candidates": [
                {
                    "name": "Legacy App",
                    "normalized_name": "legacy app",
                    "executable_path": "legacy.exe",
                    "source": "registry",
                    "status": "installed_verified",
                    "confidence": 0.9,
                    "evidence": "Test"
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8') as tmp:
            json.dump(legacy_data, tmp)
            tmp_path = tmp.name
            
        try:
            loaded_inv, ts = load_inventory_cache(tmp_path)
            self.assertEqual(len(loaded_inv.candidates), 1)
            c = loaded_inv.candidates[0]
            self.assertEqual(c.name, "Legacy App")
            self.assertEqual(c.candidate_kind, "unknown") # Default value
            self.assertEqual(c.rank_score, 0) # Default value
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == "__main__":
    unittest.main()
