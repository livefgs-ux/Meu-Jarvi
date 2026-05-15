import unittest
import os
import tempfile
import json
import time
from pathlib import Path
from core.event_timeline import EventTimeline, EventRecord, DEFAULT_TIMELINE_PATH

class TestEventTimeline(unittest.TestCase):

    def setUp(self):
        self.timeline = EventTimeline(max_events=5)

    def test_add_event_and_list_recent(self):
        self.timeline.add_event("user_input", "test", "Hello")
        recent = self.timeline.list_recent(limit=1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].summary, "Hello")
        self.assertEqual(recent[0].event_type, "user_input")

    def test_ring_buffer_respects_max_events(self):
        for i in range(10):
            self.timeline.add_event("test", "source", f"Event {i}")
        
        recent = self.timeline.list_recent()
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0].summary, "Event 5")
        self.assertEqual(recent[4].summary, "Event 9")

    def test_filter_by_event_type(self):
        self.timeline.add_event("type_a", "source", "A1")
        self.timeline.add_event("type_b", "source", "B1")
        self.timeline.add_event("type_a", "source", "A2")
        
        filtered = self.timeline.list_recent(event_type="type_a")
        self.assertEqual(len(filtered), 2)
        self.assertTrue(all(e.event_type == "type_a" for e in filtered))

    def test_filter_by_source(self):
        self.timeline.add_event("test", "src_1", "E1")
        self.timeline.add_event("test", "src_2", "E2")
        
        results = self.timeline.find_recent(source="src_1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "src_1")

    def test_correlation_id_links_events(self):
        c_id = "request_123"
        self.timeline.add_event("app_requested", "user", "Open Code", correlation_id=c_id)
        self.timeline.add_event("app_resolved", "inventory", "Code found", correlation_id=c_id)
        
        results = self.timeline.find_recent(correlation_id=c_id)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].correlation_id, c_id)
        self.assertEqual(results[1].correlation_id, c_id)

    def test_clear_timeline(self):
        self.timeline.add_event("test", "source", "E1")
        self.timeline.clear()
        self.assertEqual(len(self.timeline.list_recent()), 0)

    def test_to_dict_is_serializable(self):
        self.timeline.add_event("test", "source", "E1", metadata={"key": "value"})
        data = self.timeline.to_dict()
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["summary"], "E1")
        # Verify JSON serializable
        json_str = json.dumps(data)
        self.assertIsInstance(json_str, str)

    def test_export_and_load_jsonl_tempdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timeline.jsonl")
            self.timeline.add_event("test", "source", "E1")
            self.timeline.add_event("test", "source", "E2")
            self.timeline.export_jsonl(path)
            
            self.assertTrue(os.path.exists(path))
            
            new_timeline = EventTimeline(max_events=5)
            new_timeline.load_jsonl(path)
            self.assertEqual(len(new_timeline.list_recent()), 2)
            self.assertEqual(new_timeline.list_recent()[0].summary, "E1")

    def test_secret_redaction_in_summary(self):
        self.timeline.add_event("test", "source", "My api_key=12345")
        recent = self.timeline.list_recent(limit=1)
        self.assertNotIn("12345", recent[0].summary)
        self.assertIn("[REDACTED]", recent[0].summary)

    def test_secret_redaction_in_metadata(self):
        self.timeline.add_event("test", "source", "Summary", metadata={"api_key": "ABCDE", "other": "public"})
        recent = self.timeline.list_recent(limit=1)
        self.assertEqual(recent[0].metadata["api_key"], "[REDACTED]")
        self.assertEqual(recent[0].metadata["other"], "public")

    def test_large_metadata_is_limited(self):
        large_str = "x" * 2000
        self.timeline.add_event("test", "source", "Summary", metadata={"data": large_str})
        recent = self.timeline.list_recent(limit=1)
        self.assertLess(len(recent[0].metadata["data"]), 2000)
        self.assertIn("[TRUNCATED]", recent[0].metadata["data"])

    def test_default_path_points_to_local_state(self):
        self.assertEqual(DEFAULT_TIMELINE_PATH, ".local_state/environment_timeline.jsonl")

    def test_module_does_not_import_actions_main_ui(self):
        path = Path(__file__).parent.parent / "core" / "event_timeline.py"
        content = path.read_text(encoding="utf-8")
        forbidden = ["import actions", "from actions", "import main", "import ui"]
        for f in forbidden:
            self.assertNotIn(f, content)

    def test_module_does_not_touch_data_config_memory(self):
        path = Path(__file__).parent.parent / "core" / "event_timeline.py"
        content = path.read_text(encoding="utf-8")
        # Check for strings like "data/", "config/", "memory/"
        # Except maybe "os.makedirs" logic or similar if it was there, 
        # but the requirement says "not touch data/ config/ memory/".
        restricted = ["data/", "config/", "memory/"]
        for r in restricted:
            self.assertNotIn(f'"{r}"', content)
            self.assertNotIn(f"'{r}'", content)

    def test_no_network_or_subprocess_usage(self):
        path = Path(__file__).parent.parent / "core" / "event_timeline.py"
        content = path.read_text(encoding="utf-8")
        forbidden = ["import socket", "import requests", "import urllib", "import subprocess"]
        for f in forbidden:
            self.assertNotIn(f, content)

if __name__ == "__main__":
    unittest.main()
