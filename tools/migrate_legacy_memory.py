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
from dataclasses import dataclass
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
    )


def load_legacy_memory(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Legacy memory file not found: {str(p)}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
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
    lines.append("Legacy Memory Migration Dry-Run Report")
    if report.missing_source and report.warning:
        lines.append(f"WARNING: {report.warning}")
    lines.append(f"Total items: {report.total_items}")
    lines.append(f"Migratable: {report.migratable_items}")
    lines.append(f"Blocked (privacy): {report.blocked_items}")
    lines.append(f"Requires review: {report.review_required_items}")
    lines.append(f"Duplicates: {report.duplicate_items}")

    if report.by_source_category:
        lines.append("")
        lines.append("By source category:")
        for k in sorted(report.by_source_category):
            lines.append(f"- {k}: {report.by_source_category[k]}")

    if report.by_memory_type:
        lines.append("")
        lines.append("By memory type:")
        for k in sorted(report.by_memory_type):
            lines.append(f"- {k}: {report.by_memory_type[k]}")

    if report.by_scope:
        lines.append("")
        lines.append("By scope:")
        for k in sorted(report.by_scope):
            lines.append(f"- {k}: {report.by_scope[k]}")

    blocked = [c for c in report.candidates if c.blocked]
    if blocked:
        lines.append("")
        lines.append("Blocked items (content omitted):")
        for c in blocked[:50]:
            lines.append(f"- {c.source_category}.{c.source_key}: {c.block_reason}")
        if len(blocked) > 50:
            lines.append(f"... ({len(blocked) - 50} more)")

    if report.unknown_categories:
        lines.append("")
        lines.append("Unknown categories:")
        for cat in report.unknown_categories[:50]:
            lines.append(f"- {cat}")
        if len(report.unknown_categories) > 50:
            lines.append(f"... ({len(report.unknown_categories) - 50} more)")

    unknown_items = [c for c in report.candidates if c.unknown_category]
    if unknown_items:
        lines.append("")
        lines.append("Unknown category items (value omitted):")
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
    parser.add_argument("--apply", action="store_true", help="NOT IMPLEMENTED in Phase 1A (dry-run only)")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse uses SystemExit for -h and usage errors.
        return int(e.code) if isinstance(e.code, int) else 2

    if args.apply:
        print("ERROR: --apply is not implemented in Phase 1A. Use dry-run only.", file=sys.stderr)
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

    if args.json:
        print(json.dumps(_report_to_safe_json(report, include_content=bool(args.include_content)), indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(format_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
