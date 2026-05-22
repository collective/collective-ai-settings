"""Thread-safe in-memory registry of in-flight AI calls.

Each task is keyed by a UUID and has one of three states:
``running`` (no result yet), ``done`` (``result`` populated), or
``error`` (``error`` populated). Tasks linger after completion so the
client has time to poll for the final state; old finished tasks are
pruned opportunistically on each read.
"""

from threading import Lock

import time
import uuid


_TASKS: dict[str, dict] = {}
_LOCK = Lock()

# Finished tasks older than this are dropped on the next access to keep
# the registry from growing without bound.
_FINISHED_TTL_SECONDS = 60 * 30


def _prune_locked():
    cutoff = time.time() - _FINISHED_TTL_SECONDS
    stale = [
        tid
        for tid, task in _TASKS.items()
        if task["status"] != "running" and task.get("finished_at", 0) < cutoff
    ]
    for tid in stale:
        del _TASKS[tid]


def create_task() -> str:
    task_id = str(uuid.uuid4())
    with _LOCK:
        _TASKS[task_id] = {
            "status": "running",
            "started_at": time.time(),
        }
    return task_id


def complete_task(task_id: str, result) -> None:
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id] = {
                "status": "done",
                "result": result,
                "started_at": _TASKS[task_id].get("started_at"),
                "finished_at": time.time(),
            }


def fail_task(task_id: str, error: str) -> None:
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id] = {
                "status": "error",
                "error": error,
                "started_at": _TASKS[task_id].get("started_at"),
                "finished_at": time.time(),
            }


def get_task(task_id: str) -> dict | None:
    with _LOCK:
        _prune_locked()
        task = _TASKS.get(task_id)
        return dict(task) if task else None
