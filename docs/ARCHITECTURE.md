# Architecture (Local) - Meu Jarvis

This is a documentation-only overview of the current local repository structure. It summarizes what exists today without claiming production readiness.

For deeper contracts and phase history, see:
- `docs/MASTER_CONTRACT.md`
- `docs/MEMORY_ARCHITECTURE.md`
- `docs/MEMORY_SCHEMA.md`
- `docs/BRAIN_ROUTING.md`
- `docs/READ_ONLY_MEMORY_ADAPTER_DESIGN.md`
- `docs/RUNTIME_READ_ONLY_TEST_CONTRACT.md`

## High-Level Layers

## 1) Runtime + UI
- `main.py`: current runtime entry point. Builds the model session configuration, assembles the system instruction, and routes tool calls.
- `ui.py`: local UI.

## 2) Actions (Tools)
- `actions/`: concrete implementations of user-visible actions (open app, browser control, file operations, screen processing, etc.).
- These are invoked by tool/function calling from the runtime.

## 3) Task Agent
- `agent/`: planning/execution support (task queue, planner, executor, error handling).
- This is separate from the Brain Foundation and can be used by runtime tool calls.

## 4) Legacy Memory (JSON)
- `memory/`: legacy long-term memory used by the `save_memory` tool in runtime.
- This is still active and not migrated.

## 5) Memory Engine (SQLite + JSONL)
- `memory_engine/`: structured durable memory and auditing.
- Storage:
  - `data/jarvis_memory.db` (SQLite, local runtime file, gitignored)
  - `data/raw_events.jsonl` (JSONL audit log, local runtime file, gitignored)
- Read-only runtime support:
  - `runtime_adapter.py`: strict read-only retrieval (`mode=ro`) with bounded prompt formatting.
  - `runtime_context.py`: env-driven wrapper that returns either "" (default) or a bounded memory context block.

## 6) Brain Foundation (Deterministic v0)
- `brain/`: deterministic context detection + routing + validation.
- The Brain Foundation is standalone/testable and does not call an LLM.

## Prompt Assembly (Current)
In `main.py`, the system instruction is assembled from:
1. current date/time context
2. legacy memory string (if present)
3. read-only SQLite memory context (if enabled via env and available)
4. system prompt from `core/prompt.txt` (final authority by position)

## Boundary Summary
- No automatic memory writes to SQLite are introduced by the read-only integration.
- The read-only context is OFF by default and requires explicit environment configuration.
- Tool declarations and routing remain unchanged by the memory read-only addition.

