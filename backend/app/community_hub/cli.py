from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from app.community_hub.approval import HubConfigurationError, require_community_approval
from app.core.process_guard import SAFETY_EXIT_CODE, AnalysisForbiddenError, ProcessProbe, require_winamax_absent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administration locale du community hub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap-owner", help="Cree le proprietaire initial")
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--device-label", required=True)

    invite = subparsers.add_parser("create-invite", help="Cree une invitation a usage unique")
    invite.add_argument("--expires-hours", type=int, default=168)
    invite.add_argument("--owner-public-id")
    invite.add_argument(
        "--for-member-public-id",
        help="Reenrole un membre existant sans creer une seconde identite",
    )

    revoke_parser = subparsers.add_parser("revoke", help="Revoque un appareil, membre ou invite")
    revoke_parser.add_argument("--kind", choices=("device", "member", "invite"), required=True)
    revoke_parser.add_argument("--public-id", required=True)

    delete_parser = subparsers.add_parser(
        "delete-member", help="Supprime definitivement un membre et ses donnees"
    )
    delete_parser.add_argument("--public-id", required=True)
    delete_parser.add_argument("--confirm", required=True)

    suppress_parser = subparsers.add_parser(
        "suppress-opponent",
        help="Supprime un profil adverse et empeche sa recreation",
    )
    suppress_parser.add_argument("--public-id", required=True)
    suppress_parser.add_argument("--confirm", required=True)

    purge_parser = subparsers.add_parser(
        "purge-opponents", help="Purge les profils adverses inactifs"
    )
    purge_parser.add_argument("--retention-days", type=int)

    subparsers.add_parser("list-members", help="Liste les membres sans aucun secret")
    devices_parser = subparsers.add_parser(
        "list-devices", help="Liste les appareils sans jeton ni hash"
    )
    devices_parser.add_argument("--member-public-id")
    subparsers.add_parser("list-invites", help="Liste les invitations sans jeton")
    return parser


def run(
    argv: Sequence[str] | None = None,
    database: Any | None = None,
    *,
    detector: ProcessProbe | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = environ if environ is not None else os.environ
    try:
        require_winamax_absent(detector=detector)
        require_community_approval(env)
    except AnalysisForbiddenError as exc:
        print(str(exc), file=sys.stderr)
        return SAFETY_EXIT_CODE
    except HubConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args = _parser().parse_args(argv)

    # Lazy imports keep model and DB initialization behind both mandatory gates.
    from app.community_hub.admin import (
        AdminError,
        bootstrap_owner,
        create_invite,
        delete_member,
        list_devices,
        list_invites,
        list_members,
        purge_opponents,
        revoke,
        suppress_opponent_by_public_id,
    )
    from app.community_hub.config import get_hub_config
    from app.community_hub.database import HubDatabase

    hub_db = database or HubDatabase.from_environment()
    try:
        require_winamax_absent(detector=detector)
        hub_db.initialize()
        require_winamax_absent(detector=detector)
    except AnalysisForbiddenError as exc:
        hub_db.dispose()
        print(str(exc), file=sys.stderr)
        return SAFETY_EXIT_CODE
    db = hub_db.session()
    try:
        if args.command == "bootstrap-owner":
            member, device, token = bootstrap_owner(
                db,
                display_name=args.display_name,
                device_label=args.device_label,
            )
            print(
                json.dumps(
                    {
                        "member_id": member.public_id,
                        "device_id": device.public_id,
                        "device_token": token,
                        "warning": "Ce jeton ne sera plus affiche.",
                    }
                )
            )
        elif args.command == "create-invite":
            invite, token = create_invite(
                db,
                expires_hours=args.expires_hours,
                owner_public_id=args.owner_public_id,
                for_member_public_id=args.for_member_public_id,
            )
            print(
                json.dumps(
                    {
                        "invite_id": invite.public_id,
                        "invite_token": token,
                        "expires_at": invite.expires_at.isoformat() + "Z",
                        "warning": "Ce jeton ne sera plus affiche.",
                    }
                )
            )
        elif args.command == "revoke":
            revoke(db, kind=args.kind, public_id=args.public_id)
            print(json.dumps({"status": "revoked", "kind": args.kind, "public_id": args.public_id}))
        elif args.command == "delete-member":
            delete_member(db, public_id=args.public_id, confirmation=args.confirm)
            print(json.dumps({"status": "deleted", "member_id": args.public_id}))
        elif args.command == "suppress-opponent":
            suppress_opponent_by_public_id(
                db,
                public_id=args.public_id,
                confirmation=args.confirm,
            )
            print(json.dumps({"status": "suppressed", "opponent_id": args.public_id}))
        elif args.command == "purge-opponents":
            retention_days = (
                args.retention_days
                if args.retention_days is not None
                else get_hub_config(dict(env)).opponent_retention_days
            )
            purged = purge_opponents(db, retention_days=retention_days)
            print(json.dumps({"status": "purged", "count": purged}))
        elif args.command == "list-members":
            print(json.dumps({"items": list_members(db)}))
        elif args.command == "list-devices":
            print(
                json.dumps(
                    {"items": list_devices(db, member_public_id=args.member_public_id)}
                )
            )
        else:
            print(json.dumps({"items": list_invites(db)}))
        return 0
    except (AdminError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
