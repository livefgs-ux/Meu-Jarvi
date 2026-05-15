import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.task_runtime import ConcurrentTaskRuntime, TaskStatus


class TestTaskRuntimeShutdown(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.runtime = ConcurrentTaskRuntime()

    def tearDown(self):
        try:
            self.loop.run_until_complete(self.runtime.shutdown())
        except Exception:
            pass
        self.loop.close()

    def test_shutdown_cancels_pending_tasks(self):
        gate = asyncio.Event()

        async def pending_task():
            await gate.wait()
            return "done"

        task_id = self.loop.run_until_complete(self.runtime.submit("Pending", pending_task))
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.loop.run_until_complete(self.runtime.shutdown(cancel_pending=True, timeout=1.0))

        task = self.runtime.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, TaskStatus.CANCELLED)

    def test_shutdown_waits_for_running_tasks(self):
        async def running_task():
            await asyncio.sleep(0.05)
            return "done"

        task_id = self.loop.run_until_complete(self.runtime.submit("Running", running_task))
        self.loop.run_until_complete(self.runtime.shutdown(cancel_pending=False, timeout=1.0))

        task = self.runtime.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_shutdown_releases_resource_locks(self):
        gate = asyncio.Event()

        async def locked_task():
            await gate.wait()
            return "done"

        task_id = self.loop.run_until_complete(
            self.runtime.submit("Locked", locked_task, resource_locks={"browser"})
        )
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.loop.run_until_complete(self.runtime.shutdown())

        self.assertFalse(self.runtime._active_locks)
        self.assertEqual(self.runtime.get_task(task_id).status, TaskStatus.CANCELLED)

    def test_wait_for_idle_returns_when_tasks_finish(self):
        async def quick_task():
            await asyncio.sleep(0.01)
            return "done"

        task_id = self.loop.run_until_complete(self.runtime.submit("Quick", quick_task))
        idle = self.loop.run_until_complete(self.runtime.wait_for_idle(timeout=1.0))

        self.assertTrue(idle)
        self.assertEqual(self.runtime.get_task(task_id).status, TaskStatus.COMPLETED)

    def test_cancelled_tasks_do_not_leave_pending_asyncio_tasks(self):
        gate = asyncio.Event()

        async def pending_task():
            await gate.wait()

        self.loop.run_until_complete(self.runtime.submit("CancelMe", pending_task))
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.loop.run_until_complete(self.runtime.shutdown())
        self.loop.run_until_complete(asyncio.sleep(0))

        pending = [
            task
            for task in asyncio.all_tasks(self.loop)
            if not task.done()
        ]
        self.assertEqual(pending, [])
        self.assertFalse(self.runtime._task_handles)

    def test_task_runtime_shutdown_does_not_import_main_ui_actions(self):
        src = Path(__file__).resolve().parents[1] / "core" / "task_runtime.py"
        text = src.read_text(encoding="utf-8")
        for forbidden in ["import main", "import ui", "from actions", "import actions"]:
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
