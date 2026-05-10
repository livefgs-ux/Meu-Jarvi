import unittest

from memory_engine.schemas import (
    normalize_memory_type,
    normalize_status,
    validate_confidence,
    validate_importance,
    validate_memory_scope_policy,
    validate_scope,
)


class MemorySchemaTests(unittest.TestCase):
    def test_valid_scope_forms(self):
        self.assertEqual(validate_scope("global"), "global")
        self.assertEqual(validate_scope("session"), "session")
        self.assertEqual(validate_scope("temporary"), "temporary")
        self.assertEqual(validate_scope("project:Meu-Jarvi"), "project:Meu-Jarvi")

    def test_invalid_scope_rejected(self):
        with self.assertRaises(ValueError):
            validate_scope("project:")

    def test_type_status_and_scales(self):
        self.assertEqual(normalize_memory_type("global_rule"), "GLOBAL_RULE")
        self.assertEqual(normalize_status("Validated"), "validated")
        self.assertEqual(validate_importance(10), 10)
        self.assertEqual(validate_confidence(0.8), 0.8)

    def test_memory_scope_policy_rejects_unsafe_global_project_data(self):
        with self.assertRaises(ValueError):
            validate_memory_scope_policy("PROJECT_CONTEXT", "global")
        with self.assertRaises(ValueError):
            validate_memory_scope_policy("TECHNICAL_STATE", "global")

    def test_memory_scope_policy_rejects_non_global_global_rule(self):
        with self.assertRaises(ValueError):
            validate_memory_scope_policy("GLOBAL_RULE", "project:Meu-Jarvi")

    def test_memory_scope_policy_accepts_valid_pairs(self):
        validate_memory_scope_policy("GLOBAL_RULE", "global")
        validate_memory_scope_policy("PROJECT_CONTEXT", "project:Meu-Jarvi")
        validate_memory_scope_policy("PROJECT_CONTEXT", "session")
        validate_memory_scope_policy("TECHNICAL_STATE", "temporary")


if __name__ == "__main__":
    unittest.main()
