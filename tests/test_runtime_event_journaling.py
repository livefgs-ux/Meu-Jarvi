import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import os
import sys
import asyncio

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.runtime_journal import get_runtime_timeline, record_event, list_recent_events
from main import JarvisLive

class TestRuntimeEventJournaling(unittest.TestCase):

    def setUp(self):
        self._orig_env = os.environ.copy()
        os.environ["JARVIS_LIVE_RESILIENCE"] = "false"
        os.environ["JARVIS_CONCURRENT_TASK_RUNTIME"] = "false"
        self.timeline = get_runtime_timeline()
        self.timeline.clear()
        self.mock_ui = MagicMock()
        self.jarvis = JarvisLive(self.mock_ui)
        self.jarvis.session = AsyncMock()
        # Create a loop for testing
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.jarvis._loop = self.loop

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self.loop.close()

    def test_record_event_fail_open(self):
        # Mock add_event to raise exception
        with patch.object(self.timeline, 'add_event', side_effect=Exception("Disk full")):
            res = record_event("test", "src", "summary")
            self.assertIsNone(res)
            # Should not crash

    def test_user_text_input_records_event(self):
        self.jarvis._on_text_command("Hello Jarvis")
        events = self.timeline.list_recent(event_type="user_input")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].summary, "Hello Jarvis")
        self.assertEqual(events[0].metadata["input_type"], "text")

    def test_audio_input_records_event_without_running_jarvis(self):
        # Verify helper works
        record_event("user_input", "audio_transcription", "Audio text", metadata={"input_type": "audio"})
        events = self.timeline.list_recent(event_type="user_input")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].summary, "Audio text")

    async def async_test_tool_called_records_event(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "test"}
        fc.id = "call_123"

        # We need to mock _apply_tool_call_gate to return allowed
        with patch("main._apply_tool_call_gate", return_value=(True, None, "allow")):
            # Mock the actual tool execution to avoid network
            with patch("main.web_search_action", return_value="Search result"):
                await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="tool_called")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "web_search")
        self.assertEqual(events[0].correlation_id, "call_123")

    def test_tool_called_records_event(self):
        asyncio.run(self.async_test_tool_called_records_event())

    async def async_test_tool_result_records_event(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "test"}
        fc.id = "call_123"

        with patch("main._apply_tool_call_gate", return_value=(True, None, "allow")):
            with patch("main.web_search_action", return_value="Search result"):
                await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="tool_result")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].summary, "Search result")

    def test_tool_result_records_event(self):
        try:
            asyncio.run(self.async_test_tool_result_records_event())
        except AssertionError:
            events = self.timeline.list_recent(20)
            for e in events:
                print(f"EVENT: {e.event_type} - {e.summary}")
            raise

    async def async_test_tool_error_records_event(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "test"}
        fc.id = "call_123"

        with patch("main._apply_tool_call_gate", return_value=(True, None, "allow")):
            with patch("main.web_search_action", side_effect=Exception("API Error")):
                await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="tool_error")
        self.assertEqual(len(events), 1)
        self.assertIn("API Error", events[0].summary)
        self.assertEqual(events[0].severity, "error")

    def test_tool_error_records_event(self):
        asyncio.run(self.async_test_tool_error_records_event())

    async def async_test_confirmation_required_records_event(self):
        fc = MagicMock()
        fc.name = "file_controller"
        fc.args = {"action": "delete", "path": "important.txt"}
        fc.id = "call_999"

        # Mock gate to require confirmation
        with patch("main._apply_tool_call_gate", return_value=(False, "Confirm delete?", "confirm")):
            # Mock UI to deny
            self.mock_ui.request_confirmation = AsyncMock(return_value=False)
            await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="confirmation_required")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].summary, "Confirm delete?")

    def test_confirmation_required_records_event(self):
        asyncio.run(self.async_test_confirmation_required_records_event())

    async def async_test_confirmation_approved_records_event(self):
        fc = MagicMock()
        fc.name = "file_controller"
        fc.args = {"action": "delete", "path": "important.txt"}
        fc.id = "call_999"

        with patch("main._apply_tool_call_gate", return_value=(False, "Confirm?", "confirm")):
            self.mock_ui.request_confirmation = AsyncMock(return_value=True)
            with patch("main.file_controller", return_value="Deleted"):
                await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="confirmation_approved")
        self.assertEqual(len(events), 1)

    def test_confirmation_approved_records_event(self):
        asyncio.run(self.async_test_confirmation_approved_records_event())

    async def async_test_confirmation_denied_records_event(self):
        fc = MagicMock()
        fc.name = "file_controller"
        fc.args = {"action": "delete", "path": "important.txt"}
        fc.id = "call_999"

        with patch("main._apply_tool_call_gate", return_value=(False, "Confirm?", "confirm")):
            self.mock_ui.request_confirmation = AsyncMock(return_value=False)
            await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="confirmation_denied")
        self.assertEqual(len(events), 1)

    def test_confirmation_denied_records_event(self):
        asyncio.run(self.async_test_confirmation_denied_records_event())

    async def async_test_open_app_not_found_records_app_not_found(self):
        fc = MagicMock()
        fc.name = "open_app"
        fc.args = {"app_name": "GhostApp"}
        fc.id = "call_app"

        with patch("main._apply_tool_call_gate", return_value=(True, None, "allow")):
            with patch("main.open_app", return_value="GhostApp não foi encontrado"):
                await self.jarvis._execute_tool(fc)

        events = self.timeline.find_recent(event_type="app_not_found")
        self.assertEqual(len(events), 1)

    def test_open_app_not_found_records_app_not_found(self):
        asyncio.run(self.async_test_open_app_not_found_records_app_not_found())

    def test_secret_redaction_in_runtime_journal(self):
        record_event("user_input", "text", "password: 12345")
        events = list_recent_events(1)
        self.assertNotIn("12345", events[0].summary)
        self.assertIn("[REDACTED]", events[0].summary)

    def test_runtime_journal_does_not_import_actions_ui_main(self):
        path = os.path.join("core", "runtime_journal.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for forbidden in ["import actions", "from actions", "import main", "import ui"]:
            self.assertNotIn(forbidden, content)

    def test_runtime_journal_uses_local_state_default(self):
        from core.runtime_journal import DEFAULT_TIMELINE_PATH
        self.assertIn(".local_state", DEFAULT_TIMELINE_PATH)

    def test_runtime_journal_does_not_touch_data_config_memory(self):
        path = os.path.join("core", "runtime_journal.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for restricted in ["data/", "config/", "memory/"]:
            self.assertNotIn(f'"{restricted}"', content)
            self.assertNotIn(f"'{restricted}'", content)

    async def async_test_existing_behavior_preserved_when_journal_fails(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "test"}
        fc.id = "call_fail"

        with patch("main._apply_tool_call_gate", return_value=(True, None, "allow")):
            with patch("main.web_search_action", return_value="Still works"):
                # Patch the underlying add_event to raise, record_event should catch it
                with patch.object(self.timeline, 'add_event', side_effect=Exception("Journal crash")):
                    res = await self.jarvis._execute_tool(fc)
                    self.assertEqual(res.response["result"], "Still works")

    def test_existing_behavior_preserved_when_journal_fails(self):
        asyncio.run(self.async_test_existing_behavior_preserved_when_journal_fails())

if __name__ == "__main__":
    unittest.main()
