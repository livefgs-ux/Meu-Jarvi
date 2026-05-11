# main.py Read-Only Memory Patch Plan (Design Only)

This is a design / patch-plan document only. It does not modify runtime code.

## Purpose
Define the exact minimal future diff to allow `main.py` to consume the **read-only** memory wrapper (`memory_engine/runtime_context.py`) and inject a bounded memory block into the runtime prompt, **OFF by default**.

## Constraints (Must Hold)
The future implementation must:
- Not modify tool declarations (`TOOL_DECLARATIONS`) or routing behavior.
- Not change Gemini model/config.
- Not change UI behavior.
- Not change `save_memory` behavior (legacy JSON `memory/long_term.json`).
- Not write to SQLite (`data/jarvis_memory.db`).
- Not write to JSONL (`data/raw_events.jsonl`).
- Not call any writer functions (`create_memory/update_memory_status/archive_memory`).
- Not create DB files.
- Fail closed (if anything goes wrong, insert nothing).

## Authority / Order (Non-Negotiable)
The read-only memory block is **auxiliary context only**.

Rules:
- `core/prompt.txt` remains the **primary** runtime system instruction source.
- Read-only memory context must **not** override `core/prompt.txt`.
- Read-only memory context must **not** override safe, explicit user instructions.
- Project context must **not** override global rules.
- If memory conflicts with `core/prompt.txt` or a current instruction, treat it as **context / conflict signal**, not as an instruction to silently obey.

## Current `main.py` Observations (Read-Only)
Key locations in `F:\Meu Jarvi\main.py`:

1. Prompt/system instruction assembly
   - `JarvisLive._build_config()` constructs `types.LiveConnectConfig(system_instruction=...)`.
   - It currently computes:
     - `memory = load_memory()` and `mem_str = format_memory_for_prompt(memory)` (legacy JSON memory).
     - `sys_prompt = _load_system_prompt()` reading `core/prompt.txt` (`PROMPT_PATH`).
     - `parts = [time_ctx]`
     - `if mem_str: parts.append(mem_str)`
     - `parts.append(sys_prompt)`
     - `system_instruction = "\n".join(parts)`

2. `save_memory` tool exists and writes legacy JSON memory
   - `TOOL_DECLARATIONS` includes `"name": "save_memory"` around the end of tool declarations.
   - `_execute_tool()` checks `if name == "save_memory": ... update_memory(...)`.

3. Runtime start
   - `main()` creates `JarvisUI`, waits for API key, instantiates `JarvisLive(ui)`, and runs.

## Proposed Minimal Future `main.py` Patch (Description Only)
### 1) Add a single import (safe, thin wrapper only)
Add near the top-level imports (exact position not important as long as it is top-level and does not change runtime behavior when disabled):

```python
from memory_engine.runtime_context import build_readonly_memory_context_from_env
```

Notes:
- Importing the wrapper is acceptable because it imports only stdlib + `memory_engine.runtime_adapter`.
- It must not import any tools or writer modules.

### 2) Call wrapper only inside `_build_config()` (prompt build path only)
Inside `JarvisLive._build_config()`, after `sys_prompt = _load_system_prompt()` is available and before `system_instruction` is finalized, add:

```python
ro_mem = build_readonly_memory_context_from_env()
```

Then insert it into `parts` only if non-empty:

```python
if ro_mem:
    parts.append(ro_mem)
```

### 3) OFF-by-default toggle behavior
Because the wrapper reads `JARVIS_READONLY_MEMORY` (default OFF), the call is a no-op by default:
- If toggle disabled: `ro_mem == ""` and nothing is appended.
- If enabled but project missing: `ro_mem == ""`.
- If DB missing or cannot open read-only: `ro_mem == ""`.
- No raw exceptions should reach runtime (wrapper fail-closed).

## Exact Insertion Point
Insert the read-only memory block as a **bounded auxiliary context section** during `JarvisLive._build_config()` (prompt/system-instruction build path), before returning `types.LiveConnectConfig(...)`.

Required boundary markers must remain unchanged (produced by adapter formatting):
```
[READ-ONLY MEMORY CONTEXT]
...
[/READ-ONLY MEMORY CONTEXT]
```

### Ordering clarification (authority-preserving)
The final implementation must preserve `core/prompt.txt` authority. There are two safe ordering options:

1. **Insert before `sys_prompt`**:
   - Keep `core/prompt.txt` last in the assembled `system_instruction`, reinforcing authority by position.

2. **Insert after `sys_prompt`**:
   - Allowed only if the inserted block is clearly treated as **context only**, and tests verify it does not override system rules or safe user instructions.

This document does not force one ordering; the implementation phase must choose the safest ordering and prove it with tests.

Note: Today legacy `mem_str` is appended before `sys_prompt`. This plan does not remove or refactor that existing behavior.

## Env Toggle Contract (Future Runtime)
Variables:
- `JARVIS_READONLY_MEMORY=0|1` (default `0`)

Optional:
- `JARVIS_MEMORY_PROJECT=Meu-Jarvi`
- `JARVIS_MEMORY_MAX_CHARS=2500`
- `JARVIS_MEMORY_LIMIT=8`
- `JARVIS_MEMORY_DB=data/jarvis_memory.db`

Rules:
- If disabled, runtime behavior identical to current.
- If enabled but missing project, insert nothing.
- If enabled but DB missing/unavailable, insert nothing.
- No raw errors shown to user/model prompt.

## Required Tests for the Implementation Phase (Future Phase 7D)
These tests must be added before/with the future minimal `main.py` patch.

### A) Toggle Disabled (No Behavior Change)
1. `_build_config()` produces `system_instruction` without any `[READ-ONLY MEMORY CONTEXT]` block.
2. `TOOL_DECLARATIONS` unchanged (names/count stable).
3. No DB/log access, or at minimum no DB/log mutation signatures.

### B) Toggle Enabled (Correct Injection)
1. With env enabled + project + existing DB: context appears exactly once, inside boundaries.
2. `max_chars` respected.
3. Missing DB does not crash.
4. Enabled but missing project inserts nothing.

### C) No-Write Guarantees
1. `data/jarvis_memory.db` size/mtime unchanged.
2. `data/raw_events.jsonl` size/mtime unchanged.
3. No calls to `create_memory/update_memory_status/archive_memory` (patch/spy).

### D) Import Boundaries / No Drift
1. `main.py` imports only `memory_engine.runtime_context` (wrapper), not `tools/memory_cli.py` or `tools/memory_context_preview.py`.
2. No Graphify/Obsidian integration.
3. No Gemini config drift.

## Rollback Plan
If any issue appears:
1. Set `JARVIS_READONLY_MEMORY=0` (immediate rollback to baseline behavior).
2. If needed, remove:
   - the single import
   - the single call/insertion block

No data migration needed; no DB rollback needed (read-only).

## Risks
- Prompt bloat if `max_chars` too high or `limit` too high.
- Confusion/conflict between legacy JSON memory (`memory/long_term.json`) and SQLite memory; ordering must be intentional.
- Hidden Gemini/tool config drift (must be prevented by tests).
- Startup errors if import fails; wrapper must remain dependency-light.
- Wrapper fail-closed can hide diagnostics; consider future safe logging (not in prompt).
- Risk of “write creep” in future phases; must keep contract tests.

## Recommendation
Recommended sequence (consistent naming):

Phase 7D:
1. Add tests/harness to exercise `_build_config()` behavior under env toggles (without running the full app), proving OFF-by-default and no-write guarantees.
2. Ensure all tests pass with existing runtime seed files present.

Phase 7E:
1. Implement the minimal `main.py` diff (toggle-gated, OFF by default): one import + one call + conditional append.
2. Re-run the Phase 7D test suite to prove:
   - no behavior change when disabled
   - bounded insertion when enabled
   - no DB/log mutation

