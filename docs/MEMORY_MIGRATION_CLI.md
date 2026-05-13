# Meu Jarvis - Memory Migration CLI

## 1. Purpose
`tools/migrate_legacy_memory.py` is an offline maintenance/admin CLI to analyze, review, and (optionally) migrate legacy JSON memory into the new SQLite Memory Engine in a controlled way.

This tool:
- is not part of the normal Jarvis runtime
- does not change `main.py`
- does not change the runtime `save_memory` tool behavior
- does not touch the real runtime DB/log by default

## 2. Current State
The CLI supports:
- safe dry-run reports (text and JSON)
- legacy JSON parsing (including UTF-8 BOM via `utf-8-sig`)
- privacy guard checks (blocked content)
- heuristic in-memory deduplication
- unknown category detection
- `--allow-missing` for missing legacy files (safe empty report)
- execution as module and as direct script
- controlled `--apply` to explicit DB/log paths (never the real runtime paths)
- mandatory human-confirmation guardrail: `--confirm-apply`
- safe review bundle export for human review: `--review-bundle-path`

## 3. Safety Principles
- Dry-run is the default behavior.
- Candidate `content` is omitted by default in both text and JSON outputs.
- Blocked (secret-like) content is never printed or exported.
- The real runtime DB `data/jarvis_memory.db` is rejected for `--apply`.
- The real runtime event log `data/raw_events.jsonl` is rejected for `--apply`.
- The tool does not create `memory/long_term.json`.
- `config/api_keys.json` must never be read or exposed by this tool.
- `--apply` requires `--confirm-apply` to prevent accidental writes.
- Review bundle export requires an explicit, safe path (and blocks sensitive paths).

## 4. Supported Execution Modes
Module invocation:
```bash
python -m tools.migrate_legacy_memory ...
```

Direct script invocation:
```bash
python tools/migrate_legacy_memory.py ...
```

Both are supported.

## 5. Basic Dry-Run
```bash
python tools/migrate_legacy_memory.py --legacy-path path\\to\\legacy.json --project meu-jarvis
```

Notes:
- does not write anything
- prints a safe summary
- does not print full candidate content by default

## 6. Missing Legacy File
Without `--allow-missing`:
- missing file returns a controlled error (exit code 2)

With `--allow-missing`:
```bash
python tools/migrate_legacy_memory.py --legacy-path memory\\long_term.json --project meu-jarvis --allow-missing
```

Expected:
- exit code 0
- "Nothing to migrate" (totals are zero)
- does not create `memory/long_term.json`

## 7. JSON Output
Safe JSON (no content by default):
```bash
python tools/migrate_legacy_memory.py --legacy-path path\\to\\legacy.json --project meu-jarvis --json
```

Including content explicitly (local use only):
```bash
python tools/migrate_legacy_memory.py --legacy-path path\\to\\legacy.json --project meu-jarvis --json --include-content
```

Notes:
- use `--include-content` only when needed and only locally
- blocked content stays hidden even with `--include-content`

## 8. Review Bundle Export
Dry-run review bundle (safe by default):
```bash
python tools/migrate_legacy_memory.py --legacy-path path\\to\\legacy.json --project meu-jarvis --review-bundle-path C:\\Temp\\jarvis_review.json
```

Overwrite explicitly:
```bash
python tools/migrate_legacy_memory.py --legacy-path path\\to\\legacy.json --project meu-jarvis --review-bundle-path C:\\Temp\\jarvis_review.json --overwrite-review-bundle
```

Notes:
- creates a safe JSON bundle for human review
- does not apply changes by itself
- does not create DB/log by itself
- the "Review bundle written: ..." message goes to stderr (stdout remains clean for `--json`)

## 9. Controlled Apply Mode
Apply is controlled and must never target real runtime paths.

Example with explicit temp/test DB paths:
```bat
python tools\\migrate_legacy_memory.py ^
  --legacy-path C:\\Temp\\legacy.json ^
  --project meu-jarvis ^
  --apply ^
  --confirm-apply ^
  --db-path C:\\Temp\\jarvis_migration_test.db ^
  --event-log-path C:\\Temp\\jarvis_migration_events.jsonl
```

Behavior:
- `--apply` requires `--confirm-apply`
- `--apply` requires `--db-path` and `--event-log-path`
- real runtime paths under `data/` are rejected
- blocked / duplicate / requires_review candidates are skipped by default
- `--include-review` is required to apply `requires_review=True` candidates

## 10. Apply + Review Bundle
```bat
python tools\\migrate_legacy_memory.py ^
  --legacy-path C:\\Temp\\legacy.json ^
  --project meu-jarvis ^
  --apply ^
  --confirm-apply ^
  --db-path C:\\Temp\\jarvis_migration_test.db ^
  --event-log-path C:\\Temp\\jarvis_migration_events.jsonl ^
  --review-bundle-path C:\\Temp\\jarvis_migration_review.json
```

This produces:
- a temp/test DB + event log
- a safe review bundle showing applied/skipped/skip_reason

## 11. Path Protection Rules
The CLI rejects:
- `data/jarvis_memory.db` and `data/raw_events.jsonl` as `--apply` targets
- any review bundle target inside the repo `data/` directory
- review bundle targets that resolve to:
  - `config/api_keys.json`
  - `.env`
  - `memory/long_term.json`
- `--db-path` equal to `--event-log-path`
- review bundle paths without `.json`
- review bundle paths whose parent directory does not exist
- review bundle overwrite unless `--overwrite-review-bundle` is provided

## 12. Candidate Handling
- `blocked=True` is never applied
- `duplicate=True` is never applied
- `requires_review=True` is skipped by default
- `--include-review` allows applying review candidates if they are not blocked/duplicates
- candidate content is omitted by default in reports and bundles

## 13. Review Bundle Format
Top-level fields:
- `bundle_type`
- `bundle_version`
- `safe_by_default`
- `content_included`
- `summary`
- `apply`
- `breakdowns`
- `missing_source`
- `warning`
- `candidates`

Candidate fields include:
- `source_category`, `source_key`
- `memory_type`, `scope`, `project`, `status`
- `requires_review`
- `blocked`, `block_reason`
- `duplicate`, `duplicate_of`
- `unknown_category`
- `applied`, `skipped`, `skip_reason`
- `content` only when explicitly requested and only for non-blocked candidates

## 14. Recommended Workflow
1. Run a safe dry-run (no content).
2. Export a safe review bundle.
3. Review summary and skip/blocked/duplicate sections.
4. Fix or curate the legacy JSON if needed.
5. Run controlled apply to a temp/test DB only.
6. Validate results via retriever/search against the temp DB.
7. Export a post-apply review bundle and review again.
8. Any real runtime migration requires a separate future phase, backups, and explicit approval.

## 15. Prohibited Examples
Do not attempt to write to the real runtime DB/log:
```bat
python tools\\migrate_legacy_memory.py --legacy-path memory\\long_term.json --apply --confirm-apply --db-path data\\jarvis_memory.db --event-log-path data\\raw_events.jsonl
```

Do not write review bundles into `data/`:
```bat
python tools\\migrate_legacy_memory.py --legacy-path legacy.json --review-bundle-path data\\review.json
```

Avoid `--include-content` unless absolutely necessary (may expose normal PII that is not secret-like).

## 16. Current Limitations
- does not migrate the real runtime DB/log (by design)
- does not change runtime `save_memory`
- does not integrate into runtime
- does not create `memory/long_term.json`
- dedupe is heuristic
- human review is still required for safe migration decisions

## 17. Test Coverage
Tests cover:
- dry-run safety
- allow-missing behavior
- UTF-8 BOM parsing
- safe text/JSON outputs
- controlled apply (explicit temp paths + confirm guardrail)
- review bundle export and path protections
- blocked content never leaking
- module and direct script execution support

