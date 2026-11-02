"""Registry of in-flight async AI calls.

Each task is keyed by a UUID and has one of three states:
``running`` (no result yet), ``done`` (``result`` populated), or
``error`` (``error`` populated). Tasks linger after completion so the
client has time to poll for the final state.

By default the registry is a thread-safe in-memory dict, so a task is only
visible in the process that created it: old finished tasks are pruned
opportunistically on each read.

Setting ``COLLECTIVE_AISETTINGS_TASK_STORE`` to ``memcached://host:port``
(or a comma-separated list of ``host:port``) switches on the shared store
(:class:`SharedTaskStore`), so any process behind a load balancer can answer
the poll. Only then do the extras apply: lost-task detection
(``COLLECTIVE_AISETTINGS_TASK_MAX_RUNNING``), owner checks, and
:func:`begin_shutdown`. An invalid value logs one error and leaves the
in-memory behaviour untouched.

The store holds *state*, not cache: point it at a memcached instance of its
own, not one shared with an evicting cache, or records can vanish mid-poll.
"""

from collective.aisettings import logger
from collective.aisettings.events import TaskLostEvent
from threading import Lock
from threading import Timer
from zope.event import notify

import json
import math
import os
import time
import uuid


try:
    from pymemcache.exceptions import MemcacheServerError
    from pymemcache.exceptions import MemcacheUnexpectedCloseError
except ImportError:  # optional: collective.aisettings[memcached]
    MemcacheServerError = MemcacheUnexpectedCloseError = ()

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


def _local_create_task() -> str:
    task_id = str(uuid.uuid4())
    with _LOCK:
        _TASKS[task_id] = {
            "status": "running",
            "started_at": time.time(),
        }
    return task_id


def _local_complete_task(task_id: str, result) -> None:
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id] = {
                "status": "done",
                "result": result,
                "started_at": _TASKS[task_id].get("started_at"),
                "finished_at": time.time(),
            }


def _local_fail_task(task_id: str, error: str) -> None:
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id] = {
                "status": "error",
                "error": error,
                "started_at": _TASKS[task_id].get("started_at"),
                "finished_at": time.time(),
            }


def _local_get_task(task_id: str) -> dict | None:
    with _LOCK:
        _prune_locked()
        task = _TASKS.get(task_id)
        return dict(task) if task else None


# -- shared store ------------------------------------------------------------

STORE_ENV = "COLLECTIVE_AISETTINGS_TASK_STORE"
PREFIX_ENV = "COLLECTIVE_AISETTINGS_TASK_STORE_PREFIX"
MAX_RUNNING_ENV = "COLLECTIVE_AISETTINGS_TASK_MAX_RUNNING"
TTL_ENV = "COLLECTIVE_AISETTINGS_TASK_TTL"
DRAIN_ENV = "COLLECTIVE_AISETTINGS_TASK_DRAIN"

DEFAULT_PREFIX = "collective.aisettings.task:"
DEFAULT_MAX_RUNNING = 900.0
DEFAULT_TTL = 1800.0
DEFAULT_DRAIN = 0.0

#: Extra lifetime of a ``running`` record past ``max_running``, so the read
#: rule still finds it to report the task as lost.
EXPIRY_MARGIN = 60
#: After a memcached failure, skip it for this long (circuit breaker).
RETRY_AFTER = 30
CONNECT_TIMEOUT = 0.2
TIMEOUT = 0.5
MAX_PREFIX_LENGTH = 150

LOST_MESSAGE = "The task did not finish. Please try again."
INTERRUPTED_MESSAGE = "The task was interrupted by a server restart. Please try again."
TOO_LARGE_MESSAGE = "The result was too large for the task store."

#: Record fields that are bookkeeping, never part of a poll response.
_PRIVATE_FIELDS = ("owner", "label", "lost")


class TaskStoreShuttingDown(Exception):
    """Raised by :func:`create_task` once :func:`begin_shutdown` was called.

    Endpoints answer it with ``503`` and ``Retry-After``, so the client
    retries against another process."""


def _public(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in _PRIVATE_FIELDS}


class SharedTaskStore:
    """Task records in memcached, shared by every process using the same
    server(s) and ``prefix``.

    The worker thread still runs in the process that created the task; only
    its state is shared. Records are JSON. When memcached is unreachable the
    store falls back to a local dict (the task then only works on this
    process, as without the shared store) and skips memcached for
    ``RETRY_AFTER`` seconds.
    """

    def __init__(
        self,
        client,
        prefix=DEFAULT_PREFIX,
        max_running=DEFAULT_MAX_RUNNING,
        ttl=DEFAULT_TTL,
        drain=DEFAULT_DRAIN,
    ):
        self.client = client
        self.prefix = prefix
        self.max_running = max_running
        self.ttl = ttl
        self.drain = drain
        self._lock = Lock()
        # Fallback records, used only while memcached is failing.
        self._local: dict[str, dict] = {}
        # Tasks running in *this* process: task_id -> {"timer", "started_at",
        # "label", "owner", "marked"}. "marked" is set once the task was
        # reported lost or interrupted, so a late result does not overwrite it.
        self._running: dict[str, dict] = {}
        self._down_until = 0.0
        self._shutting_down = False

    # -- memcached access --

    def _key(self, task_id):
        return f"{self.prefix}{task_id}"

    def _available(self):
        return time.monotonic() >= self._down_until

    def _failed(self, action, exc):
        first = self._available()
        self._down_until = time.monotonic() + RETRY_AFTER
        if first:
            logger.warning(
                "AI task store: memcached %s failed (%s); using the local "
                "store for %ss",
                action,
                exc,
                RETRY_AFTER,
            )

    def _read(self, task_id):
        """Return the record, or ``None``. Memcached first, then local."""
        if self._available():
            try:
                raw = self.client.get(self._key(task_id))
            except Exception as exc:
                self._failed("get", exc)
            else:
                if raw is not None:
                    return json.loads(raw)
        with self._lock:
            record = self._local.get(task_id)
            return dict(record) if record else None

    def _write(self, task_id, record, expire):
        """Store ``record``; on failure keep it locally instead."""
        if self._available():
            payload = json.dumps(record).encode("utf-8")
            try:
                stored = self.client.set(
                    self._key(task_id),
                    payload,
                    expire=math.ceil(expire),
                    noreply=False,
                )
            except MemcacheUnexpectedCloseError as exc:
                self._failed("set", exc)
            except MemcacheServerError as exc:
                # "object too large for cache": not an outage.
                return self._write_too_large(task_id, record, expire, exc)
            except Exception as exc:
                self._failed("set", exc)
            else:
                if stored:
                    with self._lock:
                        self._local.pop(task_id, None)
                    return
                return self._write_too_large(task_id, record, expire, "not stored")
        with self._lock:
            self._prune_local_locked()
            self._local[task_id] = dict(record)

    def _write_too_large(self, task_id, record, expire, reason):
        if record.get("status") != "done":
            # Only a result can be large; anything else is an outage.
            self._failed("set", reason)
            with self._lock:
                self._local[task_id] = dict(record)
            return
        logger.error(
            "AI task result too large for the task store: task_id=%s (%s)",
            task_id,
            reason,
        )
        small = {k: v for k, v in record.items() if k not in ("result",)}
        small.update(status="error", error=TOO_LARGE_MESSAGE)
        self._write(task_id, small, expire)

    def _prune_local_locked(self):
        now = time.time()
        stale = [
            tid
            for tid, rec in self._local.items()
            if (rec.get("finished_at") or rec.get("started_at", 0))
            + self.ttl
            + self.max_running
            < now
        ]
        for tid in stale:
            del self._local[tid]

    # -- lifecycle --

    def create(self, owner=None, label=None) -> str:
        if self._shutting_down:
            raise TaskStoreShuttingDown("the task store is shutting down")
        task_id = str(uuid.uuid4())
        started_at = time.time()
        record = {"status": "running", "started_at": started_at}
        if owner:
            record["owner"] = owner
        if label:
            record["label"] = label
        timer = Timer(self.max_running, self._on_timeout, args=(task_id,))
        timer.daemon = True
        timer.name = f"ai-task-timeout-{task_id[:8]}"
        with self._lock:
            self._running[task_id] = {
                "timer": timer,
                "started_at": started_at,
                "label": label,
                "owner": owner,
                "marked": None,
            }
        self._write(task_id, record, self.max_running + EXPIRY_MARGIN)
        timer.start()
        return task_id

    def complete(self, task_id, result):
        self._finish(task_id, {"status": "done", "result": result})

    def fail(self, task_id, error):
        self._finish(task_id, {"status": "error", "error": error})

    def _finish(self, task_id, outcome):
        now = time.time()
        known = self._finishing(task_id)
        if known is None:
            # Unknown here and in the store: same as the in-memory registry,
            # which ignores unknown ids.
            return
        started_at, label, owner, marked = known
        duration = now - (started_at or now)
        if marked:
            self._report_late(task_id, label, owner, duration, marked)
            return
        if duration > self.max_running / 2:
            logger.warning(
                "AI task slow: task_id=%s label=%s duration=%ds limit=%ds",
                task_id,
                label,
                duration,
                self.max_running,
            )
        record = dict(outcome, started_at=started_at, finished_at=now)
        if owner:
            record["owner"] = owner
        if label:
            record["label"] = label
        self._write(task_id, record, self.ttl)

    def _finishing(self, task_id):
        """Return ``(started_at, label, owner, marked)`` for a task being
        finished, or ``None`` when it is unknown. ``marked`` is ``"lost"`` or
        ``"interrupted"`` when the client was already told it failed."""
        with self._lock:
            entry = self._running.pop(task_id, None)
        if entry is not None:
            entry["timer"].cancel()
            marked = entry["marked"]
            if marked is None:
                # Another process may have reported it lost on read.
                current = self._read(task_id)
                if current is not None and current.get("lost"):
                    marked = "lost"
            return entry["started_at"], entry["label"], entry["owner"], marked
        current = self._read(task_id)
        if current is None:
            return None
        return (
            current.get("started_at"),
            current.get("label"),
            current.get("owner"),
            "lost" if current.get("lost") else None,
        )

    def _report_late(self, task_id, label, owner, duration, marked):
        """A result arrived after the client was told the task failed: keep
        the record as it is (the user has seen the failure) and report it."""
        if marked == "interrupted":
            logger.info(
                "AI task finished after being interrupted: task_id=%s "
                "label=%s duration=%ds",
                task_id,
                label,
                duration,
            )
            return
        logger.error(
            "AI task finished after being reported lost: task_id=%s "
            "label=%s duration=%ds",
            task_id,
            label,
            duration,
        )
        notify(TaskLostEvent(task_id, label, owner, duration, late=True))

    def get(self, task_id, owner=None) -> dict | None:
        record = self._read(task_id)
        if record is None:
            return None
        if owner is not None and record.get("owner") and record["owner"] != owner:
            return None
        if record["status"] == "running":
            age = time.time() - record.get("started_at", 0)
            if age > self.max_running:
                record = self._mark_lost(task_id, record, age, "read")
        return _public(record)

    def _lost_record(self, record):
        record = {
            k: v for k, v in record.items() if k in ("started_at", "owner", "label")
        }
        record.update(
            status="error", error=LOST_MESSAGE, lost=True, finished_at=time.time()
        )
        return record

    def _mark_lost(self, task_id, record, age, detected_by):
        lost = self._lost_record(record)
        self._write(task_id, lost, self.ttl)
        logger.error(
            "AI task lost: task_id=%s label=%s age=%ds limit=%ds detected_by=%s",
            task_id,
            record.get("label"),
            age,
            self.max_running,
            detected_by,
        )
        notify(TaskLostEvent(task_id, record.get("label"), record.get("owner"), age))
        return lost

    def _on_timeout(self, task_id):
        with self._lock:
            entry = self._running.get(task_id)
            if entry is None or entry["marked"]:
                return
            entry["marked"] = "lost"
        current = self._read(task_id)
        if current is not None and current.get("status") != "running":
            # Already reported lost on read by another process.
            return
        record = {"started_at": entry["started_at"]}
        if entry["owner"]:
            record["owner"] = entry["owner"]
        if entry["label"]:
            record["label"] = entry["label"]
        self._mark_lost(task_id, record, time.time() - entry["started_at"], "timer")

    def begin_shutdown(self, drain=None):
        """Refuse new tasks, wait up to ``drain`` seconds for this process's
        tasks to finish, then mark the rest interrupted (``retryable``)."""
        self._shutting_down = True
        drain = self.drain if drain is None else drain
        deadline = time.monotonic() + max(drain, 0)
        while time.monotonic() < deadline:
            with self._lock:
                if not any(not e["marked"] for e in self._running.values()):
                    break
            time.sleep(0.1)
        with self._lock:
            pending = [(tid, e) for tid, e in self._running.items() if not e["marked"]]
            for _tid, entry in pending:
                entry["marked"] = "interrupted"
                entry["timer"].cancel()
        now = time.time()
        for task_id, entry in pending:
            record = {
                "status": "error",
                "error": INTERRUPTED_MESSAGE,
                "retryable": True,
                "started_at": entry["started_at"],
                "finished_at": now,
            }
            if entry["owner"]:
                record["owner"] = entry["owner"]
            if entry["label"]:
                record["label"] = entry["label"]
            self._write(task_id, record, self.ttl)
            logger.info(
                "AI task interrupted: task_id=%s label=%s age=%ds",
                task_id,
                entry["label"],
                now - entry["started_at"],
            )


# -- configuration -----------------------------------------------------------

_state = {"configured": False, "store": None}
_state_lock = Lock()


def _float_env(environ, name, default, minimum):
    value = (environ.get(name) or "").strip()
    if not value:
        return default
    try:
        number = float(value)
    except ValueError:
        number = None
    if number is None or number < minimum:
        logger.error(
            "%s=%r is not a number >= %s; using %s", name, value, minimum, default
        )
        return default
    return number


def parse_servers(url):
    """``memcached://h1:11211,h2:11211`` -> ``[("h1", 11211), ...]``.

    Raises ``ValueError`` on anything else."""
    scheme, sep, rest = url.partition("://")
    if not sep or scheme != "memcached":
        raise ValueError("only memcached://host:port is supported")
    servers = []
    for part in rest.split(","):
        part = part.strip().rstrip("/")
        host, sep, port = part.rpartition(":")
        host = host.strip("[]")
        if not sep or not host or not port.isdigit():
            raise ValueError(f"{part!r} is not host:port")
        servers.append((host, int(port)))
    if not servers:
        raise ValueError("no server given")
    return servers


def make_client(servers):
    if len(servers) == 1:
        from pymemcache.client.base import PooledClient

        return PooledClient(
            servers[0], connect_timeout=CONNECT_TIMEOUT, timeout=TIMEOUT
        )
    from pymemcache.client.hash import HashClient

    return HashClient(
        servers,
        use_pooling=True,
        connect_timeout=CONNECT_TIMEOUT,
        timeout=TIMEOUT,
    )


def configure(environ=None):
    """Build the shared store from the environment; ``None`` when off or
    invalid (an invalid value is logged once)."""
    environ = os.environ if environ is None else environ
    url = (environ.get(STORE_ENV) or "").strip()
    if not url:
        return None
    try:
        servers = parse_servers(url)
    except ValueError as exc:
        logger.error(
            "%s=%r is invalid (%s); the shared task store is off", STORE_ENV, url, exc
        )
        return None
    prefix = environ.get(PREFIX_ENV)
    if prefix is None or not prefix.strip():
        prefix = DEFAULT_PREFIX
    if len(prefix) > MAX_PREFIX_LENGTH or any(
        c.isspace() or ord(c) < 32 for c in prefix
    ):
        logger.error(
            "%s=%r must be at most %s characters, without whitespace; "
            "the shared task store is off",
            PREFIX_ENV,
            prefix,
            MAX_PREFIX_LENGTH,
        )
        return None
    try:
        client = make_client(servers)
    except ImportError:
        logger.error(
            "%s is set but pymemcache is not installed (install "
            "collective.aisettings[memcached]); the shared task store "
            "is off",
            STORE_ENV,
        )
        return None
    store = SharedTaskStore(
        client,
        prefix=prefix,
        max_running=_float_env(environ, MAX_RUNNING_ENV, DEFAULT_MAX_RUNNING, 1),
        ttl=_float_env(environ, TTL_ENV, DEFAULT_TTL, 1),
        drain=_float_env(environ, DRAIN_ENV, DEFAULT_DRAIN, 0),
    )
    logger.info("AI task store: memcached %s, prefix %r", url, prefix)
    return store


def _shared() -> SharedTaskStore | None:
    if not _state["configured"]:
        with _state_lock:
            if not _state["configured"]:
                _state["store"] = configure()
                _state["configured"] = True
    return _state["store"]


def reset(store=None):
    """Forget the configuration (tests). With ``store``, use that one."""
    with _state_lock:
        _state["store"] = store
        _state["configured"] = store is not None
    with _LOCK:
        _TASKS.clear()


# -- public API --------------------------------------------------------------


def shared_store_enabled() -> bool:
    """True when ``COLLECTIVE_AISETTINGS_TASK_STORE`` configured a shared
    store; every extra behaviour (owner checks, shutdown, alerts) hangs off
    this."""
    return _shared() is not None


def create_task(owner=None, label=None) -> str:
    """Register a running task and return its id.

    ``owner`` (a user id) and ``label`` (e.g. a capability name) are used by
    the shared store only. Raises :class:`TaskStoreShuttingDown` after
    :func:`begin_shutdown`."""
    store = _shared()
    if store is None:
        return _local_create_task()
    return store.create(owner=owner, label=label)


def complete_task(task_id: str, result) -> None:
    store = _shared()
    if store is None:
        return _local_complete_task(task_id, result)
    store.complete(task_id, result)


def fail_task(task_id: str, error: str) -> None:
    store = _shared()
    if store is None:
        return _local_fail_task(task_id, error)
    store.fail(task_id, error)


def get_task(task_id: str, owner=None) -> dict | None:
    """Return the task's public record, or ``None``.

    With the shared store, a task created with an owner is only returned to
    that owner (or to a caller passing no owner)."""
    store = _shared()
    if store is None:
        return _local_get_task(task_id)
    return store.get(task_id, owner=owner)


def begin_shutdown(drain=None) -> None:
    """Call from the process's shutdown hook. No-op without the shared store.

    Refuses new tasks, waits up to ``drain`` seconds
    (``COLLECTIVE_AISETTINGS_TASK_DRAIN`` when ``None``) for this process's
    tasks, and marks the rest ``error`` with ``retryable: true`` so clients
    retry elsewhere. Installs no signal handler: that is the deployment's
    call."""
    store = _shared()
    if store is not None:
        store.begin_shutdown(drain)
