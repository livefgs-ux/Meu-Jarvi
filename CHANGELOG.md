# Changelog

This changelog is a lightweight local summary. For authoritative history, use `git log`.

## 2026-05-11
- Added Memory Engine (SQLite + JSONL audit) with schema/policy validation and privacy guard.
- Added Brain Foundation (deterministic v0 routing/validation).
- Added manual Memory CLI and read-only preview harness.
- Added strict read-only runtime adapter and env-driven runtime wrapper.
- Added toggle-gated read-only memory context insertion into `main.py` (OFF by default).
- Added baseline tests that inspect `main.py` via AST/text without importing runtime dependencies.

