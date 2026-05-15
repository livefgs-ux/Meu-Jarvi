import unittest
import time
from core.live_resilience import LiveResilienceSupervisor, LiveConnectionState

class TestLiveResilience(unittest.TestCase):
    def setUp(self):
        self.supervisor = LiveResilienceSupervisor()

    def test_state_transitions(self):
        self.assertEqual(self.supervisor.state, LiveConnectionState.DISCONNECTED)
        self.supervisor.set_state(LiveConnectionState.CONNECTING)
        self.assertEqual(self.supervisor.state, LiveConnectionState.CONNECTING)
        self.supervisor.mark_connected()
        self.assertEqual(self.supervisor.state, LiveConnectionState.CONNECTED)
        self.supervisor.mark_disconnect(None)
        self.assertEqual(self.supervisor.state, LiveConnectionState.DISCONNECTED)

    def test_backoff_progression(self):
        # Sequence: [3, 5, 10, 20, 60]
        # Allowing for jitter (±10%)
        
        delay1 = self.supervisor.next_backoff_delay()
        self.assertTrue(2.7 <= delay1 <= 3.3)
        
        delay2 = self.supervisor.next_backoff_delay()
        self.assertTrue(4.5 <= delay2 <= 5.5)
        
        delay3 = self.supervisor.next_backoff_delay()
        self.assertTrue(9.0 <= delay3 <= 11.0)
        
        delay4 = self.supervisor.next_backoff_delay()
        self.assertTrue(18.0 <= delay4 <= 22.0)
        
        delay5 = self.supervisor.next_backoff_delay()
        self.assertTrue(54.0 <= delay5 <= 66.0)
        
        # Should stay at max
        delay6 = self.supervisor.next_backoff_delay()
        self.assertTrue(54.0 <= delay6 <= 66.0)

    def test_backoff_resets_after_connected(self):
        self.supervisor.next_backoff_delay()
        self.supervisor.next_backoff_delay()
        self.assertEqual(self.supervisor.backoff_index, 2)
        
        self.supervisor.mark_connected()
        self.assertEqual(self.supervisor.backoff_index, 0)

    def test_classifies_1011_as_recoverable(self):
        err = Exception("google.genai.errors.APIError: 1011 None. The service is currently unavailable")
        self.assertTrue(self.supervisor.classify_disconnect_error(err))
        
        err2 = Exception("ConnectionClosedError 1011")
        self.assertTrue(self.supervisor.classify_disconnect_error(err2))

    def test_classifies_service_unavailable_as_recoverable(self):
        err = Exception("The service is currently unavailable")
        self.assertTrue(self.supervisor.classify_disconnect_error(err))
        
        err2 = Exception("Internal error encountered")
        self.assertTrue(self.supervisor.classify_disconnect_error(err2))

    def test_classifies_auth_as_non_recoverable(self):
        err = Exception("API key invalid")
        self.assertFalse(self.supervisor.classify_disconnect_error(err))
        
        err2 = Exception("Permission denied")
        self.assertFalse(self.supervisor.classify_disconnect_error(err2))

    def test_queue_outbound_message_when_disconnected(self):
        self.supervisor.queue_outbound_message("Hello Sir", reason="disconnected")
        self.assertEqual(len(self.supervisor.outbound_queue), 1)
        self.assertEqual(self.supervisor.outbound_queue[0]["text"], "Hello Sir")

    def test_drain_outbound_messages_limit(self):
        self.supervisor.queue_outbound_message("Msg 1")
        self.supervisor.queue_outbound_message("Msg 2")
        self.supervisor.queue_outbound_message("Msg 3")
        
        drained = self.supervisor.drain_outbound_messages(limit=2)
        self.assertEqual(drained, ["Msg 1", "Msg 2"])
        self.assertEqual(len(self.supervisor.outbound_queue), 1)
        
        drained2 = self.supervisor.drain_outbound_messages()
        self.assertEqual(drained2, ["Msg 3"])
        self.assertEqual(len(self.supervisor.outbound_queue), 0)

    def test_pending_tool_result_storage(self):
        self.supervisor.record_tool_result_pending("web_search", "Found something", "call_1")
        self.assertEqual(len(self.supervisor.pending_tool_results), 1)
        self.assertEqual(self.supervisor.pending_tool_results[0]["tool"], "web_search")
        
        self.supervisor.clear_pending_tool_results()
        self.assertEqual(len(self.supervisor.pending_tool_results), 0)

    def test_supervisor_does_not_import_main_ui_actions(self):
        # This is a meta-test to ensure core/live_resilience is lean
        import os
        path = os.path.join("core", "live_resilience.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for forbidden in ["import main", "from main", "import ui", "from ui", "import actions", "from actions"]:
            self.assertNotIn(forbidden, content)

    def test_duplicate_tool_call_suppression(self):
        self.supervisor.record_tool_call("open_app", {"app_name": "Notepad"}, "Application 'Notepad' was not found")
        
        # Same call within 10s
        is_dup, res = self.supervisor.check_duplicate_tool_call("open_app", {"app_name": "Notepad"})
        self.assertTrue(is_dup)
        self.assertEqual(res, "Application 'Notepad' was not found")
        
        # Different args
        is_dup2, res2 = self.supervisor.check_duplicate_tool_call("open_app", {"app_name": "Calc"})
        self.assertFalse(is_dup2)
        
        # Different tool
        is_dup3, res3 = self.supervisor.check_duplicate_tool_call("web_search", {"query": "Notepad"})
        self.assertFalse(is_dup3)

if __name__ == "__main__":
    unittest.main()
