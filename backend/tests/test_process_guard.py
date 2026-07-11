from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

import pytest

import app.main as main_module
from app.core.process_guard import (
    AnalysisForbiddenError,
    AnalysisInterlock,
    ProcessGuardMonitor,
    ProcessInspectionError,
    _linux_process_names,
    is_winamax_running,
    require_winamax_absent,
)
from app.workers.history_watcher import HistoryWatcher


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ([], False),
        (["Winamax.exe"], True),
        (["WINAMAX.EXE"], True),
        (["WinamaxUpdater.exe", "mywinamax.exe"], False),
        (["explorer.exe", "Winamax.exe", "python.exe"], True),
    ],
)
def test_exact_process_name_detection(names: list[str], expected: bool) -> None:
    assert is_winamax_running(lambda: names) is expected


def _write_linux_comm(proc_root: Path, pid: int, name: str) -> None:
    process_dir = proc_root / str(pid)
    process_dir.mkdir(parents=True)
    (process_dir / "comm").write_text(name + "\n", encoding="utf-8")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_linux_probe_reads_only_comm_names(tmp_path: Path) -> None:
    _write_linux_comm(tmp_path, os.getpid(), "pytest")
    _write_linux_comm(tmp_path, 1, "systemd")
    _write_linux_comm(tmp_path, 42001, "Winamax.exe")
    (tmp_path / "not-a-process").mkdir()

    assert set(_linux_process_names(tmp_path)) == {
        "systemd",
        "pytest",
        "Winamax.exe",
    }
    assert is_winamax_running(lambda: _linux_process_names(tmp_path)) is True


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_linux_probe_fails_closed_when_own_comm_is_missing(tmp_path: Path) -> None:
    _write_linux_comm(tmp_path, 1, "systemd")
    _write_linux_comm(tmp_path, 42001, "python3")
    with pytest.raises(ProcessInspectionError):
        _linux_process_names(tmp_path)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_linux_probe_fails_closed_when_other_users_are_hidden(tmp_path: Path) -> None:
    _write_linux_comm(tmp_path, os.getpid(), "pytest")
    with pytest.raises(ProcessInspectionError):
        _linux_process_names(tmp_path)


def test_process_probe_failure_is_explicit_and_fail_closed() -> None:
    def broken_names():
        raise OSError("synthetic enumeration failure")

    with pytest.raises(ProcessInspectionError):
        is_winamax_running(broken_names)

    interlock = AnalysisInterlock()
    with pytest.raises(AnalysisForbiddenError):
        require_winamax_absent(detector=lambda: (_ for _ in ()).throw(OSError()), interlock=interlock)
    assert interlock.blocked is True
    with pytest.raises(AnalysisForbiddenError):
        interlock.ensure_allowed()


def test_startup_refusal_latches_once() -> None:
    interlock = AnalysisInterlock()
    with pytest.raises(AnalysisForbiddenError, match="Winamax.exe"):
        require_winamax_absent(detector=lambda: True, interlock=interlock)
    first_reason = interlock.reason
    assert interlock.trip("must not replace the original reason") is False
    assert interlock.reason == first_reason
    with pytest.raises(AnalysisForbiddenError):
        require_winamax_absent(detector=lambda: False, interlock=interlock)


def test_runtime_monitor_trips_and_notifies_once() -> None:
    interlock = AnalysisInterlock()
    detected = threading.Event()
    state = {"running": False, "callbacks": 0}

    def detector() -> bool:
        return state["running"]

    def on_trip(_reason: str) -> None:
        state["callbacks"] += 1
        detected.set()

    monitor = ProcessGuardMonitor(
        detector=detector,
        interlock=interlock,
        on_trip=on_trip,
        interval_seconds=0.01,
    )
    monitor.start()
    assert monitor.is_running is True
    state["running"] = True
    assert detected.wait(timeout=1.0)
    assert interlock.blocked is True
    assert state["callbacks"] == 1
    assert monitor.check_now() is False
    assert state["callbacks"] == 1
    monitor.stop()
    monitor.stop()


def test_lifespan_refuses_before_database_or_watcher(monkeypatch) -> None:
    calls: list[str] = []

    def refuse(*_args, **_kwargs) -> None:
        calls.append("preflight")
        raise AnalysisForbiddenError("synthetic Winamax detection")

    monkeypatch.setattr(main_module, "require_winamax_absent", refuse)
    monkeypatch.setattr(main_module, "initialize_database", lambda: calls.append("database"))

    class ForbiddenWatcher:
        def __init__(self) -> None:
            calls.append("watcher")

    monkeypatch.setattr(main_module, "HistoryWatcher", ForbiddenWatcher)

    async def attempt_startup() -> None:
        async with main_module.lifespan(main_module.app):
            raise AssertionError("lifespan must not yield")

    with pytest.raises(AnalysisForbiddenError):
        asyncio.run(attempt_startup())
    assert calls == ["preflight"]


def test_lifespan_runtime_detection_requests_backend_shutdown(monkeypatch) -> None:
    interlock = AnalysisInterlock()
    running = threading.Event()
    shutdown_requested = threading.Event()
    reasons: list[str] = []

    monkeypatch.setattr(main_module.app.state, "process_probe", running.is_set)
    monkeypatch.setattr(main_module.app.state, "analysis_interlock", interlock)

    def request_shutdown(reason: str) -> None:
        reasons.append(reason)
        shutdown_requested.set()

    monkeypatch.setattr(
        main_module.app.state, "request_backend_shutdown", request_shutdown
    )

    async def exercise_runtime_guard() -> None:
        async with main_module.lifespan(main_module.app):
            running.set()
            observed = await asyncio.to_thread(shutdown_requested.wait, 2.0)
            assert observed is True

    asyncio.run(exercise_runtime_guard())
    assert interlock.blocked is True
    assert len(reasons) == 1
    assert "Winamax.exe" in reasons[0]


def test_watcher_stop_is_idempotent_and_never_joins_itself() -> None:
    watcher = HistoryWatcher()
    watcher._thread = threading.current_thread()  # type: ignore[attr-defined]
    watcher.request_stop()
    watcher.stop(timeout=0)
    watcher.stop(timeout=0)
    assert watcher.is_running is False
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        watcher.start()
