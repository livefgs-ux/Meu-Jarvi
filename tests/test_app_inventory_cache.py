import unittest
import os
import time
import tempfile
import json
from pathlib import Path
from core.app_inventory import (
    AppInventory, AppCandidate, save_inventory_cache, 
    load_inventory_cache, get_cached_or_build_inventory, 
    APP_INVENTORY_CACHE_TTL_SECONDS, DEFAULT_CACHE_PATH
)

class TestAppInventoryCache(unittest.TestCase):

    def test_cache_roundtrip_tempdir(self):
        inventory = AppInventory()
        inventory.candidates.append(AppCandidate(name="TestApp", normalized_name="testapp", status="installed_verified"))
        
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "app_inventory.json")
            save_inventory_cache(inventory, cache_path)
            self.assertTrue(os.path.exists(cache_path))
            
            loaded_inv, timestamp = load_inventory_cache(cache_path)
            self.assertEqual(len(loaded_inv.candidates), 1)
            self.assertEqual(loaded_inv.candidates[0].name, "TestApp")
            self.assertGreater(timestamp, 0)

    def test_valid_cache_is_used_without_rebuild(self):
        # We can mock build_app_inventory to verify it's not called
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "cache.json")
            inventory = AppInventory()
            inventory.candidates.append(AppCandidate(name="CachedApp", normalized_name="cachedapp"))
            save_inventory_cache(inventory, cache_path)
            
            import core.app_inventory
            original_build = core.app_inventory.build_app_inventory
            core.app_inventory.build_app_inventory = lambda light_scan: unittest.TestCase().fail("build_app_inventory should not be called")
            
            try:
                result = get_cached_or_build_inventory(cache_path=cache_path)
                self.assertEqual(result.candidates[0].name, "CachedApp")
            finally:
                core.app_inventory.build_app_inventory = original_build

    def test_expired_cache_uses_stale_cache_without_deep_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "expired.json")
            
            # Create expired cache
            data = {
                "timestamp": time.time() - (APP_INVENTORY_CACHE_TTL_SECONDS + 100),
                "candidates": [{"name": "Old", "normalized_name": "old"}]
            }
            with open(cache_path, "w") as f:
                json.dump(data, f)

            import core.app_inventory
            original_refresh = core.app_inventory._schedule_inventory_refresh
            core.app_inventory._schedule_inventory_refresh = lambda *args, **kwargs: None

            try:
                result = get_cached_or_build_inventory(cache_path=cache_path)
                self.assertEqual(result.candidates[0].name, "Old")
                self.assertTrue(getattr(result, "needs_refresh", False))
            finally:
                core.app_inventory._schedule_inventory_refresh = original_refresh

    def test_force_refresh_ignores_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "force.json")
            inventory = AppInventory()
            inventory.candidates.append(AppCandidate(name="Cached", normalized_name="cached"))
            save_inventory_cache(inventory, cache_path)
            
            import core.app_inventory
            original_build = core.app_inventory.build_app_inventory
            mock_inv = AppInventory()
            mock_inv.candidates.append(AppCandidate(name="Refreshed", normalized_name="refreshed"))
            core.app_inventory.build_app_inventory = lambda light_scan: mock_inv
            
            try:
                result = get_cached_or_build_inventory(force_refresh=True, cache_path=cache_path)
                self.assertEqual(result.candidates[0].name, "Refreshed")
            finally:
                core.app_inventory.build_app_inventory = original_build

    def test_cache_does_not_touch_data_config_memory(self):
        path = Path(__file__).parent.parent / "core" / "app_inventory.py"
        content = path.read_text(encoding="utf-8")
        restricted = ["data/", "config/", "memory/", "api_keys.json", "long_term.json"]
        for r in restricted:
            self.assertNotIn(f'"{r}"', content)
            self.assertNotIn(f"'{r}'", content)

    def test_cache_path_defaults_to_local_state(self):
        self.assertEqual(DEFAULT_CACHE_PATH, ".local_state/app_inventory.json")

if __name__ == "__main__":
    unittest.main()
