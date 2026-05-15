import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any, Set, Callable, Coroutine
from core.runtime_journal import record_event

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_RESOURCE = "waiting_resource"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

@dataclass
class TaskRecord:
    task_id: str
    name: str
    status: TaskStatus
    priority: TaskPriority
    resource_locks: Set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        d["resource_locks"] = list(self.resource_locks)
        return d

class ConcurrentTaskRuntime:
    def __init__(self):
        self.tasks: Dict[str, TaskRecord] = {}
        self._active_locks: Dict[str, str] = {}  # lock_name -> task_id
        self._lock = asyncio.Lock()
        self._process_task: Optional[asyncio.Task] = None
        self._task_handles: Dict[str, asyncio.Task] = {}

    async def start(self):
        if self._process_task is None:
            self._process_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self):
        if self._process_task:
            self._process_task.cancel()
            self._process_task = None

    async def submit(
        self, 
        name: str, 
        coro_func: Callable[..., Coroutine],
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        resource_locks: Optional[Set[str]] = None,
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        
        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            name=name,
            status=TaskStatus.PENDING,
            priority=priority,
            resource_locks=resource_locks or set(),
            correlation_id=correlation_id,
            metadata=metadata or {}
        )
        
        async with self._lock:
            self.tasks[task_id] = record

        record_event("task_submitted", name, f"Task submitted: {name} ({task_id})", 
                     metadata={"task_id": task_id, "priority": priority.name}, correlation_id=correlation_id)
        
        # Start execution wrapper
        task = asyncio.create_task(self._run_task_wrapper(task_id, coro_func, args or [], kwargs or {}))
        async with self._lock:
            self._task_handles[task_id] = task
        
        return task_id

    async def _run_task_wrapper(self, task_id: str, coro_func: Callable, args: List, kwargs: Dict):
        record = self.tasks[task_id]
        
        # Resource waiting logic
        while True:
            async with self._lock:
                if self.can_run_now(record.resource_locks, task_id):
                    self.acquire_locks(task_id, record.resource_locks)
                    record.status = TaskStatus.RUNNING
                    record.started_at = time.time()
                    break
                else:
                    if record.status != TaskStatus.WAITING_RESOURCE:
                        record.status = TaskStatus.WAITING_RESOURCE
                        record_event("task_waiting_resource", record.name, f"Task {record.name} waiting for resources", 
                                     metadata={"task_id": task_id, "locks": list(record.resource_locks)}, correlation_id=record.correlation_id)
            
            await asyncio.sleep(0.5)

        record_event("task_started", record.name, f"Task started: {record.name}", 
                     metadata={"task_id": task_id}, correlation_id=record.correlation_id)

        try:
            result = await coro_func(*args, **kwargs)
            async with self._lock:
                record.status = TaskStatus.COMPLETED
                record.result = self._truncate_value(result)
                record.completed_at = time.time()
        except asyncio.CancelledError:
            async with self._lock:
                if record.status != TaskStatus.CANCELLED:
                    record.status = TaskStatus.CANCELLED
                record.completed_at = time.time()
            record_event("task_cancelled", record.name, f"Task cancelled: {record.name}",
                         metadata={"task_id": task_id}, correlation_id=record.correlation_id)
            return
        except Exception as e:
            error_msg = str(e)
            async with self._lock:
                record.status = TaskStatus.FAILED
                record.error = self._truncate_value(error_msg)
                record.completed_at = time.time()
            record_event("task_failed", record.name, f"Task failed: {record.name} - {error_msg[:100]}", 
                         metadata={"task_id": task_id, "error": error_msg}, severity="error", correlation_id=record.correlation_id)
        finally:
            async with self._lock:
                self.release_locks(task_id)
                self._task_handles.pop(task_id, None)
                if record.status == TaskStatus.COMPLETED:
                    record_event("task_completed", record.name, f"Task completed: {record.name}", 
                                 metadata={"task_id": task_id}, correlation_id=record.correlation_id)

    def can_run_now(self, locks: Set[str], task_id: str) -> bool:
        # Check conflicts
        for lock in locks:
            if lock in self._active_locks and self._active_locks[lock] != task_id:
                return False
            
            # Mutual exclusion for UI/Input
            ui_critical = {"keyboard", "mouse", "active_window"}
            if lock in ui_critical:
                for active_lock in self._active_locks:
                    if active_lock in ui_critical:
                        return False
        return True

    def acquire_locks(self, task_id: str, locks: Set[str]):
        for lock in locks:
            self._active_locks[lock] = task_id

    def release_locks(self, task_id: str):
        locks_to_remove = [k for k, v in self._active_locks.items() if v == task_id]
        for lock in locks_to_remove:
            del self._active_locks[lock]

    def cancel(self, task_id: str):
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.CANCELLED
            handle = self._task_handles.get(task_id)
            if handle and not handle.done():
                handle.cancel()
            record_event("task_cancelled", self.tasks[task_id].name, f"Task cancelled: {task_id}", 
                         metadata={"task_id": task_id})

    async def wait_for_idle(self, timeout: float = 1.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            async with self._lock:
                active = [t for t in self._task_handles.values() if not t.done()]
            if not active:
                return True
            await asyncio.sleep(0.05)
        return False

    async def shutdown(self, cancel_pending: bool = True, timeout: float = 1.0):
        async with self._lock:
            task_handles = list(self._task_handles.items())
            process_task = self._process_task

        if cancel_pending:
            for _, task in task_handles:
                if not task.done():
                    task.cancel()
            if process_task and not process_task.done():
                process_task.cancel()

        pending = [task for _, task in task_handles]
        if process_task:
            pending.append(process_task)

        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
            except asyncio.TimeoutError:
                pass

        async with self._lock:
            for record in self.tasks.values():
                if record.status in [
                    TaskStatus.PENDING,
                    TaskStatus.RUNNING,
                    TaskStatus.WAITING_RESOURCE,
                    TaskStatus.WAITING_CONFIRMATION,
                ] and cancel_pending:
                    record.status = TaskStatus.CANCELLED
                    record.completed_at = record.completed_at or time.time()
            self._active_locks.clear()
            self._task_handles.clear()
            self._process_task = None

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.tasks.get(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[TaskRecord]:
        if status:
            return [t for t in self.tasks.values() if t.status == status]
        return list(self.tasks.values())

    def list_running(self) -> List[TaskRecord]:
        return self.list_tasks(TaskStatus.RUNNING)

    def list_pending(self) -> List[TaskRecord]:
        return self.list_tasks(TaskStatus.PENDING)

    def clear_finished(self):
        to_remove = [tid for tid, t in self.tasks.items() if t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]]
        for tid in to_remove:
            del self.tasks[tid]

    def _truncate_value(self, val: Any, max_len: int = 2000) -> Any:
        if isinstance(val, str) and len(val) > max_len:
            return val[:max_len] + "... [TRUNCATED]"
        return val

    async def _scheduler_loop(self):
        # Placeholder if we need a central loop. 
        # Currently, each task has its own wrapper that waits for resources.
        while True:
            await asyncio.sleep(10)

_GLOBAL_RUNTIME = ConcurrentTaskRuntime()

def get_task_runtime() -> ConcurrentTaskRuntime:
    return _GLOBAL_RUNTIME
