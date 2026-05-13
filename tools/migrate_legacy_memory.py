"""Offline legacy memory migration tool (DRY-RUN ONLY - Phase 1A).

This tool reads a legacy JSON memory file from an explicit path, maps entries into
conservative migration candidates, applies privacy checks, and produces a dry-run report.

Safety:
- Does NOT write to SQLite.
- Does NOT write to JSONL event logs.
- Does NOT modify legacy JSON.
- Does NOT call memory_engine.writer.*.
- Rejects --apply (not implemented in Phase 1A).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True, slots=True)
class MigrationReport:
    total_items: int
    migratable_items: int
    blocked_items: int
    review_required_items: int
    candidates: list[MigrationCandidate]


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
        if not isinstance(bucket, dict):
            continue
        for key, raw in bucket.items():
            k = str(key).strip()
            v = _coerce_value_to_str(raw)
            if not k or not v:
                continue
            items.append(LegacyMemoryItem(category=cat, key=k, value=v))
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
    elif cat == "projects":
        memory_type = "PROJECT_CONTEXT"
        scope = f"project:{project}"
        proj = project
        requires_review = False
    elif cat == "notes":
        memory_type = "IDEA"
        scope = f"project:{project}"
        proj = project
        requires_review = True
    elif cat == "wishes":
        memory_type = "IDEA"
        scope = "global"
        proj = None
        requires_review = True
    elif cat == "identity":
        memory_type = "PREFERENCE"
        scope = "global"
        proj = None
        requires_review = True
    elif cat == "relationships":
        memory_type = "PREFERENCE"
        scope = "global"
        proj = None
        requires_review = True
    else:
        # Unknown categories become review candidates.
        memory_type = "IDEA"
        scope = f"project:{project}"
        proj = project
        requires_review = True

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
    )


def build_dry_run_report(path: str | Path, project: str = "meu-jarvis") -> MigrationReport:
    legacy = load_legacy_memory(path)
    legacy_items = iter_legacy_items(legacy)
    candidates: list[MigrationCandidate] = []

    for it in legacy_items:
        cand = map_legacy_item(it, project=project)
        cand = apply_privacy_check(cand)
        candidates.append(cand)

    total = len(candidates)
    blocked = sum(1 for c in candidates if c.blocked)
    review_required = sum(1 for c in candidates if c.requires_review and not c.blocked)
    migratable = sum(1 for c in candidates if not c.blocked)

    return MigrationReport(
        total_items=total,
        migratable_items=migratable,
        blocked_items=blocked,
        review_required_items=review_required,
        candidates=candidates,
    )


def format_report(report: MigrationReport) -> str:
    lines: list[str] = []
    lines.append("Legacy Memory Migration Dry-Run Report")
    lines.append(f"Total items: {report.total_items}")
    lines.append(f"Migratable: {report.migratable_items}")
    lines.append(f"Blocked (privacy): {report.blocked_items}")
    lines.append(f"Requires review: {report.review_required_items}")

    # Category breakdown.
    by_cat: dict[str, int] = {}
    for c in report.candidates:
        by_cat[c.source_category] = by_cat.get(c.source_category, 0) + 1
    if by_cat:
        lines.append("")
        lines.append("By category:")
        for k in sorted(by_cat):
            lines.append(f"- {k}: {by_cat[k]}")

    blocked = [c for c in report.candidates if c.blocked]
    if blocked:
        lines.append("")
        lines.append("Blocked items (content omitted):")
        for c in blocked[:50]:
            lines.append(f"- {c.source_category}.{c.source_key}: {c.block_reason}")
        if len(blocked) > 50:
            lines.append(f"... ({len(blocked) - 50} more)")

    return "\n".join(lines).rstrip() + "\n"


def _report_to_safe_json(report: MigrationReport) -> dict[str, Any]:
    # Safe JSON output: do not include content for blocked items.
    out = {
        "total_items": report.total_items,
        "migratable_items": report.migratable_items,
        "blocked_items": report.blocked_items,
        "review_required_items": report.review_required_items,
        "candidates": [],
    }
    for c in report.candidates:
        out["candidates"].append(
            {
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
                "content": "" if c.blocked else c.content,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_legacy_memory", add_help=True)
    parser.add_argument("--legacy-path", required=True, help="Path to legacy memory JSON file")
    parser.add_argument("--project", default="meu-jarvis", help="Project name used for project:<name> scopes")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry-run only (default)")
    parser.add_argument("--json", action="store_true", help="Print JSON report (safe output)")
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
        report = build_dry_run_report(args.legacy_path, project=args.project)
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
        print(json.dumps(_report_to_safe_json(report), indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(format_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

