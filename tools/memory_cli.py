"""Manual CLI for the local Memory Engine.

This is a local-only testing surface. It is not connected to the running
Jarvis app and does not perform automatic learning.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from memory_engine.database import DEFAULT_DB_PATH, init_db, open_db
from memory_engine.event_log import DEFAULT_EVENT_LOG_PATH
from memory_engine.retriever import get_memory_by_id, search_memories
from memory_engine.schemas import MEMORY_STATUSES
from memory_engine.writer import archive_memory, create_memory, update_memory_status


def _path(value: str | Path) -> Path:
    return Path(value)


def _print_records(records) -> None:
    if not records:
        print("(none)")
        return
    print("ID | Type | Scope | Status | Importance | Confidence | Content")
    print("---|------|-------|--------|------------|------------|--------")
    for record in records:
        content = record.content.replace("\n", " ")
        if len(content) > 96:
            content = content[:93].rstrip() + "..."
        print(
            f"{record.memory_id} | {record.memory_type} | {record.scope} | "
            f"{record.status} | {record.importance} | {record.confidence:.2f} | {content}"
        )


def _print_section(title: str, records) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    _print_records(records)


def _event_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def cmd_init(args) -> int:
    path = init_db(args.db)
    print(f"Initialized memory database: {path}")
    print(f"Event log path: {args.events}")
    return 0


def cmd_show(args) -> int:
    record = get_memory_by_id(args.memory_id, db_path=args.db)
    if record is None:
        print(f"Error: memory not found: {args.memory_id}", file=sys.stderr)
        return 2

    print(f"id: {record.memory_id}")
    print(f"type: {record.memory_type}")
    print(f"scope: {record.scope}")
    print(f"project: {record.project or ''}")
    print(f"status: {record.status}")
    print(f"importance: {record.importance}")
    print(f"confidence: {record.confidence:.2f}")
    print(f"content: {record.content}")
    print(f"source: {record.source}")
    print(f"created_at: {record.created_at}")
    print(f"updated_at: {record.updated_at}")
    return 0


def cmd_set_status(args) -> int:
    try:
        record = update_memory_status(
            args.memory_id,
            args.status,
            db_path=args.db,
            event_log_path=args.events,
            source="manual_cli",
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Updated memory ID {record.memory_id} status: {record.status}")
    return 0


def cmd_archive(args) -> int:
    try:
        record = archive_memory(
            args.memory_id,
            db_path=args.db,
            event_log_path=args.events,
            source="manual_cli",
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Archived memory ID: {record.memory_id}")
    return 0


def cmd_audit(args) -> int:
    db_path = _path(args.db)
    events_path = _path(args.events)
    total = 0
    high_importance = 0
    by_type = []
    by_scope = []
    by_status = []
    if db_path.exists():
        with open_db(db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "memories" in tables:
                total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
                high_importance = int(
                    conn.execute("SELECT COUNT(*) FROM memories WHERE importance >= 8").fetchone()[0]
                )
                by_type = conn.execute(
                    "SELECT memory_type AS key, COUNT(*) AS count FROM memories GROUP BY memory_type ORDER BY key"
                ).fetchall()
                by_scope = conn.execute(
                    "SELECT scope AS key, COUNT(*) AS count FROM memories GROUP BY scope ORDER BY key"
                ).fetchall()
                by_status = conn.execute(
                    "SELECT status AS key, COUNT(*) AS count FROM memories GROUP BY status ORDER BY key"
                ).fetchall()

    print(f"DB path: {db_path}")
    print(f"Event path: {events_path}")
    print(f"Total memories: {total}")
    print("Count by type:")
    for row in by_type:
        print(f"  {row['key']}: {row['count']}")
    print("Count by scope:")
    for row in by_scope:
        print(f"  {row['key']}: {row['count']}")
    print("Count by status:")
    for row in by_status:
        print(f"  {row['key']}: {row['count']}")
    print(f"Highest importance memories count: {high_importance}")
    print(f"Event log exists: {'yes' if events_path.exists() else 'no'}")
    print(f"Event count: {_event_line_count(events_path)}")
    return 0


def cmd_add(args) -> int:
    try:
        record = create_memory(
            args.memory_type,
            args.scope,
            args.content,
            project=args.project,
            source=args.source,
            importance=args.importance,
            confidence=args.confidence,
            status=args.status,
            db_path=args.db,
            event_log_path=args.events,
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Created memory ID: {record.memory_id}")
    return 0


def cmd_list(args) -> int:
    records = search_memories(
        memory_type=args.memory_type,
        scope=args.scope,
        project=args.project,
        status=args.status,
        limit=args.limit,
        db_path=args.db,
    )
    _print_records(records)
    return 0


def cmd_search(args) -> int:
    records = search_memories(
        query=args.query,
        memory_type=args.memory_type,
        scope=args.scope,
        project=args.project,
        limit=args.limit,
        db_path=args.db,
    )
    _print_records(records)
    return 0


def cmd_context(args) -> int:
    global_rules = search_memories(
        memory_type="GLOBAL_RULE",
        scope="global",
        db_path=args.db,
        limit=100,
    )
    _print_section("Global Rules", global_rules)
    if args.project:
        project_scope = f"project:{args.project}"
        _print_section(
            "Project Context",
            search_memories(
                memory_type="PROJECT_CONTEXT",
                scope=project_scope,
                project=args.project,
                db_path=args.db,
                limit=100,
            ),
        )
        _print_section(
            "Technical State",
            search_memories(
                memory_type="TECHNICAL_STATE",
                scope=project_scope,
                project=args.project,
                db_path=args.db,
                limit=100,
            ),
        )
        _print_section(
            "Warnings",
            search_memories(
                memory_type="WARNING",
                scope=project_scope,
                project=args.project,
                db_path=args.db,
                limit=100,
            ),
        )
        _print_section(
            "Decisions",
            search_memories(
                memory_type="DECISION",
                scope=project_scope,
                project=args.project,
                db_path=args.db,
                limit=100,
            ),
        )
        _print_section(
            "Procedures",
            search_memories(
                memory_type="PROCEDURE",
                scope=project_scope,
                project=args.project,
                db_path=args.db,
                limit=100,
            ),
        )
    return 0


def cmd_status(args) -> int:
    db_path = _path(args.db)
    events_path = _path(args.events)
    exists = db_path.exists()
    memory_count = 0
    event_count = 0
    if exists:
        with open_db(db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "memories" in tables:
                memory_count = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            if "events" in tables:
                event_count = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    print(f"DB path: {db_path}")
    print(f"Event log path: {events_path}")
    print(f"DB exists: {exists}")
    print(f"Memory count: {memory_count}")
    print(f"Event count: {event_count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual local Memory Engine CLI")
    parser.set_defaults(func=None)

    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Initialize the memory database")
    init_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    init_p.add_argument("--events", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    init_p.set_defaults(func=cmd_init)

    show_p = sub.add_parser("show", help="Show one memory by ID")
    show_p.add_argument("--id", dest="memory_id", type=int, required=True)
    show_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    show_p.set_defaults(func=cmd_show)

    add_p = sub.add_parser("add", help="Add a memory manually")
    add_p.add_argument("--type", dest="memory_type", required=True)
    add_p.add_argument("--scope", required=True)
    add_p.add_argument("--content", required=True)
    add_p.add_argument("--project")
    add_p.add_argument("--source", default="manual_cli")
    add_p.add_argument("--importance", type=int, default=5)
    add_p.add_argument("--confidence", type=float, default=0.7)
    add_p.add_argument("--status", default="observed")
    add_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    add_p.add_argument("--events", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", help="List memories")
    list_p.add_argument("--scope")
    list_p.add_argument("--project")
    list_p.add_argument("--type", dest="memory_type")
    list_p.add_argument("--status")
    list_p.add_argument("--limit", type=int, default=20)
    list_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    list_p.set_defaults(func=cmd_list)

    search_p = sub.add_parser("search", help="Search memories by keyword")
    search_p.add_argument("query")
    search_p.add_argument("--project")
    search_p.add_argument("--scope")
    search_p.add_argument("--type", dest="memory_type")
    search_p.add_argument("--limit", type=int, default=20)
    search_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    search_p.set_defaults(func=cmd_search)

    context_p = sub.add_parser("context", help="Show useful memory context")
    context_p.add_argument("--project")
    context_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    context_p.set_defaults(func=cmd_context)

    set_status_p = sub.add_parser("set-status", help="Update memory status")
    set_status_p.add_argument("--id", dest="memory_id", type=int, required=True)
    set_status_p.add_argument("--status", required=True, choices=sorted(MEMORY_STATUSES))
    set_status_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    set_status_p.add_argument("--events", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    set_status_p.set_defaults(func=cmd_set_status)

    archive_p = sub.add_parser("archive", help="Archive memory by ID")
    archive_p.add_argument("--id", dest="memory_id", type=int, required=True)
    archive_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    archive_p.add_argument("--events", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    archive_p.set_defaults(func=cmd_archive)

    audit_p = sub.add_parser("audit", help="Show memory database audit summary")
    audit_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    audit_p.add_argument("--events", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    audit_p.set_defaults(func=cmd_audit)

    status_p = sub.add_parser("status", help="Show memory database status")
    status_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    status_p.add_argument("--events", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    status_p.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
