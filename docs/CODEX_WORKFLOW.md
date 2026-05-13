# Codex Workflow (Local)

This repo evolved using phased, audited changes. This document describes a lightweight workflow to keep changes safe and reviewable.

## Ground Rules
- Prefer local repository state as the source of truth during audits.
- Do not change runtime behavior without tests.
- Keep changes scoped to the approved phase boundaries.
- Do not commit runtime data (`data/*.db`, `data/*.jsonl`) or secrets (`config/api_keys.json`).

## Recommended Loop
1. Read-only audit:
   - `git status --short`
   - inspect relevant files (no edits)
2. Write a patch plan (docs-first) when changing runtime boundaries.
3. Implement minimal changes.
4. Run local tests:
   - `python -m unittest discover tests`
5. Re-audit:
   - `git diff`
   - confirm no secrets/runtime data were touched

## Memory Work
- Manual writes go through the Memory CLI (`tools/memory_cli.py`) for explicit review.
- Runtime uses read-only memory context by default (toggle OFF).
- Do not add automatic memory writes without a dedicated design + contract + tests phase.

## After Large Changes
- Run an integrity audit (git state, file signatures for runtime data if present, tests).
- Consider creating a local checkpoint/tag only after review.

