"""Manual preview harness for read-only runtime memory context.

This tool is a local-only, read-only preview. It is not connected to the Jarvis
runtime and must never write to the SQLite DB or JSONL logs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support direct script invocation from repo root: `python tools/memory_context_preview.py ...`
if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from memory_engine.runtime_adapter import (  # noqa: E402
    DEFAULT_DB_PATH,
    format_memory_context_for_prompt,
    load_runtime_memory_context,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview read-only memory context (runtime adapter)")
    parser.add_argument("--project", help="Project name (e.g. Meu-Jarvi)")
    parser.add_argument("--query", help="Optional keyword query")
    parser.add_argument("--limit", type=int, default=8, help="Max items per section (default: 8)")
    parser.add_argument("--max-chars", type=int, default=3000, help="Max formatted chars (default: 3000)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path (default: data/jarvis_memory.db)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    ctx = load_runtime_memory_context(
        project=args.project,
        query=args.query,
        limit=args.limit,
        db_path=args.db,
    )

    if not ctx.get("available"):
        err = ctx.get("error") or "memory db unavailable"
        print(f"Memory context unavailable: {err}", file=sys.stderr)
        return 2

    text = format_memory_context_for_prompt(ctx, max_chars=args.max_chars)
    if not text.strip():
        print("(no read-only memory context available)")
        return 0

    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

