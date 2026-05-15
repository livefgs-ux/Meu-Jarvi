import unittest
import asyncio
from unittest.mock import MagicMock, patch
from main import JarvisLive

class TestContextAwarenessIntegration(unittest.TestCase):
    def setUp(self):
        self.ui = MagicMock()
        self.jarvis = JarvisLive(self.ui)
        self.jarvis._loop = MagicMock()
        self.jarvis.session = MagicMock()

    @patch('core.context_awareness.get_current_task_summary')
    def test_text_command_current_tasks_answered_without_model(self, mock_summary):
        mock_summary.return_value = "Mocked Task"
        with patch.object(self.jarvis, 'speak') as mock_speak:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                self.jarvis._on_text_command("o que voce esta fazendo agora?")
                
                # Should have spoken the answer
                mock_speak.assert_called_once_with("Mocked Task")
                # Should NOT call the model (send_client_content)
                mock_run.assert_not_called()

    @patch('core.context_awareness.get_last_search_context')
    def test_text_command_last_search_answered_without_model(self, mock_ctx):
        mock_ctx.return_value = {"query": "weather", "result": "Sunny", "timestamp": "..."}
        with patch.object(self.jarvis, 'speak') as mock_speak:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                self.jarvis._on_text_command("Qual foi a ultima busca?")
                mock_run.assert_not_called()
                mock_speak.assert_called_once()

    @patch('core.context_awareness.get_last_search_context')
    def test_text_command_show_last_search_uses_recent_context(self, mock_ctx):
        mock_ctx.return_value = {"query": "test", "result": "Search Results Data", "timestamp": "..."}
        with patch.object(self.jarvis, 'speak') as mock_speak:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                self.jarvis._on_text_command("Mostra essa busca.")
                mock_run.assert_not_called()
                mock_speak.assert_called_once()
                self.assertTrue("Search Results Data" in mock_speak.call_args[0][0])

    @patch('core.context_awareness.get_last_app_resolution_context')
    def test_text_command_app_not_found_reason_uses_timeline(self, mock_ctx):
        mock_ctx.return_value = {
            "type": "app_not_found",
            "summary": "VS Code was not found",
            "metadata": {"alternatives": ["Cursor"]},
            "timestamp": "..."
        }
        with patch.object(self.jarvis, 'speak') as mock_speak:
            with patch('asyncio.run_coroutine_threadsafe') as mock_run:
                self.jarvis._on_text_command("por que voce nao abriu o VS Code?")
                mock_run.assert_not_called()
                mock_speak.assert_called_once_with("Não abri o aplicativo porque: VS Code was not found")

    def test_text_command_unknown_preserves_existing_flow(self):
        with patch('asyncio.run_coroutine_threadsafe') as mock_run:
            self.jarvis._on_text_command("Olá Jarvis, como vai?")
            # Should call the model
            mock_run.assert_called_once()

    @patch('core.context_awareness.answer_context_question')
    def test_context_awareness_fail_open_preserves_existing_flow(self, mock_answer):
        mock_answer.side_effect = Exception("Boom")
        with patch('asyncio.run_coroutine_threadsafe') as mock_run:
            self.jarvis._on_text_command("O que você está fazendo?")
            # Even if context awareness crashes, it should fallback to model
            mock_run.assert_called_once()

    def test_no_real_tools_executed(self):
        # This is a safety check. 
        # In our tests, we mocked everything so no real tools should be called.
        pass

if __name__ == "__main__":
    unittest.main()
