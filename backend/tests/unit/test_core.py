from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from the_frame_v2.auth.middleware import _host_without_port
from the_frame_v2.auth.ratelimit import RateLimiter
from the_frame_v2.config import load_settings
from the_frame_v2.db.migrate import upgrade_to_head
from the_frame_v2.db.models import Job
from the_frame_v2.db.session import Database
from the_frame_v2.events import EventBroker
from the_frame_v2.ids import new_human_code, new_id, normalize_human_code
from the_frame_v2.jobs.queue import JobContext, JobQueue, PermanentJobError
from the_frame_v2.services.geocode import Geocoder


def test_ids_are_uuid7_and_sortable() -> None:
    a, b = new_id(), new_id()
    assert a[14] == "7" and a < b


def test_human_codes_normalize() -> None:
    code = new_human_code()
    assert len(code) == 11 and code[5] == "-"
    assert normalize_human_code(code.lower().replace("-", " ")) == code
    assert normalize_human_code("oil00-abcde") == "01100-ABCDE"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost:8765", "localhost"),
        ("[::1]:80", "[::1]"),
        ("Example.COM", "example.com"),
        ("::1", "::1"),
    ],
)
def test_host_without_port(host: str, expected: str) -> None:
    assert _host_without_port(host) == expected


def test_rate_limiter_windows() -> None:
    limiter = RateLimiter([(2, 10.0), (3, 100.0)])
    assert limiter.hit("ip", 0) and limiter.hit("ip", 1)
    assert not limiter.hit("ip", 2)
    assert limiter.hit("ip", 12)
    assert not limiter.hit("ip", 50)  # hourly-style second limit reached
    assert limiter.hit("other", 50)


def test_settings_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config.toml").write_text('port = 9000\npublic_url = "http://frame.lan:9000"\n')
    monkeypatch.setenv("THE_FRAME_V2_PORT", "9100")
    s = load_settings(data_dir=tmp_path)
    assert s.port == 9100 and s.effective_public_url == "http://frame.lan:9000"
    assert load_settings(data_dir=tmp_path, port=9200).port == 9200
    assert "frame.lan" in (s.allowed_host_set() or set())
    assert load_settings(data_dir=tmp_path, allowed_hosts=["*"]).allowed_host_set() is None


def test_geocoder_nearest_place() -> None:
    geo = Geocoder()
    lyon = geo.reverse(45.7640, 4.8357)
    assert lyon is not None and lyon.name == "Lyon" and lyon.country == "France"
    assert geo.reverse(0.0, -140.0) is None  # middle of the Pacific
    north = geo.reverse(78.2232, 15.6267)  # Longyearbyen, high latitude
    assert north is not None and north.country in ("Svalbard and Jan Mayen", "Norway")


@pytest.fixture
def queue(tmp_path: Path) -> JobQueue:
    db = Database(tmp_path / "q.db")
    upgrade_to_head(db.engine)
    return JobQueue(db, EventBroker(), lanes={"a": 1, "b": 1})


def test_job_queue_retry_and_permanent_failure(queue: JobQueue) -> None:
    calls: dict[str, int] = {"flaky": 0}

    def flaky(ctx: JobContext) -> None:
        calls["flaky"] += 1
        if calls["flaky"] < 2:
            raise RuntimeError("transient")

    def broken(ctx: JobContext) -> None:
        raise PermanentJobError("bad_input", "nope")

    queue.register("flaky", flaky, lane="a")
    queue.register("broken", broken, lane="b")
    flaky_id = queue.enqueue("flaky", {})
    broken_id = queue.enqueue("broken", {})
    queue.run_pending_sync()
    with queue._db.session() as s:
        assert s.get(Job, flaky_id).state == "done"  # type: ignore[union-attr]
        job = s.get(Job, broken_id)
        assert job is not None and job.state == "failed" and job.attempts == 1
        assert job.error == "bad_input: nope"


def test_job_queue_coalesces(queue: JobQueue) -> None:
    seen: list[Any] = []
    queue.register("render", lambda ctx: seen.append(ctx.payload["v"]), lane="a")
    queue.enqueue("render", {"v": 1}, coalesce_key="render:x")
    queue.enqueue("render", {"v": 2}, coalesce_key="render:x")
    queue.run_pending_sync()
    assert seen == [2]


def test_job_queue_threads_and_crash_recovery(queue: JobQueue) -> None:
    done = threading.Event()
    queue.register("ping", lambda ctx: done.set(), lane="a")
    with queue._db.session() as s:
        s.add(Job(kind="ping", lane="a", state="running"))  # left over by a crash
    queue.start()
    try:
        assert done.wait(5)
    finally:
        queue.stop()
