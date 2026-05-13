# Memory Engine (SQLite + JSONL)

This document describes the local Memory Engine implemented in `memory_engine/`.

See also:
- `docs/MEMORY_ARCHITECTURE.md`
- `docs/MEMORY_SCHEMA.md`
- `docs/READ_ONLY_MEMORY_ADAPTER_DESIGN.md`

## Goals
- Local, owned, auditable memory.
- Explicit, validated writes (no background "save everything").
- Read-only runtime consumption first.

## Storage
- SQLite DB: `data/jarvis_memory.db` (runtime local file, gitignored)
- JSONL event log: `data/raw_events.jsonl` (append-only audit trail, gitignored)

## Record Shape (Conceptual)
Memories are stored as structured records with:
- type (e.g., GLOBAL_RULE, PROJECT_CONTEXT, TECHNICAL_STATE, WARNING, DECISION, PROCEDURE, etc.)
- scope (global, project:<name>, session, temporary)
- project (optional, when project-scoped)
- status (observed, candidate, confirmed, validated, conflicted, deprecated, archived)
- importance (int)
- confidence (float)
- source (string)
- timestamps

## Scope Policy (Enforced)
- GLOBAL_RULE must use scope=global.
- PROJECT_CONTEXT cannot use scope=global.
- TECHNICAL_STATE cannot use scope=global.

## Privacy Guard
The privacy guard blocks obvious credentials/secrets before they can be stored, including:
- API keys
- tokens
- passwords
- private keys
- .env-like content

## Read-Only Runtime Consumption
Two components exist:
- `memory_engine/runtime_adapter.py`: opens SQLite using read-only URI mode and retrieves bounded context.
- `memory_engine/runtime_context.py`: environment-driven wrapper used by runtime.

Default behavior:
- OFF by default. When disabled (or misconfigured), returns an empty string.

## Tooling
- Manual CLI: `tools/memory_cli.py` (explicit writes only; safe for manual review and auditing)
- Preview harness: `tools/memory_context_preview.py` (read-only; prints bounded prompt block)

## Non-Goals (Current)
- Automatic runtime writes to SQLite.
- Migration of legacy JSON memory into SQLite.
- Embeddings/vector search.

