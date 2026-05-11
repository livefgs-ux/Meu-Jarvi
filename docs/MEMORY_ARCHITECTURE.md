# Memory Architecture

## Goal

The memory architecture creates a local, user-owned foundation for durable, auditable memory. It does not train a model, does not call cloud services, and does not modify the existing Jarvis runtime.

## Memory Layers

### Working Memory

Short-lived context for the active request. This is not durable by default.

### Episodic Memory

Session or event memories about what happened. These should be stored only when useful for future behavior or audit.

### Semantic / Structured Memory

Structured facts, rules, preferences, decisions, warnings, and procedures.

### Procedural Memory

Validated steps or methods that should influence future execution.

### Project Memory

Project-scoped technical context, decisions, constraints, and known state.

### Correction Memory

Records of mistakes and corrections that should change future routing or behavior.

### Decision Memory

Durable records of decisions, rationale, and scope.

### Warning Memory

Known risks, unsafe patterns, sensitive areas, or caution points.

## Why SQLite First

SQLite is local, auditable, portable, transactional, and available in the Python standard library. It is a safer v0 storage layer than a service, vector database, or cloud dependency.

## Why JSONL Audit Logs

JSONL gives a simple append-only raw event trail. It supports review and debugging without requiring a database viewer.

## Why Embeddings Are Future Work

Embeddings add dependency, indexing, privacy, and evaluation complexity. The first version uses explicit fields and keyword retrieval so behavior stays inspectable.

## Why Obsidian Is Excluded

This foundation is not an Obsidian integration. Obsidian may be useful as a human-facing note interface later, but the core memory engine should remain independent and local-first.

## Graphify Scope

Graphify is not the main memory. It may later become an optional adapter for project or code structure memory, but it is not part of v0 storage or retrieval.

## Manual CLI

The memory CLI is a manual test surface only. It exists so the Memory Engine can be initialized, written to, searched, and inspected before any runtime Jarvis integration is approved.

The CLI is not automatic learning, not a background process, and not connected to the running Jarvis app. Every write through the CLI is explicit and goes through Memory Engine validation and privacy checks.

The CLI should be used to validate memory behavior, schema decisions, and auditability before any future runtime connection is considered.

The CLI supports both invocation styles:

- `python -m tools.memory_cli ...`
- `python tools/memory_cli.py ...`

The recommended developer form is `python -m tools.memory_cli ...` because it uses package-style imports. Direct script invocation is supported for convenience from the repository root.

## Read-Only Runtime Adapter (Design Only)

Before any runtime integration is implemented, a read-only adapter should be introduced to allow the Jarvis runtime to retrieve a bounded memory context from `data/jarvis_memory.db`.

This adapter must:

- Open SQLite in strict read-only mode (`mode=ro`).
- Never write to SQLite and never write to `data/raw_events.jsonl`.
- Never create, validate, promote, archive, or update memories.
- Only retrieve a small context for prompt insertion with strict limits.

This is intended as the first step toward safe runtime usage: read-only retrieval first, no automatic writing.

CLI lifecycle controls allow memories to be inspected, promoted through statuses, deprecated, archived, and audited manually. This keeps validation explicit before runtime integration.

Memories should be reviewed and promoted through lifecycle statuses instead of blindly trusted at write time.
