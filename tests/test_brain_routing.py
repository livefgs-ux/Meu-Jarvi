import unittest

from brain.context_detector import detect_context
from brain.router import choose_mode


class BrainRoutingTests(unittest.TestCase):
    def test_detect_context_detects_debugging(self):
        context = detect_context("Traceback failed with an exception in this bug")
        self.assertEqual(context["task_type"], "debugging")
        self.assertEqual(context["recommended_mode"], "Debugger")

    def test_detect_context_detects_sysadmin(self):
        context = detect_context("pip inside my python venv uses PATH on Windows")
        self.assertEqual(context["task_type"], "sysadmin")
        self.assertIn("pip", context["detected_keywords"])
        self.assertTrue(context["needs_execution"])

    def test_detect_context_detects_memory_task(self):
        context = detect_context("Remember this as a brain global rule and learn it")
        self.assertEqual(context["task_type"], "memory")
        self.assertTrue(context["needs_memory"])

    def test_router_selects_security_reviewer_for_high_risk_secret_delete(self):
        context = detect_context("delete this token and password from the project")
        self.assertEqual(context["risk_level"], "high")
        self.assertEqual(choose_mode(context), "Security Reviewer")

    def test_router_selects_memory_engineer(self):
        context = detect_context("Add this to memory as project context")
        self.assertEqual(choose_mode(context), "Memory Engineer")

    def test_router_selects_debugger(self):
        context = detect_context("debug this exception")
        self.assertEqual(choose_mode(context), "Debugger")

    def test_ambiguous_architecture_memory_plan_prefers_memory_engineer(self):
        context = detect_context("analyze this architecture and memory plan")
        self.assertEqual(context["task_type"], "memory")
        self.assertEqual(choose_mode(context), "Memory Engineer")

    def test_delete_token_from_config_routes_to_security_reviewer(self):
        context = detect_context("delete token from config")
        self.assertEqual(context["risk_level"], "high")
        self.assertEqual(choose_mode(context), "Security Reviewer")

    def test_pip_install_failed_with_traceback_prefers_debugger(self):
        context = detect_context("pip install failed with traceback")
        self.assertEqual(context["task_type"], "debugging")
        self.assertEqual(choose_mode(context), "Debugger")

    def test_explain_why_error_happened_routes_to_debugger(self):
        context = detect_context("explain why this error happened")
        self.assertEqual(choose_mode(context), "Debugger")
        self.assertNotEqual(choose_mode(context), "Executor")

    def test_why_pip_install_failed_is_not_teacher(self):
        context = detect_context("why did pip install fail?")
        self.assertEqual(choose_mode(context), "Debugger")
        self.assertNotEqual(choose_mode(context), "Teacher")

    def test_pure_teaching_requests_still_route_to_teacher(self):
        for text in ("explain this concept", "teach me how SQLite works"):
            with self.subTest(text=text):
                self.assertEqual(choose_mode(detect_context(text)), "Teacher")

    def test_traceback_modulenotfounderror_why_routes_to_debugger(self):
        context = detect_context("traceback says ModuleNotFoundError, why?")
        self.assertEqual(choose_mode(context), "Debugger")

    def test_risk_classification_high_for_sensitive_terms(self):
        for text in (
            "delete the credential",
            "remove this token",
            "password is exposed",
            "api key leaked",
        ):
            with self.subTest(text=text):
                self.assertEqual(detect_context(text)["risk_level"], "high")

    def test_risk_classification_low_for_normal_explanation(self):
        context = detect_context("explain why memory scope matters")
        self.assertEqual(context["risk_level"], "low")

    def test_execution_like_requests_are_medium_risk(self):
        for text in ("run the test", "apply this patch", "modify the file"):
            with self.subTest(text=text):
                self.assertEqual(detect_context(text)["risk_level"], "medium")


if __name__ == "__main__":
    unittest.main()
