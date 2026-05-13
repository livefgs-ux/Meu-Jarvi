"""Offline legacy memory migration tool (DRY-RUN ONLY - Phase 1A).

This tool reads a legacy JSON memory file from an explicit path, maps entries into
conservative migration candidates, applies privacy checks, and produces a dry-run report.

Safety:
- Does NOT write to SQLite.
- Does NOT write to JSONL event logs.
- Does NOT modify legacy JSON.
  - Does NOT call the Memory Engine writer module.
- Rejects --apply (not implemented in Phase 1A).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# When executed directly (python tools/migrate_legacy_memory.py), Python's import base
# is the tools/ directory, so project-root imports like "memory_engine" may fail.
# Keep behavior identical; just ensure imports resolve in direct-script mode.
if __package__ in {None, ""}:
    _repo_root = Path(__file__).resolve().parent.parent
    _repo_root_str = str(_repo_root)
    if _repo_root_str not in sys.path:
        sys.path.insert(0, _repo_root_str)

from memory_engine.privacy_guard import check_content_safe


KNOWN_CATEGORIES = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}


@dataclass(frozen=True, slots=True)
class LegacyMemoryItem:
    category: str
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class MigrationCandidate:
    source_category: str
    source_key: str
    content: str
    memory_type: str
    scope: str
    project: str | None
    status: str
    importance: int
    confidence: float
    requires_review: bool
    blocked: bool
    block_reason: str
    duplicate: bool = False
    duplicate_of: str = ""
    unknown_category: bool = False
    applied: bool = False
    skipped: bool = False
    skip_reason: str = ""


@dataclass(frozen=True, slots=True)
class MigrationReport:
    total_items: int
    migratable_items: int
    blocked_items: int
    review_required_items: int
    duplicate_items: int
    by_source_category: dict[str, int]
    by_memory_type: dict[str, int]
    by_scope: dict[str, int]
    unknown_categories: list[str]
    candidates: list[MigrationCandidate]
    missing_source: bool = False
    warning: str = ""
    applied_items: int = 0
    skipped_items: int = 0
    apply_requested: bool = False
    apply_confirmed: bool = False
    apply_target_db: str = ""
    apply_event_log: str = ""


def empty_missing_report(path: str | Path) -> MigrationReport:
    p = Path(path)
    return MigrationReport(
        total_items=0,
        migratable_items=0,
        blocked_items=0,
        review_required_items=0,
        duplicate_items=0,
        by_source_category={},
        by_memory_type={},
        by_scope={},
        unknown_categories=[],
        candidates=[],
        missing_source=True,
        warning=f"Legacy memory file not found. Nothing to migrate: {str(p)}",
        applied_items=0,
        skipped_items=0,
        apply_requested=False,
        apply_confirmed=False,
        apply_target_db="",
        apply_event_log="",
    )


def validate_apply_paths(db_path: str | Path, event_log_path: str | Path) -> tuple[Path, Path]:
    if not db_path:
        raise ValueError(
            "--apply requires --db-path. Refusing to write without an explicit temporary/test database path."
        )
    if not event_log_path:
        raise ValueError(
            "--apply requires --event-log-path. Refusing to write without an explicit temporary/test event log path."
        )

    repo_root = Path(__file__).resolve().parent.parent
    real_db = (repo_root / "data" / "jarvis_memory.db").resolve(strict=False)
    real_log = (repo_root / "data" / "raw_events.jsonl").resolve(strict=False)

    db_abs = Path(db_path).expanduser().resolve(strict=False)
    log_abs = Path(event_log_path).expanduser().resolve(strict=False)

    if db_abs == log_abs:
        raise ValueError("--db-path and --event-log-path must be different files.")
    if db_abs == real_db:
        raise ValueError(
            "Refusing to write to the real Jarvis memory database in Phase 2C: data/jarvis_memory.db. "
            "Use an explicit temporary/test DB path."
        )
    if log_abs == real_log:
        raise ValueError(
            "Refusing to write to the real Jarvis event log in Phase 2C: data/raw_events.jsonl. "
            "Use an explicit temporary/test event log path."
        )

    return db_abs, log_abs


def apply_report(
    report: MigrationReport,
    *,
    db_path: str | Path,
    event_log_path: str | Path,
    include_review: bool = False,
) -> MigrationReport:
    # Never write anything when legacy source is missing in allow-missing mode.
    if report.missing_source:
        return replace(
            report,
            applied_items=0,
            skipped_items=0,
            apply_requested=True,
            apply_confirmed=True,
        )

    db_abs, log_abs = validate_apply_paths(db_path, event_log_path)

    # Local import: apply-mode only. Avoid importing writer in pure dry-run flows.
    from memory_engine.writer import create_memory  # noqa: WPS433

    applied = 0
    skipped = 0
    updated_candidates: list[MigrationCandidate] = []

    for c in report.candidates:
        if c.blocked:
            skipped += 1
            updated_candidates.append(replace(c, skipped=True, skip_reason="blocked"))
            continue
        if c.duplicate:
            skipped += 1
            updated_candidates.append(replace(c, skipped=True, skip_reason="duplicate"))
            continue
        if c.requires_review and not include_review:
            skipped += 1
            updated_candidates.append(replace(c, skipped=True, skip_reason="requires_review"))
            continue

        # Eligible: write through Memory Engine writer (no SQL here).
        _ = create_memory(
            c.memory_type,
            c.scope,
            c.content,
            status=c.status,
            importance=c.importance,
            confidence=c.confidence,
            source="legacy_migration",
            project=c.project,
            metadata={
                "source_category": c.source_category,
                "source_key": c.source_key,
                "migration_phase": "2A",
            },
            db_path=db_abs,
            event_log_path=log_abs,
        )
        applied += 1
        updated_candidates.append(replace(c, applied=True))

    return replace(
        report,
        candidates=updated_candidates,
        applied_items=applied,
        skipped_items=skipped,
        apply_requested=True,
        apply_confirmed=True,
        apply_target_db=str(db_abs),
        apply_event_log=str(log_abs),
    )


def load_legacy_memory(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Legacy memory file not found: {str(p)}")
    try:
        # utf-8-sig handles Windows-generated UTF-8 BOM transparently.
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid legacy JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Legacy JSON root must be an object/dict")
    return data


def _coerce_value_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict) and "value" in value:
        v = value.get("value")
        return "" if v is None else str(v).strip()
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    # Conservative: stringify unknown types.
    return str(value).strip()


def iter_legacy_items(memory: dict[str, Any]) -> list[LegacyMemoryItem]:
    items: list[LegacyMemoryItem] = []
    if not isinstance(memory, dict):
        return items

    for category, bucket in memory.items():
        if bucket is None:
            continue
        cat = str(category).strip()
        if isinstance(bucket, dict):
            for key, raw in bucket.items():
                k = str(key).strip()
                v = _coerce_value_to_str(raw)
                if not k or not v:
                    continue
                items.append(LegacyMemoryItem(category=cat, key=k, value=v))
            continue

        # Some legacy exports may represent items as a list of {key,value} objects.
        if isinstance(bucket, list):
            for raw_item in bucket:
                if not isinstance(raw_item, dict):
                    continue
                k = str(raw_item.get("key", "")).strip()
                v = _coerce_value_to_str(raw_item.get("value"))
                if not k or not v:
                    continue
                items.append(LegacyMemoryItem(category=cat, key=k, value=v))
            continue

        # Unknown bucket shape: ignore.
        continue
    return items


def map_legacy_item(item: LegacyMemoryItem, project: str = "meu-jarvis") -> MigrationCandidate:
    cat = (item.category or "").strip()
    key = (item.key or "").strip()

    importance = 5
    confidence = 0.5
    status = "candidate"
    blocked = False
    block_reason = ""

    # Conservative mapping rules (Phase 1A).
    if cat == "preferences":
        memory_type = "PREFERENCE"
        scope = "global"
        proj: str | None = None
        requires_review = False
        unknown_category = False
    elif cat == "projects":
        memory_type = "PROJECT_CONTEXT"
        scope = f"project:{project}"
        proj = project
        requires_review = False
        unknown_category = False
    elif cat == "notes":
        memory_type = "IDEA"
        scope = f"project:{project}"
        proj = project
        requires_review = True
        unknown_category = False
    elif cat == "wishes":
        memory_type = "IDEA"
        scope = "global"
        proj = None
        requires_review = True
        unknown_category = False
    elif cat == "identity":
        memory_type = "PREFERENCE"
        scope = "global"
        proj = None
        requires_review = True
        unknown_category = False
    elif cat == "relationships":
        memory_type = "PREFERENCE"
        scope = "global"
        proj = None
        requires_review = True
        unknown_category = False
    else:
        # Unknown categories become review candidates.
        memory_type = "IDEA"
        scope = f"project:{project}"
        proj = project
        requires_review = True
        unknown_category = True

    content = f"{cat}.{key}: {item.value}"

    return MigrationCandidate(
        source_category=cat,
        source_key=key,
        content=content,
        memory_type=memory_type,
        scope=scope,
        project=proj,
        status=status,
        importance=importance,
        confidence=confidence,
        requires_review=requires_review,
        blocked=blocked,
        block_reason=block_reason,
        duplicate=False,
        duplicate_of="",
        unknown_category=unknown_category,
    )


def apply_privacy_check(candidate: MigrationCandidate) -> MigrationCandidate:
    result = check_content_safe(candidate.content)
    if result.allowed:
        return candidate
    return MigrationCandidate(
        source_category=candidate.source_category,
        source_key=candidate.source_key,
        content=candidate.content,
        memory_type=candidate.memory_type,
        scope=candidate.scope,
        project=candidate.project,
        status=candidate.status,
        importance=candidate.importance,
        confidence=candidate.confidence,
        requires_review=candidate.requires_review,
        blocked=True,
        block_reason=result.reason or "Blocked by privacy guard",
        duplicate=candidate.duplicate,
        duplicate_of=candidate.duplicate_of,
        unknown_category=candidate.unknown_category,
    )


def _normalize_content_for_dedupe(content: str) -> str:
    text = (content or "").strip().lower()
    return " ".join(text.split())


def _apply_dedupe(candidates: list[MigrationCandidate]) -> list[MigrationCandidate]:
    seen: dict[str, MigrationCandidate] = {}
    out: list[MigrationCandidate] = []
    for c in candidates:
        key = f"{c.memory_type}|{c.scope}|{_normalize_content_for_dedupe(c.content)}"
        if key in seen:
            first = seen[key]
            out.append(
                MigrationCandidate(
                    source_category=c.source_category,
                    source_key=c.source_key,
                    content=c.content,
                    memory_type=c.memory_type,
                    scope=c.scope,
                    project=c.project,
                    status=c.status,
                    importance=c.importance,
                    confidence=c.confidence,
                    requires_review=c.requires_review,
                    blocked=c.blocked,
                    block_reason=c.block_reason,
                    duplicate=True,
                    duplicate_of=f"{first.source_category}.{first.source_key}",
                    unknown_category=c.unknown_category,
                )
            )
        else:
            seen[key] = c
            out.append(c)
    return out


def build_dry_run_report(
    path: str | Path,
    project: str = "meu-jarvis",
    *,
    allow_missing: bool = False,
) -> MigrationReport:
    p = Path(path)
    if not p.exists():
        if allow_missing:
            return empty_missing_report(p)
        # Preserve strict behavior by default to avoid hiding wrong paths.
        raise FileNotFoundError(f"Legacy memory file not found: {str(p)}")

    legacy = load_legacy_memory(p)
    legacy_items = iter_legacy_items(legacy)
    candidates: list[MigrationCandidate] = []

    for it in legacy_items:
        cand = map_legacy_item(it, project=project)
        cand = apply_privacy_check(cand)
        candidates.append(cand)

    candidates = _apply_dedupe(candidates)

    total = len(candidates)
    blocked = sum(1 for c in candidates if c.blocked)
    duplicates = sum(1 for c in candidates if c.duplicate)
    review_required = sum(1 for c in candidates if c.requires_review and not c.blocked)
    migratable = sum(1 for c in candidates if (not c.blocked) and (not c.duplicate))

    by_cat: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    unknown: set[str] = set()
    for c in candidates:
        by_cat[c.source_category] = by_cat.get(c.source_category, 0) + 1
        by_type[c.memory_type] = by_type.get(c.memory_type, 0) + 1
        by_scope[c.scope] = by_scope.get(c.scope, 0) + 1
        if c.unknown_category:
            unknown.add(c.source_category)

    return MigrationReport(
        total_items=total,
        migratable_items=migratable,
        blocked_items=blocked,
        review_required_items=review_required,
        duplicate_items=duplicates,
        by_source_category=by_cat,
        by_memory_type=by_type,
        by_scope=by_scope,
        unknown_categories=sorted(unknown),
        candidates=candidates,
    )


def format_report(report: MigrationReport) -> str:
    lines: list[str] = []
    lines.append("Legacy Memory Migration Report")

    if report.missing_source and report.warning:
        lines.append("")
        lines.append("Missing Source")
        lines.append(f"- {report.warning}")

    if report.apply_requested:
        lines.append("")
        lines.append("Apply Preview (safe)")
        if report.apply_target_db:
            lines.append(f"- Apply target DB: {report.apply_target_db}")
        if report.apply_event_log:
            lines.append(f"- Apply event log: {report.apply_event_log}")
        lines.append("- Candidate content omitted by default.")

    # Summary
    lines.append("")
    lines.append("Summary")
    lines.append(f"- Total items: {report.total_items}")
    lines.append(f"- Migratable: {report.migratable_items}")
    lines.append(f"- Blocked: {report.blocked_items}")
    lines.append(f"- Requires review: {report.review_required_items}")
    lines.append(f"- Duplicates: {report.duplicate_items}")
    lines.append(f"- Applied: {report.applied_items}")
    lines.append(f"- Skipped: {report.skipped_items}")

    if report.by_source_category:
        lines.append("")
        lines.append("Breakdown by Source Category")
        for k in sorted(report.by_source_category):
            lines.append(f"- {k}: {report.by_source_category[k]}")

    if report.by_memory_type:
        lines.append("")
        lines.append("Breakdown by Memory Type")
        for k in sorted(report.by_memory_type):
            lines.append(f"- {k}: {report.by_memory_type[k]}")

    if report.by_scope:
        lines.append("")
        lines.append("Breakdown by Scope")
        for k in sorted(report.by_scope):
            lines.append(f"- {k}: {report.by_scope[k]}")

    blocked = [c for c in report.candidates if c.blocked]
    if blocked:
        lines.append("")
        lines.append("Blocked Items (content omitted)")
        for c in blocked[:50]:
            lines.append(f"- {c.source_category}.{c.source_key}: {c.block_reason}")
        if len(blocked) > 50:
            lines.append(f"... ({len(blocked) - 50} more)")

    skipped_items = [c for c in report.candidates if c.skipped]
    if skipped_items:
        lines.append("")
        lines.append("Skipped Items (content omitted)")
        # Optional: show skip reason counts first.
        by_reason: dict[str, int] = {}
        for c in skipped_items:
            r = c.skip_reason or "unknown"
            by_reason[r] = by_reason.get(r, 0) + 1
        for r in sorted(by_reason):
            lines.append(f"- {r}: {by_reason[r]}")
        for c in skipped_items[:50]:
            lines.append(f"- {c.source_category}.{c.source_key}: {c.skip_reason}")
        if len(skipped_items) > 50:
            lines.append(f"... ({len(skipped_items) - 50} more)")

    if report.unknown_categories:
        lines.append("")
        lines.append("Unknown Categories")
        for cat in report.unknown_categories[:50]:
            lines.append(f"- {cat}")
        if len(report.unknown_categories) > 50:
            lines.append(f"... ({len(report.unknown_categories) - 50} more)")

    unknown_items = [c for c in report.candidates if c.unknown_category]
    if unknown_items:
        lines.append("")
        lines.append("Unknown Category Items (value omitted)")
        for c in unknown_items[:50]:
            lines.append(f"- {c.source_category}.{c.source_key}")
        if len(unknown_items) > 50:
            lines.append(f"... ({len(unknown_items) - 50} more)")

    return "\n".join(lines).rstrip() + "\n"


def _report_to_safe_json(report: MigrationReport, *, include_content: bool) -> dict[str, Any]:
    # Safe JSON output: content omitted by default; never include blocked content.
    out = {
        "missing_source": bool(report.missing_source),
        "warning": report.warning or "",
        "total_items": report.total_items,
        "migratable_items": report.migratable_items,
        "blocked_items": report.blocked_items,
        "review_required_items": report.review_required_items,
        "duplicate_items": report.duplicate_items,
        "applied_items": report.applied_items,
        "skipped_items": report.skipped_items,
        "apply_requested": bool(report.apply_requested),
        "apply_confirmed": bool(report.apply_confirmed),
        "apply_target_db": report.apply_target_db or "",
        "apply_event_log": report.apply_event_log or "",
        # Keep explicit "breakdown_*" keys; also keep legacy "by_*" for compatibility.
        "breakdown_by_source_category": dict(report.by_source_category),
        "breakdown_by_memory_type": dict(report.by_memory_type),
        "breakdown_by_scope": dict(report.by_scope),
        "by_source_category": dict(report.by_source_category),
        "by_memory_type": dict(report.by_memory_type),
        "by_scope": dict(report.by_scope),
        "unknown_categories": list(report.unknown_categories),
        "candidates": [],
    }
    for c in report.candidates:
        item = {
            "source_category": c.source_category,
            "source_key": c.source_key,
            "memory_type": c.memory_type,
            "scope": c.scope,
            "project": c.project,
            "status": c.status,
            "importance": c.importance,
            "confidence": c.confidence,
            "requires_review": c.requires_review,
            "blocked": c.blocked,
            "block_reason": c.block_reason,
            "duplicate": c.duplicate,
            "duplicate_of": c.duplicate_of,
            "unknown_category": c.unknown_category,
            "applied": c.applied,
            "skipped": c.skipped,
            "skip_reason": c.skip_reason,
        }
        if include_content and (not c.blocked):
            item["content"] = c.content
        out["candidates"].append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_legacy_memory", add_help=True)
    parser.add_argument("--legacy-path", required=True, help="Path to legacy memory JSON file")
    parser.add_argument("--project", default="meu-jarvis", help="Project name used for project:<name> scopes")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry-run only (default)")
    parser.add_argument("--json", action="store_true", help="Print JSON report (safe output)")
    parser.add_argument("--include-content", action="store_true", help="Include content in JSON for non-blocked items only")
    parser.add_argument("--allow-missing", action="store_true", help="If legacy file is missing, return an empty report (exit 0)")
    parser.add_argument("--apply", action="store_true", help="Apply eligible candidates to an explicit temp DB/log (Phase 2A)")
    parser.add_argument("--db-path", help="SQLite DB path for --apply (must be explicit; real runtime DB is rejected)")
    parser.add_argument("--event-log-path", help="JSONL event log path for --apply (must be explicit; real runtime log is rejected)")
    parser.add_argument("--include-review", action="store_true", help="Include requires_review candidates in --apply (still skips blocked/duplicates)")
    parser.add_argument("--confirm-apply", action="store_true", help="Required with --apply to prevent accidental writes")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse uses SystemExit for -h and usage errors.
        return int(e.code) if isinstance(e.code, int) else 2

    if args.apply and (not args.confirm_apply):
        print(
            "ERROR: --apply requires --confirm-apply in this phase. This prevents accidental writes.",
            file=sys.stderr,
        )
        return 2
    if args.apply and (not args.db_path):
        print(
            "ERROR: --apply requires --db-path. Refusing to write without an explicit temporary/test database path.",
            file=sys.stderr,
        )
        return 2
    if args.apply and (not args.event_log_path):
        print(
            "ERROR: --apply requires --event-log-path. Refusing to write without an explicit temporary/test event log path.",
            file=sys.stderr,
        )
        return 2

    try:
        report = build_dry_run_report(args.legacy_path, project=args.project, allow_missing=bool(args.allow_missing))
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        # Fail closed with a generic message (no raw details).
        print("ERROR: failed to process legacy memory file", file=sys.stderr)
        _ = e
        return 1

    if args.apply:
        try:
            report = apply_report(
                report,
                db_path=args.db_path,
                event_log_path=args.event_log_path,
                include_review=bool(args.include_review),
            )
            # Attach safe apply metadata for output (even if missing_source=True).
            report = replace(
                report,
                apply_requested=True,
                apply_confirmed=True,
                apply_target_db=str(Path(args.db_path).expanduser().resolve(strict=False)),
                apply_event_log=str(Path(args.event_log_path).expanduser().resolve(strict=False)),
            )
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print("ERROR: failed to apply migration report", file=sys.stderr)
            _ = e
            return 1

    if args.json:
        print(json.dumps(_report_to_safe_json(report, include_content=bool(args.include_content)), indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(format_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
