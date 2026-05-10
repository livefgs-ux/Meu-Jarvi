# Master Contract

## Jarvis Brain Core

The Jarvis Brain Core is a local, auditable foundation for reasoning over rules, project context, task context, memories, decisions, corrections, and warnings. It is not a replacement for the current Jarvis runtime and is not connected to Gemini, Obsidian, Graphify, or the UI in this version.

The first contract of the Brain Core is separation. The system must classify information before it stores or retrieves it.

## Context Classes

### GLOBAL_RULE

Global rules are permanent behavior or methodology rules. They affect how Jarvis should reason across projects and sessions.

Examples:

- Diagnose before changing.
- Do not store secrets.
- Do not mix global rules with project-specific context.

Global rules must not contain project-specific technical state, credentials, local machine secrets, temporary task notes, or assumptions presented as facts.

### PROJECT_CONTEXT

Project context is scoped to a specific project. It can include architecture decisions, known constraints, technical state, repository facts, and validated procedures for that project.

Project context must remain inside `project:<name>` scope. The system must never promote project details to global rules automatically.

### TASK_CONTEXT

Task context is temporary. It applies to the active task or session and should not become durable unless it changes future behavior, decisions, safety, project context, or a validated procedure.

## Promotion Rules

The system must never automatically promote project context into global rules. Promotion requires explicit user intent and validation that the content is behavior or methodology related, not a project technical detail.

The Brain Foundation must use the Memory Engine's validation policy for memory scope rules. It must not duplicate or bypass the policy that prevents project-specific technical state from becoming global memory.

## Storage Contract

Every memory must have:

- type
- scope
- status
- confidence
- importance
- source
- created timestamp
- updated timestamp

The system must not store secrets, API keys, passwords, tokens, private keys, credentials, or `.env`-like content.

## Runtime Boundary

The Phase 3 Brain Foundation is standalone. It may initialize and use the Memory Engine when given explicit paths, but it must not connect to the current Jarvis runtime, UI, Gemini session, Obsidian, Graphify, or autonomous background learning.

## Manual Write Boundary

Memory writes must remain explicit until runtime integration is separately approved. Automatic learning, save-everything behavior, and background memory capture are not part of the current phase.

Runtime integration must not automatically validate memories. Manual or policy-driven validation is required before high-priority behavioral memories are trusted.
