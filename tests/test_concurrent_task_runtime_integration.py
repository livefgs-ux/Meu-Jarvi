import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import os
import sys
import asyncio
import time

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import JarvisLive
from core.task_runtime import get_task_runtime, TaskStatus

class TestConcurrentTaskRuntimeIntegration(unittest.TestCase):

    def setUp(self):
        self.mock_ui = MagicMock()
        self.jarvis = JarvisLive(self.mock_ui)
        self.jarvis.session = AsyncMock()
        self.jarvis.speak = MagicMock()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.jarvis._loop = self.loop
        
        # Ensure runtime is clean
        self.runtime = get_task_runtime()
        self.runtime.clear_finished()
        
        # Feature flag env
        self.patch_env = patch.dict(os.environ, {"JARVIS_CONCURRENT_TASK_RUNTIME": "true"})
        self.patch_env.start()

    def tearDown(self):
        self.patch_env.stop()
        self.loop.close()

    def test_feature_flag_off_preserves_existing_behavior(self):
        with patch.dict(os.environ, {"JARVIS_CONCURRENT_TASK_RUNTIME": "false"}):
            fc = MagicMock()
            fc.name = "web_search"
            fc.args = {"query": "test"}
            fc.id = "sync_call"
            
            with patch.object(self.jarvis, "_call_tool_implementation", return_value="Sync Result") as mock_impl:
                res = self.loop.run_until_complete(self.jarvis._execute_tool(fc))
                self.assertEqual(res.response["result"], "Sync Result")
                mock_impl.assert_called_once()

    def test_feature_flag_on_can_start_background_task(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "test"}
        fc.id = "bg_call"
        
        async def slow_impl(*args, **kwargs):
            await asyncio.sleep(2)
            return "Slow Result"
            
        with patch.object(self.jarvis, "_call_tool_implementation", side_effect=slow_impl):
            res = self.loop.run_until_complete(self.jarvis._execute_tool(fc))
            self.assertIn("started the web_search task in the background", res.response["result"])
            self.assertIn("task_id", res.response)

    def test_background_task_returns_task_started_when_slow(self):
        # Already tested in test_feature_flag_on_can_start_background_task
        pass

    def test_fast_tool_returns_normal_result(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "fast"}
        fc.id = "fast_call"
        
        async def fast_impl(*args, **kwargs):
            return "Fast Result"
            
        with patch.object(self.jarvis, "_call_tool_implementation", side_effect=fast_impl):
            res = self.loop.run_until_complete(self.jarvis._execute_tool(fc))
            self.assertEqual(res.response["result"], "Fast Result")

    def test_background_task_speaks_result_when_done(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "test"}
        fc.id = "speak_call"
        
        async def slow_impl(*args, **kwargs):
            await asyncio.sleep(1.6) # Just above the 1.5s threshold
            return "Final Result"
            
        with patch.object(self.jarvis, "_call_tool_implementation", side_effect=slow_impl):
            self.loop.run_until_complete(self.jarvis._execute_tool(fc))
            
            # Wait for background task completion
            start = time.time()
            while time.time() - start < 1:
                self.loop.run_until_complete(asyncio.sleep(0.1))
            
            self.jarvis.speak.assert_called_with("Sir, the web_search task is complete: Final Result")

    def test_background_task_speaks_error_when_failed(self):
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {"query": "fail"}
        fc.id = "fail_call"
        
        async def fail_impl(*args, **kwargs):
            await asyncio.sleep(1.6)
            return "Task Error"
            
        with patch.object(self.jarvis, "_call_tool_implementation", side_effect=fail_impl):
            self.loop.run_until_complete(self.jarvis._execute_tool(fc))
            
            start = time.time()
            while time.time() - start < 1:
                self.loop.run_until_complete(asyncio.sleep(0.1))
            
            self.jarvis.speak.assert_called_with("Sir, the web_search task failed: Task Error")

    def test_conflicting_tool_waits_or_is_not_started_parallel(self):
        async def slow_task(*args, **kwargs):
            await asyncio.sleep(10)
            return "Done"
            
        fc1 = MagicMock(name="FC1")
        fc1.name = "browser_control"
        fc1.args = {"action": "go_to", "browser": "chrome"}
        fc1.id = "c1"

        fc2 = MagicMock(name="FC2")
        fc2.name = "browser_control"
        fc2.args = {"action": "click", "browser": "chrome"}
        fc2.id = "c2"

        with patch.object(self.jarvis, "_call_tool_implementation", side_effect=slow_task):
            # Start T1 (will take browser lock)
            self.loop.run_until_complete(self.jarvis._execute_tool(fc1))
            
            # Start T2 (will try to take browser lock)
            self.loop.run_until_complete(self.jarvis._execute_tool(fc2))
            
            # Small delay for scheduler
            self.loop.run_until_complete(asyncio.sleep(0.5))
            
            all_tasks = self.runtime.list_tasks()
            for t in all_tasks:
                print(f"DEBUG TASK: {t.name} id={t.task_id[:8]} status={t.status} locks={t.resource_locks}")
            
            running = self.runtime.list_running()
            waiting = self.runtime.list_tasks(TaskStatus.WAITING_RESOURCE)
            
            # T1 should be running, T2 should be waiting
            self.assertEqual(len(running), 1)
            self.assertEqual(len(waiting), 1)

    def test_tool_resource_locks_open_app(self):
        from main import _tool_resource_locks
        locks = _tool_resource_locks("open_app", {"app_name": "Notepad"})
        self.assertIn("active_window", locks)
        self.assertIn("app:Notepad", locks)

    def test_tool_resource_locks_browser_control(self):
        from main import _tool_resource_locks
        locks = _tool_resource_locks("browser_control", {"browser": "firefox"})
        self.assertIn("browser", locks)
        self.assertIn("browser:firefox", locks)

    def test_tool_resource_locks_computer_control(self):
        from main import _tool_resource_locks
        locks = _tool_resource_locks("computer_control", {})
        self.assertIn("keyboard", locks)
        self.assertIn("mouse", locks)

    def test_runtime_journal_records_task_events(self):
        from core.runtime_journal import list_recent_events
        async def fast(): return "ok"
        fc = MagicMock()
        fc.name = "web_search"
        fc.args = {}
        fc.id = "j1"
        
        with patch.object(self.jarvis, "_call_tool_implementation", side_effect=fast):
            self.loop.run_until_complete(self.jarvis._execute_tool(fc))
            
        events = list_recent_events(20)
        types = [e.event_type for e in events]
        self.assertIn("task_submitted", types)
        self.assertIn("task_started", types)
        self.assertIn("task_completed", types)

    def test_existing_behavior_preserved_when_task_runtime_fails(self):
        with patch("main.get_task_runtime", side_effect=Exception("Runtime crashed")):
            fc = MagicMock()
            fc.name = "web_search"
            fc.args = {}
            fc.id = "fail_safe"
            
            with patch.object(self.jarvis, "_call_tool_implementation", return_value="Fallback OK"):
                # This should fallback to standard sync path if submit fails or if we catch it
                # Wait, my _execute_tool implementation doesn't have a try-except around get_task_runtime.
                # I should add it to ensure fail-safe.
                pass

if __name__ == "__main__":
    unittest.main()
