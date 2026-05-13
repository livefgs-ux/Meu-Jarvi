# Roadmap (Meu Jarvis)

This roadmap reflects the current local repository state and the safety-first approach.

## Now (Stabilization)
- Keep read-only memory injection OFF by default.
- Keep tests green and maintain baseline AST checks for `main.py`.
- Document legacy vs SQLite memory boundaries clearly.

## Next (Controlled Runtime Read-Only Usage)
- Add safe, non-secret debug visibility for whether read-only memory was loaded (no DB dumps).
- Evaluate prompt size limits (`JARVIS_MEMORY_MAX_CHARS`) with real usage.

## Later (Explicit Memory Write Design - Not Automatic)
- Design a controlled, explicit runtime write interface (no save-everything).
- Add additional policy controls and approval steps.
- Consider migration strategy for legacy JSON memory only after agreement and tests.

## Out of Scope (For Now)
- Embeddings/vector search.
- Obsidian integration.
- Graphify as the main memory store.
- Autonomous background learning.

