from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import func, select

from app.core.process_guard import (
    SAFETY_EXIT_CODE,
    AnalysisForbiddenError,
    ProcessGuardMonitor,
    analysis_interlock,
    require_winamax_absent,
)
from app.database import SessionLocal, initialize_database
from app.models import Hand, Tournament
from app.services.importer import rescan_all
from app.services.settings import load_settings


def _print_safety_refusal() -> None:
    print(
        json.dumps(
            {
                "error": "analysis_forbidden",
                "message": "Commande refusée par le verrou de sécurité.",
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Winamax Analyzer local administration")
    parser.add_argument("command", choices=["init", "rescan", "status"])
    args = parser.parse_args()

    if args.command == "init":
        initialize_database()
        print(json.dumps({"initialized": True}, ensure_ascii=False, indent=2))
        return 0

    monitor: ProcessGuardMonitor | None = None
    try:
        require_winamax_absent()
        if args.command == "rescan":
            monitor = ProcessGuardMonitor()
            monitor.start()
            analysis_interlock.ensure_allowed()

        initialize_database()
        with SessionLocal() as db:
            settings = load_settings(db)
            if args.command == "rescan":
                outcome = rescan_all(db, settings)
                require_winamax_absent()
                analysis_interlock.ensure_allowed()
                payload = outcome.to_dict()
            else:
                require_winamax_absent()
                payload = {
                    "history_paths": settings.history_paths,
                    "tournaments": db.scalar(select(func.count(Tournament.id))) or 0,
                    "hands": db.scalar(select(func.count(Hand.id))) or 0,
                }
                require_winamax_absent()
    except AnalysisForbiddenError:
        _print_safety_refusal()
        return SAFETY_EXIT_CODE
    finally:
        if monitor is not None:
            monitor.stop()

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
