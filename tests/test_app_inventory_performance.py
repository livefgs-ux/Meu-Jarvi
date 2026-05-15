import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.app_inventory import (
    AppCandidate,
    AppInventory,
    get_cached_or_build_inventory,
    resolve_trusted_app,
    save_inventory_cache,
)


class TestAppInventoryPerformance(unittest.TestCase):
    def _cached_inventory(self, cache_path: Path, name: str = "CachedApp") -> AppInventory:
        inventory = AppInventory()
        inventory.candidates.append(AppCandidate(name=name, normalized_name=name.lower()))
        save_inventory_cache(inventory, str(cache_path))
        return inventory

    def test_cache_hit_does_not_rebuild_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "app_inventory.json"
            self._cached_inventory(cache_path)

            with patch("core.app_inventory.build_app_inventory") as mock_build:
                result = get_cached_or_build_inventory(cache_path=str(cache_path))

            self.assertEqual(result.candidates[0].name, "CachedApp")
            mock_build.assert_not_called()

    def test_expired_cache_uses_stale_cache_without_deep_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "expired.json"
            self._cached_inventory(cache_path, name="OldApp")

            data = json.loads(cache_path.read_text(encoding="utf-8"))
            data["timestamp"] = 0
            cache_path.write_text(json.dumps(data), encoding="utf-8")

            with patch("core.app_inventory.build_app_inventory") as mock_build, patch(
                "core.app_inventory._schedule_inventory_refresh"
            ) as mock_refresh:
                result = get_cached_or_build_inventory(cache_path=str(cache_path))

            self.assertEqual(result.candidates[0].name, "OldApp")
            self.assertTrue(getattr(result, "needs_refresh", False))
            mock_build.assert_not_called()
            mock_refresh.assert_called_once()

    def test_force_refresh_can_trigger_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "force.json"
            self._cached_inventory(cache_path, name="CachedApp")

            refreshed = AppInventory()
            refreshed.candidates.append(AppCandidate(name="RefreshedApp", normalized_name="refreshedapp"))

            with patch("core.app_inventory.build_app_inventory", return_value=refreshed) as mock_build:
                result = get_cached_or_build_inventory(
                    light_scan=False,
                    force_refresh=True,
                    cache_path=str(cache_path),
                )

            self.assertEqual(result.candidates[0].name, "RefreshedApp")
            mock_build.assert_called_once_with(light_scan=False)

    def test_missing_cache_uses_light_scan_not_deep_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "missing.json"
            expected = AppInventory()
            expected.candidates.append(AppCandidate(name="LightScan", normalized_name="lightscan"))

            with patch("core.app_inventory.build_app_inventory", return_value=expected) as mock_build:
                result = get_cached_or_build_inventory(cache_path=str(cache_path))

            self.assertEqual(result.candidates[0].name, "LightScan")
            mock_build.assert_called_once_with(light_scan=True)

    def test_resolve_vscode_not_installed_fast_with_cache(self):
        inventory = AppInventory()
        with patch("core.app_inventory.get_cached_or_build_inventory", return_value=inventory) as mock_get:
            result = resolve_trusted_app("VS Code")

        self.assertEqual(result["status"], "not_found")
        mock_get.assert_called_once_with(light_scan=True, force_refresh=False)

    def test_no_real_apps_launched(self):
        src = Path(__file__).resolve().parents[1] / "core" / "app_inventory.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("subprocess", text.lower())
        self.assertNotIn("os.startfile", text.lower())

    def test_does_not_touch_data_config_memory(self):
        src = Path(__file__).resolve().parents[1] / "core" / "app_inventory.py"
        text = src.read_text(encoding="utf-8")
        for needle in ["data/jarvis_memory.db", "data/raw_events.jsonl", "config/api_keys.json", "memory/long_term.json"]:
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
