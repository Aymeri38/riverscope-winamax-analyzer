from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.core.process_guard import AnalysisForbiddenError, analysis_interlock
from app.database import SessionLocal
from app.services.importer import rescan_all
from app.services.community_client import CommunityClient, sync_community_after_rescan
from app.services.settings import load_settings


logger = logging.getLogger("winamax_analyzer.watcher")


class _HistoryEventHandler(FileSystemEventHandler):
    def __init__(self, wake_event: threading.Event) -> None:
        super().__init__()
        self.wake_event = wake_event

    def on_created(self, event: FileSystemEvent) -> None:
        self._maybe_wake(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._maybe_wake(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._maybe_wake(event)

    def _maybe_wake(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = str(getattr(event, "dest_path", None) or event.src_path)
        name = Path(path).name.casefold()
        if name.endswith(".txt") and "expresso" in name:
            self.wake_event.set()


class HistoryWatcher:
    """watchdog-backed rescanner; it only observes configured history directories."""

    def __init__(self, community_client: CommunityClient | None = None) -> None:
        self._observer = Observer()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._scheduled: set[str] = set()
        self._start_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._observer_started = False
        self._observer_stop_requested = False
        self._community_client = community_client
        self._last_community_sync = 0.0

    def start(self) -> None:
        with self._start_lock:
            analysis_interlock.ensure_allowed()
            if self._stop.is_set():
                raise RuntimeError("A stopped history watcher cannot be restarted")
            if self._thread is not None and self._thread.is_alive():
                return

            with SessionLocal() as db:
                settings = load_settings(db)
            handler = _HistoryEventHandler(self._wake)
            for configured in settings.history_paths:
                analysis_interlock.ensure_allowed()
                path = Path(configured)
                if not path.is_dir():
                    continue
                resolved = str(path.resolve())
                if resolved in self._scheduled:
                    continue
                self._observer.schedule(handler, resolved, recursive=False)
                self._scheduled.add(resolved)

            analysis_interlock.ensure_allowed()
            if self._scheduled:
                self._observer.start()
                self._observer_started = True
            try:
                analysis_interlock.ensure_allowed()
            except AnalysisForbiddenError:
                self.stop()
                raise

            self._thread = threading.Thread(target=self._run, name="history-import-worker", daemon=True)
            self._thread.start()
            self._wake.set()  # initial import of already completed files
            logger.info("Surveillance locale démarrée pour %d dossier(s)", len(self._scheduled))

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(
            thread is not None
            and thread.is_alive()
            and not self._stop.is_set()
            and not analysis_interlock.blocked
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            # Periodic scan covers changed settings and filesystem event loss.
            self._wake.wait(timeout=30)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                analysis_interlock.ensure_allowed()
                with SessionLocal() as db:
                    settings = load_settings(db)
                    analysis_interlock.ensure_allowed()
                    outcome = rescan_all(db, settings)
                    now_monotonic = time.monotonic()
                    if (
                        self._community_client is not None
                        and now_monotonic - self._last_community_sync
                        >= settings.community_sync_interval_seconds
                    ):
                        sync_community_after_rescan(db, self._community_client)
                        self._last_community_sync = now_monotonic
                    if outcome.imported or outcome.failed:
                        logger.info(
                            "Import post-session: %d importé(s), %d en attente, %d échec(s)",
                            outcome.imported,
                            outcome.waiting,
                            outcome.failed,
                        )
            except AnalysisForbiddenError:
                logger.critical("Watcher arrêté par le verrou de sécurité; aucun nouvel import ne sera lancé.")
                self.stop()
                break
            except Exception as exc:  # service must keep running after a file error
                logger.error("Le rescannage local a échoué sans arrêter le service: %s", type(exc).__name__)

    def request_stop(self) -> None:
        """Signal every watcher component without waiting for thread termination."""
        with self._stop_lock:
            self._stop.set()
            self._wake.set()
            stop_observer = self._observer_started and not self._observer_stop_requested
            if stop_observer:
                self._observer_stop_requested = True

        if stop_observer:
            try:
                self._observer.stop()
            except Exception as exc:
                logger.error("Signal d'arrêt de l'observer incomplet: %s", type(exc).__name__)

    def stop(self, timeout: float = 1.0) -> None:
        """Request shutdown and perform bounded, self-join-safe cleanup."""
        self.request_stop()
        deadline = time.monotonic() + max(0.0, timeout)
        current = threading.current_thread()

        try:
            if self._observer_started and self._observer is not current and self._observer.is_alive():
                self._observer.join(timeout=max(0.0, deadline - time.monotonic()))
        except Exception as exc:
            logger.error("Arrêt de l'observer incomplet: %s", type(exc).__name__)

        thread = self._thread
        if thread is not None and thread is not current and thread.is_alive():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
