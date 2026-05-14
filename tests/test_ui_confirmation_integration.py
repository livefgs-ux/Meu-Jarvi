import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

async def async_mock(*args, **kwargs):
    pass

class TestUIConfirmationIntegration(unittest.TestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()
        os.environ["JARVIS_TOOL_CALL_GATE"] = "true"
        # Avoid real sounddevice or other hardware deps if possible
        sys.modules['sounddevice'] = MagicMock()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    async def async_test_execute_tool_confirms_and_allows(self):
        from main import JarvisLive
        mock_ui = MagicMock()

        # Mock UI confirmation to return True (Approved)
        future = asyncio.Future()
        future.set_result(True)
        mock_ui.request_confirmation.return_value = future

        jarvis = JarvisLive(mock_ui)
        jarvis.session = MagicMock()
        jarvis.session.send_client_content = MagicMock(side_effect=async_mock)
        jarvis._loop = asyncio.get_event_loop()

        fc = MagicMock()
        fc.name = "file_controller"
        fc.args = {"action": "delete", "path": "test.txt"}
        fc.id = "call_123"

        # We need to ensure _apply_tool_call_gate returns 'confirm'

        with patch("main.file_controller", return_value="Deleted."):
            resp = await jarvis._execute_tool(fc)

        self.assertEqual(resp.response["result"], "Deleted.")
        mock_ui.request_confirmation.assert_called_once()

    async def async_test_execute_tool_confirms_and_denies(self):
        from main import JarvisLive
        mock_ui = MagicMock()

        # Mock UI confirmation to return False (Denied)
        future = asyncio.Future()
        future.set_result(False)
        mock_ui.request_confirmation.return_value = future

        jarvis = JarvisLive(mock_ui)
        jarvis.session = MagicMock()
        jarvis.session.send_client_content = MagicMock(side_effect=async_mock)
        jarvis._loop = asyncio.get_event_loop()

        fc = MagicMock()
        fc.name = "file_controller"
        fc.args = {"action": "delete", "path": "test.txt"}
        fc.id = "call_123"

        resp = await jarvis._execute_tool(fc)

        self.assertEqual(resp.response["result"], "denied")
        self.assertEqual(resp.response["error"], "User denied the request.")

    def test_integration_flow(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_test_execute_tool_confirms_and_allows())
            loop.run_until_complete(self.async_test_execute_tool_confirms_and_denies())
        finally:
            loop.close()

if __name__ == "__main__":
    unittest.main()
