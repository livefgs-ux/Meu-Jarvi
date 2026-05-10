"""Local Jarvis memory engine foundation.

This package is intentionally standalone. It is not connected to the running
Jarvis app in this version.
"""

from .schemas import MemoryRecord
from .database import DEFAULT_DB_PATH, init_db
from .writer import archive_memory, create_memory, update_memory_status
from .retriever import (
    get_memory_by_id,
    list_active_global_rules,
    list_memories_by_scope,
    list_project_context,
    retrieve_context,
    search_memories,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "MemoryRecord",
    "archive_memory",
    "create_memory",
    "get_memory_by_id",
    "init_db",
    "list_active_global_rules",
    "list_memories_by_scope",
    "list_project_context",
    "retrieve_context",
    "search_memories",
    "update_memory_status",
]
