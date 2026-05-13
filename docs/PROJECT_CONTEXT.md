# Project Context - Meu Jarvis (Local)

This document is a human-readable project context snapshot for the local repository in `F:\Meu Jarvi`.

Status: in progress / personal local use.

## Identity
- Project name: Meu Jarvis
- Origin: legal fork of Mark-XXXIX / MARK XXXIX
- Primary language: Python
- Entry point: `main.py`
- UI: `ui.py`

## What Is Implemented (Observed Locally)
- Actions/tooling layer in `actions/` (app/browser/desktop/file/screen/etc. actions).
- Task execution/queue layer in `agent/`.
- Brain Foundation v0 (deterministic) in `brain/` (context detection, routing, validation, standalone brain facade).
- Memory Engine in `memory_engine/` (SQLite memory + JSONL audit log + schema/policy validation + privacy guard).
- Read-only runtime memory context injection in `main.py` (toggle-gated and OFF by default).
- Manual memory CLI in `tools/memory_cli.py`.
- Manual read-only preview harness in `tools/memory_context_preview.py`.
- Tests covering boundaries, policy enforcement, read-only behavior, and baseline runtime integration checks.

## What Is Explicitly Not Implemented (Yet)
- Automatic memory writes from runtime into the SQLite Memory Engine.
- Migration of legacy JSON memory (`memory/`) into SQLite.
- Embeddings/vector search.
- Obsidian integration.
- Graphify as the main memory store.

## Runtime Memory Note (Important)
The existing `save_memory` tool still writes to the legacy JSON memory via `memory/memory_manager.py`.

The SQLite Memory Engine exists, but runtime writes to it are not treated as migrated/primary at this stage.

