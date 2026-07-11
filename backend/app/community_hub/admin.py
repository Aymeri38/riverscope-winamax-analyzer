from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.community_hub.models import Device, Invite, Member, Opponent, SharedTournament
from app.community_hub.opponents import purge_inactive_opponents, suppress_opponent
from app.community_hub.security import (
    DEVICE_TOKEN_LIFETIME,
    DEVICE_TOKEN_PREFIX,
    INVITE_TOKEN_PREFIX,
    generate_secret,
    hash_secret,
    normalize_device_label,
    normalize_public_name,
    utcnow_naive,
)


class AdminError(RuntimeError):
    pass


def bootstrap_owner(
    db: Session,
    *,
    display_name: str,
    device_label: str,
) -> tuple[Member, Device, str]:
    if db.scalar(select(Member.id).where(Member.role == "owner")) is not None:
        raise AdminError("Un proprietaire existe deja.")
    now = utcnow_naive()
    try:
        normalized_name, display_name_key = normalize_public_name(display_name)
        normalized_label = normalize_device_label(device_label)
    except ValueError as exc:
        raise AdminError(str(exc)) from exc
    token = generate_secret(DEVICE_TOKEN_PREFIX)
    member = Member(
        public_id=str(uuid4()),
        display_name=normalized_name,
        display_name_key=display_name_key,
        role="owner",
        policy_version="2",
        consented_at=now,
    )
    db.add(member)
    db.flush()
    device = Device(
        public_id=str(uuid4()),
        member_id=member.id,
        label=normalized_label,
        token_hash=hash_secret(token),
        expires_at=now + DEVICE_TOKEN_LIFETIME,
    )
    db.add(device)
    db.commit()
    db.refresh(member)
    db.refresh(device)
    return member, device, token


def create_invite(
    db: Session,
    *,
    expires_hours: int,
    owner_public_id: str | None = None,
    for_member_public_id: str | None = None,
) -> tuple[Invite, str]:
    if not 1 <= expires_hours <= 24 * 365:
        raise AdminError("La duree doit etre comprise entre 1 heure et 365 jours.")
    query = select(Member).where(Member.role == "owner", Member.disabled_at.is_(None))
    if owner_public_id is not None:
        query = query.where(Member.public_id == owner_public_id)
    owner = db.scalar(query.order_by(Member.created_at.asc()))
    if owner is None:
        raise AdminError("Aucun proprietaire actif trouve.")
    target_member_id: int | None = None
    if for_member_public_id is not None:
        target_member_id = db.scalar(
            select(Member.id).where(
                Member.public_id == for_member_public_id,
                Member.disabled_at.is_(None),
            )
        )
        if target_member_id is None:
            raise AdminError("Membre cible actif introuvable.")
    now = utcnow_naive()
    token = generate_secret(INVITE_TOKEN_PREFIX)
    invite = Invite(
        public_id=str(uuid4()),
        token_hash=hash_secret(token),
        created_by_member_id=owner.id,
        target_member_id=target_member_id,
        created_at=now,
        expires_at=now + timedelta(hours=expires_hours),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, token


def revoke(db: Session, *, kind: str, public_id: str) -> None:
    now = utcnow_naive()
    if kind == "device":
        row = db.scalar(select(Device).where(Device.public_id == public_id))
        attribute = "revoked_at"
    elif kind == "invite":
        row = db.scalar(select(Invite).where(Invite.public_id == public_id))
        attribute = "revoked_at"
    elif kind == "member":
        row = db.scalar(select(Member).where(Member.public_id == public_id))
        attribute = "disabled_at"
    else:
        raise AdminError("Type de revocation inconnu.")
    if row is None:
        raise AdminError("Element introuvable.")
    setattr(row, attribute, now)
    db.commit()


def delete_member(db: Session, *, public_id: str, confirmation: str) -> None:
    if confirmation != "DELETE":
        raise AdminError("Suppression refusee : --confirm DELETE est requis.")
    deleted = db.execute(delete(Member).where(Member.public_id == public_id))
    if deleted.rowcount != 1:
        db.rollback()
        raise AdminError("Membre introuvable.")
    db.execute(delete(Opponent).where(~Opponent.tournaments.any()))
    db.commit()


def suppress_opponent_by_public_id(
    db: Session,
    *,
    public_id: str,
    confirmation: str,
) -> None:
    try:
        suppress_opponent(db, public_id=public_id, confirmation=confirmation)
    except ValueError as exc:
        raise AdminError(str(exc)) from exc


def purge_opponents(db: Session, *, retention_days: int) -> int:
    if retention_days <= 0:
        raise AdminError("La retention doit etre strictement positive.")
    return purge_inactive_opponents(db, retention_days=retention_days)


def list_members(db: Session) -> list[dict[str, object]]:
    rows = db.execute(
        select(
            Member,
            func.count(func.distinct(Device.id)),
            func.count(func.distinct(SharedTournament.id)),
        )
        .outerjoin(Device, Device.member_id == Member.id)
        .outerjoin(SharedTournament, SharedTournament.member_id == Member.id)
        .group_by(Member.id)
        .order_by(Member.created_at.asc())
    ).all()
    return [
        {
            "public_id": member.public_id,
            "display_name": member.display_name,
            "role": member.role,
            "created_at": member.created_at.isoformat() + "Z",
            "disabled": member.disabled_at is not None,
            "device_count": int(device_count),
            "tournament_count": int(tournament_count),
        }
        for member, device_count, tournament_count in rows
    ]


def list_devices(db: Session, member_public_id: str | None = None) -> list[dict[str, object]]:
    query = select(Device, Member).join(Member, Member.id == Device.member_id)
    if member_public_id is not None:
        query = query.where(Member.public_id == member_public_id)
    rows = db.execute(query.order_by(Device.created_at.asc())).all()
    return [
        {
            "public_id": device.public_id,
            "member_id": member.public_id,
            "member_display_name": member.display_name,
            "label": device.label,
            "created_at": device.created_at.isoformat() + "Z",
            "expires_at": device.expires_at.isoformat() + "Z",
            "last_seen_at": (
                device.last_seen_at.isoformat() + "Z" if device.last_seen_at else None
            ),
            "revoked": device.revoked_at is not None,
        }
        for device, member in rows
    ]


def list_invites(db: Session) -> list[dict[str, object]]:
    rows = list(db.scalars(select(Invite).order_by(Invite.created_at.desc())))
    return [
        {
            "public_id": invite.public_id,
            "expires_at": invite.expires_at.isoformat() + "Z",
            "used": invite.used_at is not None,
            "revoked": invite.revoked_at is not None,
            "target_member_id": (
                db.scalar(select(Member.public_id).where(Member.id == invite.target_member_id))
                if invite.target_member_id is not None
                else None
            ),
        }
        for invite in rows
    ]
