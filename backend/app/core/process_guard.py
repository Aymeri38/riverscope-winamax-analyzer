from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections.abc import Callable, Iterable
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


WINAMAX_EXECUTABLE = "Winamax.exe"
SAFETY_EXIT_CODE = 23
DEFAULT_POLL_INTERVAL_SECONDS = 0.25


class ProcessInspectionError(RuntimeError):
    """Raised when the process-name list cannot be inspected safely."""


class AnalysisForbiddenError(RuntimeError):
    """Raised after the irreversible, process-local safety latch has tripped."""


class ProcessProbe(Protocol):
    def __call__(self) -> bool: ...


class AnalysisInterlock:
    """One-way latch shared by the API, watcher and importer.

    There is deliberately no public reset operation. Once tripped, the current
    analyzer process must terminate; a later manual launch performs a new
    process-name preflight.
    """

    def __init__(self) -> None:
        self._blocked = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None
        self._tripped_at: datetime | None = None

    @property
    def blocked(self) -> bool:
        return self._blocked.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    @property
    def tripped_at(self) -> datetime | None:
        with self._lock:
            return self._tripped_at

    def trip(self, reason: str) -> bool:
        """Trip the latch once and return whether this call was the first."""
        with self._lock:
            if self._blocked.is_set():
                return False
            self._reason = reason
            self._tripped_at = datetime.now(UTC)
            self._blocked.set()
            return True

    def ensure_allowed(self) -> None:
        if self._blocked.is_set():
            raise AnalysisForbiddenError(
                self.reason or "Analyse interdite par le verrou de sécurité."
            )


analysis_interlock = AnalysisInterlock()


def _windows_process_names() -> tuple[str, ...]:
    """Return executable names from Toolhelp32 without opening any process.

    This enumerates only the process image names. It never requests a process
    handle and never reads process memory, windows, command lines or modules.
    """
    if os.name != "nt":
        raise ProcessInspectionError("La vérification de processus exige Windows.")

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot_processes = 0x00000002
    error_no_more_files = 18
    invalid_handle_value = ctypes.c_void_p(-1).value

    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_snapshot(snapshot_processes, 0)
    if handle in (None, 0, invalid_handle_value):
        raise ProcessInspectionError("Impossible d'énumérer les noms de processus.")

    names: list[str] = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ctypes.set_last_error(0)
        if not process_first(handle, ctypes.byref(entry)):
            error = ctypes.get_last_error()
            if error == error_no_more_files:
                return ()
            raise ProcessInspectionError("Impossible de lire la liste des processus.")
        while True:
            names.append(str(entry.szExeFile))
            ctypes.set_last_error(0)
            if not process_next(handle, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error not in (0, error_no_more_files):
                    raise ProcessInspectionError("Énumération des processus interrompue.")
                break
    finally:
        close_handle(handle)
    return tuple(names)


def _linux_process_names(proc_root: Path = Path("/proc")) -> tuple[str, ...]:
    """Return Linux process names by reading only ``/proc/<pid>/comm``.

    ``comm`` exposes the kernel task name and is sufficient for an exact
    ``Winamax.exe`` comparison (including a Wine-hosted executable).  This
    deliberately avoids process memory, command lines, environment variables,
    open files and network state.  The probe fails closed when procfs itself
    cannot be trusted; processes which disappear during enumeration are simply
    skipped.
    """
    if not sys.platform.startswith("linux"):
        raise ProcessInspectionError("La verification /proc exige Linux.")

    root = proc_root.expanduser()
    try:
        if not root.is_dir():
            raise ProcessInspectionError("Le systeme /proc est indisponible.")
        # Our own entry proves procfs is mounted. PID 1 proves that process
        # names outside the current user are visible; hidepid/ProtectProc
        # configurations would otherwise create a dangerous false negative.
        for required_pid in (os.getpid(), 1):
            (root / str(required_pid) / "comm").read_text(
                encoding="utf-8", errors="replace"
            )
        entries = tuple(root.iterdir())
    except ProcessInspectionError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ProcessInspectionError(
            "Impossible de verifier les noms de processus via /proc."
        ) from exc

    names: list[str] = []
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            name = (entry / "comm").read_text(
                encoding="utf-8", errors="replace"
            ).rstrip("\r\n")
        except FileNotFoundError:
            # A process can exit between listing /proc and reading its name.
            continue
        except OSError as exc:
            raise ProcessInspectionError(
                "Enumeration des processus Linux interrompue."
            ) from exc
        names.append(name)
    return tuple(names)


def _platform_process_names() -> tuple[str, ...]:
    if os.name == "nt":
        return _windows_process_names()
    if sys.platform.startswith("linux"):
        return _linux_process_names()
    raise ProcessInspectionError(
        "La verification de Winamax.exe n'est pas disponible sur cette plateforme."
    )


def is_winamax_running(
    process_names_provider: Callable[[], Iterable[str]] | None = None,
) -> bool:
    provider = process_names_provider or _platform_process_names
    try:
        names = provider()
        return any(str(name).casefold() == WINAMAX_EXECUTABLE.casefold() for name in names)
    except ProcessInspectionError:
        raise
    except Exception as exc:
        raise ProcessInspectionError("Impossible de vérifier Winamax.exe.") from exc


def require_winamax_absent(
    detector: ProcessProbe | None = None,
    interlock: AnalysisInterlock | None = None,
) -> None:
    latch = interlock or analysis_interlock
    latch.ensure_allowed()
    probe = detector or is_winamax_running
    try:
        running = bool(probe())
    except Exception as exc:
        reason = (
            "Analyse interdite : la présence de Winamax.exe n'a pas pu être vérifiée."
        )
        latch.trip(reason)
        raise AnalysisForbiddenError(reason) from exc
    if running:
        reason = "Analyse interdite : Winamax.exe est en cours d'exécution."
        latch.trip(reason)
        raise AnalysisForbiddenError(reason)
    latch.ensure_allowed()


class ProcessGuardMonitor:
    """Continuously trips the shared latch if Winamax appears or probing fails."""

    def __init__(
        self,
        on_trip: Callable[[str], None] | None = None,
        detector: ProcessProbe | None = None,
        interlock: AnalysisInterlock | None = None,
        interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._on_trip = on_trip
        self._detector = detector or is_winamax_running
        self._interlock = interlock or analysis_interlock
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._callback_sent = False

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._stop.is_set():
                raise RuntimeError("A stopped process guard monitor cannot be restarted")
        if not self.check_now():
            self._interlock.ensure_allowed()
        thread = threading.Thread(
            target=self._run,
            name="winamax-process-guard",
            daemon=True,
        )
        with self._state_lock:
            self._thread = thread
        thread.start()

    def check_now(self) -> bool:
        if self._interlock.blocked:
            self._notify_once(
                self._interlock.reason or "Analyse interdite par le verrou de sécurité."
            )
            return False
        try:
            running = bool(self._detector())
        except Exception:
            reason = (
                "Arrêt de sécurité : la présence de Winamax.exe n'a pas pu être vérifiée."
            )
            self._interlock.trip(reason)
            self._notify_once(reason)
            return False
        if running:
            reason = "Arrêt de sécurité : Winamax.exe a été détecté."
            self._interlock.trip(reason)
            self._notify_once(reason)
            return False
        return True

    def _notify_once(self, reason: str) -> None:
        callback: Callable[[str], None] | None = None
        with self._state_lock:
            if not self._callback_sent:
                self._callback_sent = True
                callback = self._on_trip
        if callback is not None:
            callback(reason)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            if not self.check_now():
                return

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))
