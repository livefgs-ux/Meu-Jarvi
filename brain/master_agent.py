"""Standalone Jarvis Brain facade."""

from __future__ import annotations

from pathlib import Path

from .context_detector import detect_context
from .router import choose_mode
from .validator import validate_brain_request
from memory_engine.database import DEFAULT_DB_PATH, init_db
from memory_engine.event_log import DEFAULT_EVENT_LOG_PATH
from memory_engine.retriever import (
    list_active_global_rules,
    list_project_context,
    retrieve_context,
    search_memories,
)
from memory_engine.writer import create_memory


class JarvisBrain:
    def __init__(
        self,
        db_path: str | Path | None = None,
        event_log_path: str | Path | None = None,
    ) -> None:
        self._explicit_db_path = db_path is not None
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.event_log_path = Path(event_log_path) if event_log_path is not None else DEFAULT_EVENT_LOG_PATH
        self.initialized = False

    def initialize(self) -> Path:
        self.initialized = True
        return init_db(self.db_path)

    def _can_read_memory(self) -> bool:
        return self.initialized or self._explicit_db_path or self.db_path.exists()

    def analyze_request(self, user_input: str, project: str | None = None) -> dict:
        context = detect_context(user_input, project=project)
        mode = choose_mode(context)
        validation = validate_brain_request(user_input, project=project)

        if self._can_read_memory():
            memory_context = retrieve_context(
                project=context.get("probable_project"),
                task=context.get("raw_input") or None,
                db_path=self.db_path,
            )
        else:
            memory_context = {
                "global_rules": [],
                "project_context": [],
                "task_context": [],
                "procedures": [],
                "decisions": [],
                "warnings": [],
            }

        return {
            "context": context,
            "mode": mode,
            "recommended_mode": mode,
            "validation": validation,
            "memory_context": memory_context,
        }

    def remember(
        self,
        memory_type: str,
        scope: str,
        content: str,
        *,
        project: str | None = None,
        source: str = "brain",
        importance: int = 5,
        confidence: float = 0.7,
        status: str = "observed",
    ):
        return create_memory(
            memory_type,
            scope,
            content,
            project=project,
            source=source,
            importance=importance,
            confidence=confidence,
            status=status,
            db_path=self.db_path,
            event_log_path=self.event_log_path,
        )

    def recall(self, project: str | None = None, query: str | None = None) -> dict:
        if not self._can_read_memory():
            return {
                "global_rules": [],
                "project_context": [],
                "matching_memories": [],
            }

        matching = []
        if query:
            matching = search_memories(query=query, db_path=self.db_path, limit=20)

        return {
            "global_rules": list_active_global_rules(db_path=self.db_path),
            "project_context": list_project_context(project, db_path=self.db_path) if project else [],
            "matching_memories": matching,
        }
