# Memory Schema

## Memory Types

- `GLOBAL_RULE`: permanent behavior or methodology rule.
- `PREFERENCE`: user preference that may affect future responses or decisions.
- `CORRECTION`: mistake and corrected behavior.
- `PROJECT_CONTEXT`: project-scoped fact, constraint, or context.
- `TECHNICAL_STATE`: current technical state, usually project/session scoped.
- `DECISION`: decision with durable value.
- `PROCEDURE`: validated repeatable process.
- `WARNING`: caution, risk, or unsafe pattern.
- `IDEA`: future possibility or non-committed thought.
- `TASK`: task or follow-up item.
- `SESSION_SUMMARY`: summary of a session.

## Scopes

- `global`: cross-project behavior and stable preferences.
- `project:<name>`: context scoped to one project.
- `session`: current or recent session context.
- `temporary`: short-lived context that should not be treated as durable.

Project-scoped context output should keep memory types distinct:

- `PROJECT_CONTEXT` is project fact, constraint, or context.
- `TECHNICAL_STATE` is current implementation or environment state.
- `WARNING` is a risk or caution.

These are related by project scope, but they are not interchangeable.

## Statuses

- `observed`: noticed but not fully validated.
- `candidate`: possible memory awaiting confirmation.
- `confirmed`: accepted as useful.
- `validated`: verified and durable.
- `conflicted`: conflicts with existing memory.
- `deprecated`: superseded but retained for audit.
- `archived`: inactive.

## Lifecycle Transitions

The intended manual lifecycle is:

- `observed -> candidate -> confirmed -> validated`
- `observed/confirmed/validated -> deprecated` when superseded or no longer recommended.
- Any non-active memory can become `archived` when it should be hidden from normal retrieval.
- `conflicted` is used when a contradiction or likely overlap is detected and needs review.

Runtime integration must not automatically treat new memories as validated. High-priority behavioral memories should be manually or policy validated before they are trusted.

## Importance

Importance is an integer from 1 to 10.

- 1-3: low utility.
- 4-6: useful context.
- 7-8: important behavior, decision, or project context.
- 9-10: critical safety, policy, or validated procedure.

## Confidence

Confidence is a float from 0.0 to 1.0.

- 0.0-0.39: weak or uncertain.
- 0.4-0.69: plausible but needs validation.
- 0.7-0.89: reliable.
- 0.9-1.0: validated or directly confirmed.
