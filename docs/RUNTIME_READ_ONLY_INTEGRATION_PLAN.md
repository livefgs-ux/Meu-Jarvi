# Runtime Read-Only Memory Integration Plan (Design-Only)

## Purpose
Define where and how the existing Jarvis runtime (current `main.py` flow) could later receive **bounded, read-only** memory context from `memory_engine/runtime_adapter.py` without changing tool routing behavior or enabling any writes.

This document is design-only. No runtime code changes are performed in Phase 6D.

## Non-goals
- No modification of `main.py`, `ui.py`, `actions/`, `agent/`, `memory/`, `config/`, `core/prompt.txt`.
- No runtime integration implementation yet.
- No automatic memory writes of any kind (no “save everything”, no background learning).
- No DB creation, no writes to `data/jarvis_memory.db`, no writes to `data/raw_events.jsonl`.
- No Gemini / external APIs / internet / Graphify / Obsidian integrations.

## Current Runtime Observations (Read-Only)
From read-only inspection of `main.py`:

1. **JarvisLive initialization**
   - `main()` creates `JarvisUI`, then `JarvisLive(ui)`.

2. **System instruction / prompt assembly**
   - `JarvisLive._build_config()` builds `types.LiveConnectConfig(system_instruction=...)`.
   - It currently concatenates (in this order):
     1. `[CURRENT DATE & TIME] ...`
     2. Existing legacy memory string from `memory/memory_manager.py` (via `load_memory()` + `format_memory_for_prompt()`), if present
     3. The system prompt loaded from `core/prompt.txt` (via `_load_system_prompt()`).

3. **Existing memory write behavior**
   - A tool declaration exists: `save_memory`.
   - Tool execution path in `_execute_tool()` calls `memory.memory_manager.update_memory(...)`, which writes to `memory/long_term.json`.
   - This is separate from the new SQLite Memory Engine (`data/jarvis_memory.db`).

These observations suggest the safest future place to add a read-only context block is in `_build_config()` at the point where `system_instruction` is assembled, because that is upstream of all user turns and does not touch tool routing.

## Proposed Integration Target (Future)
Future runtime integration should:

1. Call:
   - `memory_engine.runtime_adapter.load_runtime_memory_context(...)`
   - `memory_engine.runtime_adapter.format_memory_context_for_prompt(...)`

2. Insert the formatted text as a bounded block using **this exact boundary**:
```
[READ-ONLY MEMORY CONTEXT]
...
[/READ-ONLY MEMORY CONTEXT]
```

3. Maintain strict safety properties:
   - Read-only SQLite open (`mode=ro`) only.
   - Never call writer functions (`create_memory`, `update_memory_status`, `archive_memory`).
   - Never write to `data/raw_events.jsonl`.
   - Never change tool routing behavior.
   - Be disabled by default (Mode A) unless explicitly enabled (Mode B).

## Proposed Integration Point (Future)
**Target:** `JarvisLive._build_config()` where `parts` are assembled for `system_instruction`.

### Insertion placement
Insert the read-only memory block:

- **After** the global system prompt (the contents of `core/prompt.txt`) so global system rules stay authoritative.
- **Before** any task-specific user request (already true because `system_instruction` is set before user turns).

Rationale:
- “Global system rules outrank memory” is easiest to preserve when system rules come first.
- The memory context becomes an *additional reference section* rather than a replacement for system rules.

Note: today the legacy `mem_str` is appended before the system prompt. This plan does not change that behavior in Phase 6D; it only defines where the new block should go when implementation is approved later.

## Integration Modes (Future)
Only Modes A and B are candidates for the first implementation.

### Mode A — OFF (default)
- Do not load any SQLite memory context.
- Do not insert any read-only block.

### Mode B — MANUAL PROJECT READ (first implementation candidate)
- A fixed project name is provided explicitly (example: `Meu-Jarvi`).
- Runtime loads:
  - validated/confirmed global rules
  - validated/confirmed project context (for that project)
  - plus other bounded sections per adapter rules

How to provide the project name (design options):
- Environment variable (lowest impact): `JARVIS_PROJECT=Meu-Jarvi`
- A dedicated CLI flag (would require runtime changes; still feasible later)

### Mode C — DETECTED PROJECT READ (future)
- A future detector chooses project from user turns.
- Not in scope for first runtime read-only integration.

## Prompt Insertion Rules
When inserting the block:

1. Always use the exact boundary markers:
   - `[READ-ONLY MEMORY CONTEXT]`
   - `[/READ-ONLY MEMORY CONTEXT]`

2. Keep bounded:
   - Default `max_chars` should be conservative (2000–3000).
   - Do not dump the DB.

3. Separation rules:
   - Global Rules must not be mixed into Project Context.
   - Project Context must not override Global Rules.

4. Conflict handling:
   - If a memory entry conflicts with a current explicit safe user instruction, it should be treated as *reference only* and the conflict should be visible (e.g., “potential conflict”) rather than silently decided.

5. Exclusions:
   - Never include archived/deprecated/conflicted by default.

## Safety Boundaries / Risk Controls
The future integration must preserve:

- **Read-only only**: open SQLite with URI `mode=ro`.
- **Toggle gated**: disabled by default; explicit opt-in required.
- **Max chars**: hard limit for prompt insertion.
- **No automatic writes**: no creation/promotion/archival of memories.
- **No DB creation**: missing DB must not create any file.
- **Graceful failure**: if DB missing/unavailable, omit the block (or include a short safe note) without raising raw sqlite errors to the user.
- **No secrets printed**: rely on upstream privacy guard at write time, and keep formatting concise.
- **No tool routing change**: no modifications to `TOOL_DECLARATIONS` or tool selection logic.

## Failure Behavior (Future)
If memory DB is missing or can’t be opened read-only:

- The runtime should proceed normally without memory context.
- Do not surface raw exceptions to the user.
- Optional: log a short diagnostic to console/UI log (not to the model prompt), but keep it non-sensitive.

## Query / Keyword Matches Note
Current adapter + preview tool support `query` and can display a “Keyword Matches” section.

Design recommendation for first runtime integration:
- **Acceptable as-is for manual preview/harness usage.**
- For the first runtime read-only integration (Mode B), prefer **query=None** by default (stable, predictable context).
- Consider query-based retrieval only later, behind an explicit flag or when the user explicitly asks to “search memory”.

If we want to refine this before runtime integration, that should be a small follow-up phase (e.g., Phase 6C.1) with tests demonstrating boundedness and non-leak behavior.

## Future Test Plan (For Later Approved Implementation)
When integration implementation is approved (Phase 7A+), tests should prove:

1. Runtime integration is gated OFF by default.
2. When enabled, insertion:
   - adds exactly one bounded `[READ-ONLY MEMORY CONTEXT] ...` block
   - respects `max_chars`
3. No writes:
   - no calls to writer functions
   - no modifications to `data/jarvis_memory.db` or `data/raw_events.jsonl`
4. Missing DB handling:
   - does not crash runtime
   - does not create DB files
5. No routing changes:
   - tool declarations and routing remain unchanged

## Risks
- **Prompt ordering risk**: inserting memory before system rules could accidentally elevate memory priority. This plan explicitly places memory after system rules for safety.
- **Dual-memory confusion**: legacy `memory/long_term.json` memory is already inserted; adding SQLite memory may create redundant or conflicting context. Mitigation: strict sectioning + boundedness + conflict visibility.
- **Over-context**: too many memories could bloat prompts. Mitigation: `max_chars` + per-section limits.

## Recommendation
Proceed to a future Phase 7A only after:
1. Explicit opt-in toggle is designed/approved (default OFF).
2. Tests for integration gating and “no writes” are defined and ready.
3. A clear plan exists for how legacy `long_term.json` memory and SQLite memory should coexist in prompt order (without refactoring legacy behavior yet).

