from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

import uvicorn

from app.core.process_guard import (
    SAFETY_EXIT_CODE,
    AnalysisForbiddenError,
    analysis_interlock,
    require_winamax_absent,
)


logger = logging.getLogger("winamax_analyzer.runner")


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Winamax Analyzer protected local server")
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, choices=range(1024, 65536), default=8000)
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        require_winamax_absent()
    except AnalysisForbiddenError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Fermez Winamax puis relancez manuellement start.ps1. "
            "Aucun redémarrage automatique ne sera tenté.",
            file=sys.stderr,
        )
        return SAFETY_EXIT_CODE

    # Importing the ASGI application only after the preflight keeps database and
    # watcher initialization out of every refused launch.
    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            reload=False,
            workers=1,
            log_level="info",
        )
    )

    def request_shutdown(reason: str) -> None:
        app.state.process_guard_shutdown_requested = True
        server.should_exit = True
        logger.critical("%s Watcher et backend en cours d'arrêt; aucune relance.", reason)

    app.state.request_backend_shutdown = request_shutdown
    try:
        server.run()
    except AnalysisForbiddenError as exc:
        logger.critical("Démarrage interrompu par le verrou de sécurité: %s", exc)
    finally:
        app.state.request_backend_shutdown = None

    if analysis_interlock.blocked or getattr(
        app.state, "process_guard_shutdown_requested", False
    ):
        return SAFETY_EXIT_CODE
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
