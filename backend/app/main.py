from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.router import router
from app.core.config import config
from app.core.process_guard import (
    AnalysisForbiddenError,
    AnalysisInterlock,
    ProcessGuardMonitor,
    ProcessProbe,
    analysis_interlock,
    is_winamax_running,
    require_winamax_absent,
)
from app.database import initialize_database
from app.workers.history_watcher import HistoryWatcher


logging.basicConfig(
    level=os.environ.get("WXA_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher: HistoryWatcher | None = None
    monitor: ProcessGuardMonitor | None = None
    app.state.history_watcher = None
    app.state.process_guard_monitor = None
    loop = asyncio.get_running_loop()
    detector: ProcessProbe = getattr(app.state, "process_probe", is_winamax_running)
    interlock: AnalysisInterlock = getattr(
        app.state, "analysis_interlock", analysis_interlock
    )

    def stop_application(reason: str) -> None:
        current_watcher = watcher
        try:
            if current_watcher is not None:
                current_watcher.request_stop()
        finally:
            try:
                shutdown: Callable[[str], None] | None = getattr(
                    app.state, "request_backend_shutdown", None
                )
                if callable(shutdown):
                    shutdown(reason)
                else:
                    # A direct uvicorn launch is still fail-closed: ending its
                    # event loop prevents a live backend from remaining.
                    loop.call_soon_threadsafe(loop.stop)
            finally:
                if current_watcher is not None:
                    current_watcher.stop()

    try:
        # Both checks happen before the ASGI startup completes, hence before
        # Uvicorn opens its listening socket.
        require_winamax_absent(detector=detector, interlock=interlock)
        initialize_database()
        require_winamax_absent(detector=detector, interlock=interlock)

        monitor = ProcessGuardMonitor(
            on_trip=stop_application,
            detector=detector,
            interlock=interlock,
        )
        monitor.start()
        app.state.process_guard_monitor = monitor

        if os.environ.get("WXA_DISABLE_WATCHER", "0") != "1":
            watcher = HistoryWatcher()
            require_winamax_absent(detector=detector, interlock=interlock)
            watcher.start()
        app.state.history_watcher = watcher
        interlock.ensure_allowed()
        yield
    finally:
        if monitor is not None:
            monitor.stop()
        if watcher is not None:
            watcher.stop()
        app.state.history_watcher = None
        app.state.process_guard_monitor = None


app = FastAPI(
    title="Winamax Expresso Analyzer",
    description="Analyse locale post-session uniquement — aucune assistance en temps réel.",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.state.process_probe = is_winamax_running
app.state.analysis_interlock = analysis_interlock
app.state.request_backend_shutdown = None
app.state.process_guard_shutdown_requested = False


@app.middleware("http")
async def reject_after_safety_trip(request, call_next):  # type: ignore[no-untyped-def]
    try:
        interlock: AnalysisInterlock = getattr(
            request.app.state, "analysis_interlock", analysis_interlock
        )
        interlock.ensure_allowed()
    except AnalysisForbiddenError:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Analyseur arrêté par le verrou de sécurité Winamax.exe."
            },
        )
    return await call_next(request)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


if config.frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=config.frontend_dist, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def frontend_not_built() -> str:
        return (
            "<main style='font-family:system-ui;max-width:720px;margin:5rem auto'>"
            "<h1>Winamax Analyzer</h1><p>Le backend local fonctionne, mais le frontend n’est pas encore compilé.</p>"
            "<p>Exécutez <code>install.ps1</code>, puis relancez <code>start.ps1</code>.</p></main>"
        )
