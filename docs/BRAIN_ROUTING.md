# Brain Routing

## Master Agent Modes

The Master Agent chooses an operating mode from the request context, risk, and required output.

- `Architect`: design, structure, and system planning.
- `Debugger`: failures, traces, errors, broken behavior.
- `Security Reviewer`: secrets, credentials, unsafe operations, privacy risks.
- `Sysadmin`: environment, OS, shell, setup, installations.
- `Code Reviewer`: review for bugs, regressions, missing tests, and risks.
- `Memory Engineer`: memory schema, storage, retrieval, policy, consolidation.
- `Executor`: bounded implementation or operational work.
- `Teacher`: explanation, learning, examples.
- `Creative Director`: creative work, style, media, product direction.

## Retrieval Order

Relevant memory should be retrieved in this order:

1. Global rules.
2. Active project context.
3. Task or session context.
4. Procedures.
5. Decisions.
6. Warnings.

## Routing Principle

The system should classify intent, target object, scope, and risk before selecting a tool or action. It should not choose a tool only because a parameter name or action word appears similar.

## Phase 3 Deterministic Foundation

The v0 Brain Foundation uses deterministic keyword and rule-based routing only. It does not call an LLM, shell, UI, network, Gemini, Graphify, or Obsidian.

The context detector returns:

- raw input
- probable project
- task type
- risk level
- memory need
- execution need
- detected keywords
- recommended mode

Routing remains advisory. The standalone brain does not execute commands.
