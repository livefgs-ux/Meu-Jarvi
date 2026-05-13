# Security Model (Local)

This document describes the local security posture and operational constraints for Meu Jarvis.

## Core Principles
- Local-first: run on a personal machine, not a server.
- Human-in-the-loop: prefer explicit confirmation and bounded actions.
- Least privilege: do not assume admin rights or unrestricted filesystem access.
- Auditability: prefer deterministic logic, logs, and tests over hidden behavior.

## Secrets Handling
- Do not commit secrets to Git.
- `config/api_keys.json` is a local-only secret file and should remain gitignored.
- Avoid copying or printing API keys in logs, tests, docs, or prompts.

## Memory Security
Two memory systems exist:

1. Legacy JSON memory (runtime `save_memory`)
- Stored under `memory/`.
- Still active; not migrated.

2. Memory Engine (SQLite + JSONL)
- `data/jarvis_memory.db` and `data/raw_events.jsonl` are runtime local files and are gitignored.
- Writes should remain explicit (manual CLI) unless a future phase approves controlled runtime writes.

## Privacy Guard
The Memory Engine includes a privacy guard that blocks common secret patterns:
- API keys
- tokens
- passwords
- private keys
- .env-like credential content

## Read-Only Runtime Boundary
Runtime integration is read-only first:
- OFF by default.
- Must not write to SQLite.
- Must not append to JSONL event logs.
- Must not validate/promote/archive memories at runtime.

## Network / External Services
- The assistant runtime may use network actions (e.g., web search) via explicit tools.
- Documentation and development phases should avoid relying on remote sources as "truth" for local audits.

## Known Risks
- Prompt bloat when adding memory context.
- Overlap/confusion between legacy JSON memory and SQLite memory context.
- Misconfiguration of env toggles leading to missing context (fail-closed behavior).

