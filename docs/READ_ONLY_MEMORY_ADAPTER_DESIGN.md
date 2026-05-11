# Read-Only Memory Adapter Design (Phase 6A)

## Purpose

Design a safe, read-only adapter that allows the Jarvis runtime to retrieve a small, relevant memory context from `data/jarvis_memory.db` and format it for prompt insertion, without writing anything.

This is a design-only phase. No runtime integration is implemented here.

## Non-Goals

- No runtime integration in `main.py` or `ui.py`.
- No database writes, no JSONL writes, no memory creation, no lifecycle operations.
- No Gemini calls, no external APIs, no internet.
- No Graphify or Obsidian integration.
- No embeddings, no vector DB, no autonomous learning, no “save everything”.
- No changes to existing Jarvis behavior.

## Current Runtime Structure (Read-Only Inspection Summary)

Entrypoint and lifecycle:

- `main.py:866` defines `main()` and starts `JarvisUI`, then runs `JarvisLive.run()` in a background thread.
- `main.py:483` defines `class JarvisLive`.

Tool routing:

- `main.py:73` defines `TOOL_DECLARATIONS` for Gemini tool calls.
- `main.py:567` defines `JarvisLive._execute_tool()`, which dispatches tool calls and returns a `FunctionResponse`.
- `save_memory` is handled inside `_execute_tool`:
  - `main.py:574` checks `if name == "save_memory":`
  - It writes via `memory.memory_manager.update_memory(...)` (old JSON memory), not the new SQLite engine.

Prompt/context assembly:

- `main.py:531` defines `JarvisLive._build_config()`.
- `_build_config()` currently assembles `system_instruction` as:
  1. `[CURRENT DATE & TIME]` block
  2. old JSON memory summary via `format_memory_for_prompt(load_memory())` (optional)
  3. system prompt loaded from `core/prompt.txt`
  - The final string is `"\n".join(parts)` assigned to `LiveConnectConfig.system_instruction`.

Safe insertion point (future):

- The cleanest read-only insertion point later is inside `_build_config()` by inserting a bounded memory section into `parts` after the old JSON `mem_str` and before `sys_prompt`, or before `sys_prompt` regardless of whether `mem_str` exists.
- Integration must remain read-only first (no writing, no promotions) and must keep the section bounded and short.

## Adapter Contract

The adapter must:

- Read from `data/jarvis_memory.db`.
- Never write to SQLite.
- Never write to `data/raw_events.jsonl`.
- Never create any memory record.
- Never validate/promote/archive memories.
- Never call:
  - `memory_engine.writer.create_memory`
  - `memory_engine.writer.update_memory_status`
  - `memory_engine.writer.archive_memory`
- Only retrieve a small, relevant context.

Failure behavior:

- If DB is missing or unreadable, return an empty context and a short reason field suitable for logs, not for prompt inflation.
- Never create directories or placeholder DB files.

## Proposed Future File (Not Implemented In Phase 6A)

Proposed file:

- `memory_engine/runtime_adapter.py`

Proposed public functions:

```python
def load_runtime_memory_context(
    project: str | None = None,
    query: str | None = None,
    limit: int = 8,
    db_path: str | Path = Path("data") / "jarvis_memory.db",
) -> dict: ...

def format_memory_context_for_prompt(context: dict) -> str: ...

def get_global_rules(limit: int = 8, db_path=...) -> list[dict]: ...

def get_project_context(project: str, limit: int = 8, db_path=...) -> dict: ...
```

Implementation note (read-only SQLite):

- Use `sqlite3.connect("file:<path>?mode=ro", uri=True)` to guarantee read-only access.
- Avoid any `init_db()` call, any table creation, and any PRAGMAs that could change state.
- Prefer `immutable=1` (when supported) as an additional read-only hint:
  - `file:<path>?mode=ro&immutable=1`

## Retrieval Order

The adapter should retrieve in this order, bounded by `limit` per section and by an overall cap:

1. Validated global rules (`type=GLOBAL_RULE`, `scope=global`, `status=validated`)
2. Confirmed or validated project context (`type=PROJECT_CONTEXT`, `scope=project:<name>`, `status in {validated, confirmed}`)
3. Validated warnings (`type=WARNING`, `scope=project:<name>`, `status=validated`)
4. Validated decisions (`type=DECISION`, `scope=project:<name>`, `status=validated`)
5. Confirmed or validated technical state (`type=TECHNICAL_STATE`, `scope=project:<name>`, `status in {validated, confirmed}`)
6. If `query` is provided: keyword matches across active memories, still respecting:
   - status priority
   - importance priority
   - scope separation (global vs project)

Status priority:

- `validated > confirmed > observed > candidate`

Importance priority:

- Higher `importance` first, then more recent `updated_at`.

Exclusions:

- Exclude `archived` and `deprecated`.
- Exclude `conflicted` by default.
- Do not include raw metadata unless explicitly required for safety (avoid prompt bloat).

## Prompt Formatting Rules

Prompt insertion must be bounded and short:

```text
[READ-ONLY MEMORY CONTEXT]
Global Rules:
- ...

Project Context (Meu-Jarvi):
- ...

Warnings:
- ...

Decisions:
- ...
[/READ-ONLY MEMORY CONTEXT]
```

Rules:

- Never dump the full database.
- Keep sections short (default 3–8 items each, with an overall cap).
- Preserve separation: global rules must never be overridden by project context.
- Memory must not override current explicit user instruction if the instruction is safe and clear.
- If memory conflicts with the current user instruction, flag the conflict explicitly in the formatted context instead of silently choosing.
- If DB is missing/unreadable, omit the section entirely or render a 1-line “(no runtime memory available)” without details.

## Safety Boundaries

The adapter must not:

- Import `main.py` or `ui.py`.
- Import `actions/` or `agent/`.
- Call Gemini or any external API.
- Write files outside of the DB read path.
- Write to the DB or JSONL.
- Execute shell commands.

## Future Integration Phases (No Runtime Integration In Phase 6A)

- Phase 6B: Implement `memory_engine/runtime_adapter.py` only, plus tests proving read-only behavior. No `main.py` changes.
- Phase 6C: Add an optional small manual harness or CLI subcommand to print the formatted context for a given project/query. No `main.py` changes.
- Phase 6D: Design where `main.py` could read and insert the bounded context section in `_build_config()`. Still no automatic writing.
- Phase 7: Only then consider an optional read-only runtime connection behind a feature flag or explicit toggle.

Automatic writing remains out of scope for these phases.

## Test Plan (For Phase 6B+)

Future tests must prove:

- Adapter does not write to DB (open in read-only mode, detect unchanged size/mtime).
- Adapter does not write to JSONL.
- Adapter does not import `main` or `ui`.
- Adapter does not call `create_memory`, `update_memory_status`, `archive_memory`.
- Adapter excludes archived/deprecated, and excludes conflicted by default.
- Adapter keeps `GLOBAL_RULE` separate from `PROJECT_CONTEXT`.
- Adapter output is bounded and does not dump everything.
- Adapter handles missing DB safely.

## Risks

- SQLite “read-only” must be enforced by connection mode (URI `mode=ro`) to avoid accidental side-effects (journals/WAL).
- Prompt bloat if limits are not enforced strictly.
- Potential conflict between old JSON memory summary and new runtime adapter context; ordering and separation must be explicit.
- Risk of over-trusting unvalidated memories; status filtering must be conservative.

## Recommendation

Proceed to Phase 6B implementing `memory_engine/runtime_adapter.py` with strict read-only SQLite access (`mode=ro`) and comprehensive “no mutation” tests, but still no runtime integration in `main.py`.

