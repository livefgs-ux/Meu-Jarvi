# Runtime Read-Only Integration Test Contract (Pre-`main.py`)

## 1. Purpose
This document defines the **non-negotiable contract** and the **required tests** that must be satisfied **before** any read-only memory context is connected to the Jarvis runtime (`main.py`).

No runtime integration should be implemented until this contract is met and reviewed.

## 2. Non-goals
This contract explicitly does **not** allow:
- Automatic memory writes (no background learning, no implicit saving).
- “Save-everything” mechanisms.
- Any mutation of memory state (no validate/promote/archive/deprecate at runtime).
- Any changes to Gemini/API calling behavior.
- UI refactors or behavior changes.
- Tool routing changes or tool declaration changes.
- Obsidian integration.
- Graphify integration.
- Embeddings or vector indexes.

## 3. Future Integration Rule (Required Behavior)
Any future runtime read-only connection must satisfy all of the following:

1. **OFF by default**
   - Must be disabled unless explicitly enabled by a toggle.

2. **Read-only**
   - Must open SQLite in read-only mode (URI `mode=ro`).
   - Must never create the DB file.

3. **Bounded**
   - Must bound prompt insertion by `max_chars`.
   - Must not dump the database.

4. **Safe if DB missing**
   - Missing/invalid DB must not crash startup/config build.
   - Must fail closed: omit the block (or show a short safe note) without raw errors.

5. **No writes of any kind**
   - Must not write to SQLite.
   - Must not append to `data/raw_events.jsonl`.
   - Must not call any writer functions:
     - `create_memory`
     - `update_memory_status`
     - `archive_memory`
   - Must not validate/promote/archive memories.

6. **No routing/config behavior change**
   - Must not change existing tool declarations or routing behavior.
   - Must not change Gemini model selection/config.

## 4. Proposed Future Toggle (Design Only)
Define (but do not implement yet) a future environment toggle:

- `JARVIS_READONLY_MEMORY`
  - Values: `0` or `1`
  - Default: `0` (OFF)

Optional future variables (design-only; no implementation yet):
- `JARVIS_MEMORY_PROJECT` (example: `Meu-Jarvi`)
- `JARVIS_MEMORY_MAX_CHARS` (default suggestion: `2500`)
- `JARVIS_MEMORY_DB` (default suggestion: `data/jarvis_memory.db`)

## 5. Required Tests Before Any `main.py` Modification
The following tests must exist **before or during** the future implementation work that touches runtime.

### A. Toggle Behavior
1. Disabled by default: no read-only memory block is inserted.
2. When disabled, runtime behavior is identical to current behavior (no new memory context).
3. When enabled, the read-only memory block is inserted exactly once.

### B. Read-only Behavior (No Mutation Proof)
Tests must prove that when runtime integration runs:
1. `data/jarvis_memory.db` signature unchanged (size + mtime).
2. `data/raw_events.jsonl` signature unchanged (size + mtime).
3. No writer functions are called:
   - Patch/spy assertions for `memory_engine.writer.create_memory`, `update_memory_status`, `archive_memory` must show zero calls.
4. No memory rows created and no events appended (enforced via signatures and writer-call checks).

Preferred approach:
- If real runtime seed files exist, record (size, mtime) before and after and assert unchanged.
- Also run a version of tests inside an isolated temp CWD where `data/` does not exist to prove “does not create DB”.

### C. Prompt Injection Boundary (Correctness + Boundedness)
Tests must prove:
1. The inserted context appears **only** inside:
   - `[READ-ONLY MEMORY CONTEXT]`
   - `[/READ-ONLY MEMORY CONTEXT]`
2. The inserted context is bounded by `max_chars`.
3. Adapter exclusions are preserved:
   - `archived`, `deprecated`, `conflicted` are excluded.
4. Separation remains intact:
   - global rules do not mix with project context
   - project context does not override global rules (at minimum: the prompt sectioning preserves separation)

### D. Runtime Safety / No Behavior Drift
Tests must prove:
1. Missing DB does not crash Jarvis config build (read-only block omitted safely).
2. SQLite open errors do not leak raw internal error strings to the user/model prompt.
3. No Gemini model/config changes as part of integration.
4. No tool declaration changes as part of integration.
5. No UI changes as part of integration.

### E. Import Boundaries (Runtime Remains Minimal)
Tests (static or runtime import checks) must prove:
1. Runtime integration does **not** import:
   - `tools/memory_cli.py`
   - `tools/memory_context_preview.py`
2. Runtime integration may import only:
   - `memory_engine.runtime_adapter` (preferred), or
   - a minimal wrapper module that itself only imports `runtime_adapter`.

## 6. Future Implementation Shape (Safest Sequence)
This contract recommends the following sequence:

### Phase 7B (No `main.py` changes)
1. Add a minimal wrapper/helper module (if needed) to keep `main.py` import changes small.
2. Add tests for:
   - toggles
   - bounded prompt block
   - “no mutation” proofs
3. Ensure tests pass with and without existing runtime seed files.

### Phase 7C (Minimal `main.py` change, toggle-gated)
1. Modify `main.py` minimally in exactly one integration point (as designed in Phase 6D).
2. Guard behind `JARVIS_READONLY_MEMORY=1` (default OFF).
3. Prove by tests:
   - no behavior change when disabled
   - insertion when enabled
   - no mutation of DB/log

### Phase 7D (Manual runtime smoke test, still no automatic writes)
1. Manual run with toggle enabled.
2. Confirm prompt includes bounded memory block.
3. Confirm DB/log signatures unchanged.

## 7. Approval Checklist (Before Phase 7C)
Before approving any `main.py` change:
1. `git status` is clean.
2. All tests pass.
3. DB/log signatures recorded before and after tests.
4. Exact diff reviewed; `main.py` diff minimal and toggle-gated.
5. No runtime write path introduced (no writer imports/calls; no JSONL writes).

## 8. Risk List (Known)
- Prompt bloat (context too large).
- Conflict between legacy JSON memory (`memory/long_term.json`) and SQLite memory.
- Accidental automatic writes creeping into runtime.
- Project context overriding global rules (or being treated as such).
- Memory context overriding current explicit safe user instruction.
- Hidden changes to Gemini config or tool declarations.
- Missing DB causing startup/config failure.

## 9. Final Recommendation
Do **not** proceed to modify `main.py` immediately.

Proceed next with Phase 7B (tests + optional wrapper only). Only after the contract tests exist and pass should Phase 7C be considered.

