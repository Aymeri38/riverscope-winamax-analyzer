from __future__ import annotations

import argparse
import getpass
import json
import sys

from app.core.process_guard import (
    AnalysisForbiddenError,
    ProcessGuardMonitor,
    require_winamax_absent,
)


COMMUNITY_CONSENT_VERSION = "1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Appairage communautaire post-session")
    commands = parser.add_subparsers(dest="command", required=True)
    join = commands.add_parser("join")
    join.add_argument("--hub-url", required=True)
    join.add_argument("--display-name", required=True)
    join.add_argument("--consent-version", default=COMMUNITY_CONSENT_VERSION)
    join.add_argument("--consent", action="store_true", required=True)
    commands.add_parser("status")
    commands.add_parser("sync")
    commands.add_parser("leave")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        require_winamax_absent()
    except AnalysisForbiddenError:
        print("Opération refusée : fermez Winamax avant le mode communautaire.", file=sys.stderr)
        return 23
    monitor = ProcessGuardMonitor()
    try:
        monitor.start()
    except AnalysisForbiddenError:
        print("Opération refusée : fermez Winamax avant le mode communautaire.", file=sys.stderr)
        return 23
    try:
        return _run_command(args)
    finally:
        monitor.stop()


def _run_command(args: argparse.Namespace) -> int:
    # These imports may initialize the local data directory/database, so they
    # intentionally occur only after the fail-closed process preflight.
    from app.database import SessionLocal, initialize_database
    from app.core.community_secret import CommunitySecretError
    from app.schemas.community import CommunityJoinRequest
    from app.services.community_client import CommunityClient, CommunityError

    initialize_database()
    client = CommunityClient()
    try:
        with SessionLocal() as db:
            if args.command == "join":
                invite = getpass.getpass("Code d'invitation (masqué) : ")
                request = CommunityJoinRequest(
                    hub_url=args.hub_url,
                    invite=invite,
                    display_name=args.display_name,
                    consent=args.consent,
                    consent_version=args.consent_version,
                )
                result = client.join(db, request)
            elif args.command == "sync":
                result = client.sync(db).model_dump(mode="json")
            elif args.command == "leave":
                remote_revoked = client.leave(db)
                result = {"configured": False, "remote_revoked": remote_revoked}
            else:
                result = client.status(db).model_dump(mode="json")
    except AnalysisForbiddenError:
        print("Opération interrompue : Winamax.exe a été détecté.", file=sys.stderr)
        return 23
    except (CommunityError, CommunitySecretError, ValueError, OSError) as exc:
        print(
            f"Opération communautaire impossible ({getattr(exc, 'code', type(exc).__name__)}).",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
