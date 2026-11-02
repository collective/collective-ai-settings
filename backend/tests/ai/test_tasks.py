"""Tests for the async task registry (in-memory and shared memcached store).

The shared store is exercised against pymemcache's ``MockMemcacheClient``;
two :class:`SharedTaskStore` instances on one client stand in for two
processes behind a load balancer.
"""

from collective.aisettings.services import tasks
from collective.aisettings.services.task_status import AITaskStatus
from plone import api
from plone.app.testing import TEST_USER_ID
from plone.app.testing import TEST_USER_NAME
from pymemcache.exceptions import MemcacheServerError
from pymemcache.test.utils import MockMemcacheClient

import json
import logging
import pytest
import time
import uuid


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in (
        tasks.STORE_ENV,
        tasks.PREFIX_ENV,
        tasks.MAX_RUNNING_ENV,
        tasks.TTL_ENV,
        tasks.DRAIN_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    tasks.reset()
    yield
    tasks.reset()


@pytest.fixture()
def events(monkeypatch):
    fired = []
    monkeypatch.setattr(tasks, "notify", fired.append)
    return fired


def make_store(client=None, **kw):
    return tasks.SharedTaskStore(client or MockMemcacheClient(), **kw)


def use(store):
    tasks.reset(store)
    return store


class BrokenClient:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kw):
        self.calls += 1
        raise ConnectionRefusedError("down")

    set = get


class TestOff:
    """Without COLLECTIVE_AISETTINGS_TASK_STORE nothing changes."""

    def test_disabled(self):
        assert tasks.shared_store_enabled() is False

    def test_lifecycle(self):
        tid = tasks.create_task(owner="jdoe", label="chat")
        assert tasks.get_task(tid)["status"] == "running"
        tasks.complete_task(tid, {"reply": "hi"})
        task = tasks.get_task(tid, owner="someone-else")
        assert task["status"] == "done"
        assert task["result"] == {"reply": "hi"}
        assert set(task) == {"status", "result", "started_at", "finished_at"}

    def test_fail(self):
        tid = tasks.create_task()
        tasks.fail_task(tid, "boom")
        assert tasks.get_task(tid)["error"] == "boom"

    def test_unknown_is_ignored(self):
        tasks.complete_task("nope", {})
        assert tasks.get_task("nope") is None

    def test_prune(self, monkeypatch):
        tid = tasks.create_task()
        tasks.complete_task(tid, {})
        tasks._TASKS[tid]["finished_at"] = time.time() - tasks._FINISHED_TTL_SECONDS - 1
        assert tasks.get_task(tid) is None

    def test_no_timer_thread(self, monkeypatch):
        started = []
        monkeypatch.setattr(tasks.Timer, "start", lambda self: started.append(self))
        tasks.create_task()
        assert started == []

    def test_shutdown_is_noop(self):
        tasks.begin_shutdown()
        assert tasks.get_task(tasks.create_task())["status"] == "running"


class TestConfigure:
    def test_unset(self):
        assert tasks.configure({}) is None

    @pytest.mark.parametrize(
        "url",
        [
            "redis://h:6379",
            "memcached://",
            "memcached://host",
            "memcached://h:x",
            "h:1",
        ],
    )
    def test_invalid_is_off(self, url, caplog):
        with caplog.at_level(logging.ERROR):
            assert tasks.configure({tasks.STORE_ENV: url}) is None
        assert tasks.STORE_ENV in caplog.text

    def test_parse_servers(self):
        assert tasks.parse_servers("memcached://a:1, b:2") == [("a", 1), ("b", 2)]
        assert tasks.parse_servers("memcached://[::1]:11211") == [("::1", 11211)]

    def test_single_server(self):
        store = tasks.configure({tasks.STORE_ENV: "memcached://localhost:11211"})
        assert type(store.client).__name__ == "PooledClient"
        assert store.prefix == tasks.DEFAULT_PREFIX
        assert store.max_running == 900
        assert store.ttl == 1800
        assert store.drain == 0

    def test_several_servers(self):
        store = tasks.configure({tasks.STORE_ENV: "memcached://a:1,b:2"})
        assert type(store.client).__name__ == "HashClient"

    def test_settings(self):
        store = tasks.configure({
            tasks.STORE_ENV: "memcached://localhost:11211",
            tasks.PREFIX_ENV: "site1:aitask:",
            tasks.MAX_RUNNING_ENV: "60",
            tasks.TTL_ENV: "120",
            tasks.DRAIN_ENV: "5",
        })
        assert (store.prefix, store.max_running, store.ttl, store.drain) == (
            "site1:aitask:",
            60,
            120,
            5,
        )

    def test_bad_number_uses_default(self, caplog):
        store = tasks.configure({
            tasks.STORE_ENV: "memcached://localhost:11211",
            tasks.MAX_RUNNING_ENV: "soon",
        })
        assert store.max_running == tasks.DEFAULT_MAX_RUNNING

    def test_bad_prefix_is_off(self):
        assert (
            tasks.configure({
                tasks.STORE_ENV: "memcached://localhost:11211",
                tasks.PREFIX_ENV: "my site",
            })
            is None
        )

    def test_pymemcache_missing(self, monkeypatch, caplog):
        def missing(servers):
            raise ImportError("pymemcache")

        monkeypatch.setattr(tasks, "make_client", missing)
        with caplog.at_level(logging.ERROR):
            assert tasks.configure({tasks.STORE_ENV: "memcached://h:1"}) is None
        assert "pymemcache" in caplog.text

    def test_enabled_from_environment(self, monkeypatch):
        monkeypatch.setenv(tasks.STORE_ENV, "memcached://localhost:11211")
        tasks.reset()
        assert tasks.shared_store_enabled() is True


class TestShared:
    def test_two_processes(self):
        """The regression test: created on one, polled on another."""
        client = MockMemcacheClient()
        one, two = make_store(client), make_store(client)
        tid = one.create()
        assert two.get(tid)["status"] == "running"
        one.complete(tid, {"reply": "hi"})
        task = two.get(tid)
        assert task["status"] == "done"
        assert task["result"] == {"reply": "hi"}

    def test_module_api(self):
        use(make_store())
        tid = tasks.create_task(owner="jdoe", label="assistant")
        tasks.fail_task(tid, "boom")
        task = tasks.get_task(tid, owner="jdoe")
        assert task["status"] == "error"
        assert task["error"] == "boom"
        assert "owner" not in task and "label" not in task

    def test_prefix_and_expiry(self, monkeypatch):
        client = MockMemcacheClient()
        calls = []
        real_set = client.set

        def spy(key, value, expire=0, noreply=True, flags=None):
            calls.append((key, expire, noreply))
            return real_set(key, value, expire, noreply, flags)

        monkeypatch.setattr(client, "set", spy)
        store = make_store(client, prefix="s1:", max_running=100, ttl=200)
        tid = store.create()
        store.complete(tid, {})
        assert calls == [(f"s1:{tid}", 160, False), (f"s1:{tid}", 200, False)]
        assert json.loads(client.get(f"s1:{tid}"))["status"] == "done"

    def test_prefixes_do_not_mix(self):
        client = MockMemcacheClient()
        tid = make_store(client, prefix="a:").create()
        assert make_store(client, prefix="b:").get(tid) is None

    def test_owner(self):
        store = make_store()
        tid = store.create(owner="jdoe")
        assert store.get(tid, owner="jdoe")["status"] == "running"
        assert store.get(tid, owner="intruder") is None
        assert store.get(tid)["status"] == "running"
        anonymous = store.create()
        assert store.get(anonymous, owner="anyone")["status"] == "running"


class TestLost:
    def test_read_rule(self, events, caplog):
        client = MockMemcacheClient()
        store = make_store(client, max_running=100)
        tid = str(uuid.uuid4())
        client.set(
            f"{store.prefix}{tid}",
            json.dumps({
                "status": "running",
                "started_at": time.time() - 101,
                "label": "assistant",
            }).encode(),
        )
        with caplog.at_level(logging.ERROR):
            task = store.get(tid)
            again = store.get(tid)
        assert task["status"] == "error"
        assert task["error"] == tasks.LOST_MESSAGE
        assert "lost" not in task
        assert again["status"] == "error"
        assert caplog.text.count("AI task lost") == 1
        assert "detected_by=read" in caplog.text
        assert len(events) == 1
        assert events[0].task_id == tid
        assert events[0].label == "assistant"
        assert events[0].late is False

    def test_timer(self, events, caplog):
        store = make_store(max_running=0.2)
        tid = store.create(label="assistant")
        time.sleep(0.5)
        with caplog.at_level(logging.ERROR):
            assert store.get(tid)["status"] == "error"
        assert len(events) == 1
        assert store._running[tid]["marked"] == "lost"

    def test_late_completion(self, events, caplog):
        store = make_store(max_running=0.2)
        tid = store.create()
        time.sleep(0.5)
        with caplog.at_level(logging.ERROR):
            store.complete(tid, {"reply": "too late"})
        assert "finished after being reported lost" in caplog.text
        assert store.get(tid)["status"] == "error"
        assert [e.late for e in events] == [False, True]

    def test_late_after_another_process_reported_it(self, events, caplog):
        client = MockMemcacheClient()
        one = make_store(client, max_running=100)
        two = make_store(client, max_running=100)
        tid = one.create()
        key = f"{one.prefix}{tid}"
        record = json.loads(client.get(key))
        record["started_at"] -= 101
        client.set(key, json.dumps(record).encode())
        assert two.get(tid)["status"] == "error"
        with caplog.at_level(logging.ERROR):
            one.complete(tid, {"reply": "late"})
        assert "finished after being reported lost" in caplog.text
        assert one.get(tid)["status"] == "error"

    def test_slow_warning(self, caplog):
        store = make_store(max_running=100)
        tid = store.create(label="assistant")
        store._running[tid]["started_at"] -= 60
        with caplog.at_level(logging.WARNING):
            store.complete(tid, {})
        assert "AI task slow" in caplog.text
        assert store.get(tid)["status"] == "done"

    def test_fast_is_quiet(self, caplog):
        store = make_store(max_running=100)
        tid = store.create()
        with caplog.at_level(logging.WARNING):
            store.complete(tid, {})
        assert "AI task" not in caplog.text


class TestShutdown:
    def test_marks_running_retryable(self, events):
        store = use(make_store())
        tid = tasks.create_task()
        tasks.begin_shutdown()
        task = tasks.get_task(tid)
        assert task["status"] == "error"
        assert task["retryable"] is True
        assert events == []
        with pytest.raises(tasks.TaskStoreShuttingDown):
            tasks.create_task()
        # A late result does not overwrite what the client already saw.
        tasks.complete_task(tid, {"reply": "late"})
        assert tasks.get_task(tid)["retryable"] is True
        assert store._running == {}

    def test_drain_waits(self):
        import threading

        store = make_store()
        quick = store.create()
        slow = store.create()
        threading.Timer(0.2, store.complete, args=(quick, {"reply": "ok"})).start()
        started = time.monotonic()
        store.begin_shutdown(drain=0.6)
        assert time.monotonic() - started >= 0.5
        assert store.get(quick)["status"] == "done"
        assert store.get(slow)["retryable"] is True

    def test_drain_returns_early(self):
        store = make_store()
        started = time.monotonic()
        store.begin_shutdown(drain=5)
        assert time.monotonic() - started < 1

    def test_idempotent(self):
        store = make_store()
        tid = store.create()
        store.begin_shutdown()
        store.begin_shutdown()
        assert store.get(tid)["retryable"] is True


class TestFailures:
    def test_falls_back_locally(self, caplog):
        client = BrokenClient()
        store = make_store(client)
        with caplog.at_level(logging.WARNING):
            tid = store.create()
            store.complete(tid, {"reply": "hi"})
            assert store.get(tid)["status"] == "done"
        assert caplog.text.count("using the local store") == 1
        # The breaker skipped memcached after the first failure.
        assert client.calls == 1

    def test_recovers(self, monkeypatch):
        client = MockMemcacheClient()
        store = make_store(client)
        store._down_until = time.monotonic() - 1
        tid = store.create()
        assert client.get(f"{store.prefix}{tid}") is not None

    def test_too_large(self, monkeypatch, caplog):
        client = MockMemcacheClient()
        real_set = client.set

        def picky(key, value, expire=0, noreply=True, flags=None):
            if len(value) > 200:
                raise MemcacheServerError("object too large for cache")
            return real_set(key, value, expire, noreply, flags)

        monkeypatch.setattr(client, "set", picky)
        store = make_store(client)
        tid = store.create()
        with caplog.at_level(logging.ERROR):
            store.complete(tid, {"reply": "x" * 1000})
        task = store.get(tid)
        assert task["status"] == "error"
        assert task["error"] == tasks.TOO_LARGE_MESSAGE
        assert "too large" in caplog.text
        assert store._available()


def _status(portal, request, task_id):
    endpoint = AITaskStatus.__new__(AITaskStatus)
    endpoint.context = portal
    endpoint.request = request
    endpoint.params = [task_id]
    return endpoint.reply()


class TestStatusEndpoint:
    def test_no_store(self, portal, http_request):
        _status(portal, http_request, "nope")
        assert http_request.response.getStatus() == 404
        assert http_request.response.getHeader("Cache-Control") == "no-store"

    def test_owner_checked(self, portal, http_request):
        use(make_store())
        theirs = tasks.create_task(owner="someone-else")
        mine = tasks.create_task(owner=TEST_USER_ID)
        with api.env.adopt_user(username=TEST_USER_NAME):
            assert _status(portal, http_request, theirs) == {"error": "task not found"}
            assert _status(portal, http_request, mine)["status"] == "running"
