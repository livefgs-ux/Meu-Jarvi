import unittest

from brain.validator import validate_brain_request, validate_memory_request


class BrainScopeTests(unittest.TestCase):
    def test_validator_uses_memory_engine_policy_for_unsafe_scope(self):
        with self.assertRaises(ValueError):
            validate_memory_request(
                "TECHNICAL_STATE",
                "global",
                "Meu-Jarvi uses temporary memory test databases.",
            )

    def test_validator_flags_memory_scope_risk(self):
        result = validate_brain_request(
            "Save this project context as a global memory rule",
            project=None,
        )
        self.assertTrue(result["memory_scope_risk"])
        self.assertTrue(result["missing_project_context"])
        self.assertEqual(result["mode"], "Memory Engineer")


if __name__ == "__main__":
    unittest.main()
