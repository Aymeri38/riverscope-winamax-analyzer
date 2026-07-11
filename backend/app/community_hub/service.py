from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.community_hub.models import (
    Device,
    Invite,
    Member,
    SharedHand,
    SharedTournament,
    SyncReceipt,
)
from app.community_hub.schemas import EnrollRequest, SyncTournamentRequest
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
from app.core.process_guard import AnalysisForbiddenError


def _uuid() -> str:
    return str(uuid4())


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Les dates doivent inclure un fuseau horaire.")
    return value.astimezone(UTC).replace(tzinfo=None)


def _public_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def enroll(db: Session, request: EnrollRequest) -> tuple[Member, Device, str]:
    now = utcnow_naive()
    if not request.invite_token.startswith(INVITE_TOKEN_PREFIX):
        raise HTTPException(status_code=400, detail="Invitation invalide ou expiree.")
    invite_digest = hash_secret(request.invite_token)
    invite = db.scalar(select(Invite).where(Invite.token_hash == invite_digest))
    if invite is None or not hmac.compare_digest(invite.token_hash, invite_digest):
        raise HTTPException(status_code=400, detail="Invitation invalide ou expiree.")
    if invite.used_at is not None or invite.revoked_at is not None or invite.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invitation invalide ou expiree.")

    try:
        display_name, display_name_key = normalize_public_name(request.display_name)
        device_label = normalize_device_label(request.device_label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nom public ou appareil invalide.") from exc
    raw_device_token = generate_secret(DEVICE_TOKEN_PREFIX)
    try:
        if invite.target_member_id is not None:
            member = db.get(Member, invite.target_member_id)
            if (
                member is None
                or member.disabled_at is not None
                or not hmac.compare_digest(member.display_name_key, display_name_key)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Invitation de reenrolement incompatible avec ce nom public.",
                )
            member.policy_version = request.policy_version
            member.consented_at = now
        else:
            member = Member(
                public_id=_uuid(),
                display_name=display_name,
                display_name_key=display_name_key,
                role="member",
                policy_version=request.policy_version,
                consented_at=now,
            )
            db.add(member)
            db.flush()
        claim = db.execute(
            update(Invite)
            .where(
                Invite.id == invite.id,
                Invite.used_at.is_(None),
                Invite.revoked_at.is_(None),
                Invite.expires_at > now,
            )
            .values(used_at=now, used_by_member_id=member.id)
        )
        if claim.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Cette invitation vient d'etre utilisee.")
        device = Device(
            public_id=_uuid(),
            member_id=member.id,
            label=device_label,
            token_hash=hash_secret(raw_device_token),
            expires_at=now + DEVICE_TOKEN_LIFETIME,
        )
        db.add(device)
        db.commit()
        db.refresh(member)
        db.refresh(device)
        return member, device, raw_device_token
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Nom communautaire indisponible ou enrolement concurrent.",
        ) from exc


def _canonical_payload(request: SyncTournamentRequest) -> tuple[str, int]:
    # client_key is a device-local HMAC namespace and changes after a device is
    # replaced.  Content identity must survive that lifecycle to prevent the
    # same tournament being duplicated on targeted re-enrollment.
    canonical = json.dumps(
        request.model_dump(mode="json", exclude={"client_key"}, exclude_none=False),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload_bytes = canonical.encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest(), len(payload_bytes)


def _ensure_sync_allowed(db: Session, ensure_allowed: Callable[[], None] | None) -> None:
    if ensure_allowed is None:
        return
    try:
        ensure_allowed()
    except AnalysisForbiddenError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Synchronisation annulee par le verrou de securite.",
        ) from exc


def _ensure_receipt_quota(db: Session, tournament_id: int, maximum: int) -> None:
    count = int(
        db.scalar(
            select(func.count(SyncReceipt.id)).where(
                SyncReceipt.tournament_id == tournament_id
            )
        )
        or 0
    )
    if count >= maximum:
        raise HTTPException(
            status_code=507,
            detail="Quota de renouvellements atteint; contactez l'hote.",
        )


def sync_tournament(
    db: Session,
    member_id: int,
    request: SyncTournamentRequest,
    *,
    ensure_allowed: Callable[[], None] | None = None,
    max_tournaments: int = 50_000,
    max_hands: int = 1_000_000,
    max_payload_bytes: int = 2 * 1024 * 1024 * 1024,
    max_receipts_per_tournament: int = 16,
) -> tuple[SharedTournament, bool]:
    _ensure_sync_allowed(db, ensure_allowed)
    now = utcnow_naive()
    started_at = _naive_utc(request.tournament.started_at)
    ended_at = _naive_utc(request.tournament.ended_at)
    # A second server-side post-session gate.  Small clock skews are tolerated,
    # but a tournament ending less than one minute ago is never accepted.
    if ended_at > now - timedelta(seconds=60):
        raise HTTPException(
            status_code=409,
            detail="Tournoi trop recent : synchronisation post-session uniquement.",
        )
    for hand in request.tournament.hands:
        played_at = _naive_utc(hand.played_at)
        if played_at > now - timedelta(seconds=60):
            raise HTTPException(
                status_code=409,
                detail="Main trop recente : synchronisation post-session uniquement.",
            )
        if played_at < started_at - timedelta(minutes=5) or played_at > ended_at + timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="Date de main hors du tournoi.")

    digest, payload_bytes = _canonical_payload(request)
    receipt = db.scalar(
        select(SyncReceipt).where(
            SyncReceipt.member_id == member_id,
            SyncReceipt.client_key == request.client_key,
        )
    )
    if receipt is not None:
        if not hmac.compare_digest(receipt.payload_digest, digest):
            raise HTTPException(
                status_code=409,
                detail="client_key deja utilise avec un contenu different.",
            )
        existing = db.get(SharedTournament, receipt.tournament_id)
        if existing is None:  # Defensive: foreign keys should make this impossible.
            raise HTTPException(status_code=409, detail="Recu de synchronisation invalide.")
        _ensure_sync_allowed(db, ensure_allowed)
        return existing, False

    content_match = db.scalar(
        select(SharedTournament).where(
            SharedTournament.member_id == member_id,
            SharedTournament.content_digest == digest,
        )
    )
    if content_match is not None:
        _ensure_receipt_quota(db, content_match.id, max_receipts_per_tournament)
        try:
            db.add(
                SyncReceipt(
                    member_id=member_id,
                    client_key=request.client_key,
                    payload_digest=digest,
                    tournament_id=content_match.id,
                )
            )
            _ensure_sync_allowed(db, ensure_allowed)
            db.commit()
            return content_match, False
        except IntegrityError as exc:
            db.rollback()
            receipt = db.scalar(
                select(SyncReceipt).where(
                    SyncReceipt.member_id == member_id,
                    SyncReceipt.client_key == request.client_key,
                )
            )
            if receipt is not None and hmac.compare_digest(receipt.payload_digest, digest):
                existing = db.get(SharedTournament, receipt.tournament_id)
                if existing is not None:
                    return existing, False
            raise HTTPException(status_code=409, detail="Conflit de synchronisation.") from exc

    data = request.tournament
    tournament_count, hand_count, stored_bytes = db.execute(
        select(
            func.count(SharedTournament.id),
            func.coalesce(func.sum(SharedTournament.total_hands), 0),
            func.coalesce(func.sum(SharedTournament.payload_bytes), 0),
        ).where(SharedTournament.member_id == member_id)
    ).one()
    if (
        int(tournament_count) + 1 > max_tournaments
        or int(hand_count) + data.total_hands > max_hands
        or int(stored_bytes) + payload_bytes > max_payload_bytes
    ):
        raise HTTPException(
            status_code=507,
            detail="Quota local du contributeur atteint; contactez l'hote.",
        )

    tournament = SharedTournament(
        public_id=_uuid(),
        member_id=member_id,
        client_key=request.client_key,
        content_digest=digest,
        schema_version=request.schema_version,
        started_at=started_at,
        ended_at=ended_at,
        format=data.format,
        is_nitro=data.is_nitro,
        currency=data.currency,
        total_buyin=data.total_buyin,
        multiplier=data.multiplier,
        prize_pool=data.prize_pool,
        reward=data.reward,
        final_rank=data.final_rank,
        duration_seconds=data.duration_seconds,
        total_hands=data.total_hands,
        registered_players=data.registered_players,
        initial_stack=data.initial_stack,
        final_stack=data.final_stack,
        chip_delta=data.chip_delta,
        payload_bytes=payload_bytes,
    )
    try:
        db.add(tournament)
        db.flush()
        for hand in data.hands:
            hero = next(player for player in hand.players if player.alias == "HERO")
            replay_json = json.dumps(
                hand.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            db.add(
                SharedHand(
                    public_id=_uuid(),
                    tournament_id=tournament.id,
                    member_id=member_id,
                    hand_number=hand.hand_number,
                    played_at=_naive_utc(hand.played_at),
                    hero_position=hero.position,
                    active_players=hand.active_players,
                    big_blind=hand.big_blind,
                    total_pot=hand.total_pot,
                    hero_net=hand.hero_net,
                    is_all_in=hand.is_all_in,
                    reached_showdown=hand.reached_showdown,
                    replay_json=replay_json,
                )
            )
        db.flush()
        db.add(
            SyncReceipt(
                member_id=member_id,
                client_key=request.client_key,
                payload_digest=digest,
                tournament_id=tournament.id,
            )
        )
        _ensure_sync_allowed(db, ensure_allowed)
        db.commit()
        db.refresh(tournament)
        return tournament, True
    except IntegrityError as exc:
        db.rollback()
        receipt = db.scalar(
            select(SyncReceipt).where(
                SyncReceipt.member_id == member_id,
                SyncReceipt.client_key == request.client_key,
            )
        )
        if receipt is not None and hmac.compare_digest(receipt.payload_digest, digest):
            existing = db.get(SharedTournament, receipt.tournament_id)
            if existing is not None:
                return existing, False
        content_match = db.scalar(
            select(SharedTournament).where(
                SharedTournament.member_id == member_id,
                SharedTournament.content_digest == digest,
            )
        )
        if content_match is not None:
            try:
                _ensure_receipt_quota(db, content_match.id, max_receipts_per_tournament)
                db.add(
                    SyncReceipt(
                        member_id=member_id,
                        client_key=request.client_key,
                        payload_digest=digest,
                        tournament_id=content_match.id,
                    )
                )
                _ensure_sync_allowed(db, ensure_allowed)
                db.commit()
                return content_match, False
            except IntegrityError:
                db.rollback()
        raise HTTPException(status_code=409, detail="Conflit de synchronisation.") from exc


def contributor_id_to_internal(db: Session, public_id: str | None) -> int | None:
    if public_id is None:
        return None
    member_id = db.scalar(
        select(Member.id).where(
            Member.public_id == public_id,
            Member.disabled_at.is_(None),
        )
    )
    if member_id is None:
        raise HTTPException(status_code=404, detail="Contributeur introuvable.")
    return int(member_id)


def tournament_summary(row: SharedTournament) -> dict[str, object]:
    return {
        "public_id": row.public_id,
        "contributor_id": row.member.public_id,
        "contributor_display_name": row.member.display_name,
        "started_at": _public_datetime(row.started_at),
        "ended_at": _public_datetime(row.ended_at),
        "format": row.format,
        "is_nitro": row.is_nitro,
        "currency": row.currency,
        "total_buyin": float(row.total_buyin),
        "multiplier": float(row.multiplier) if row.multiplier is not None else None,
        "prize_pool": float(row.prize_pool),
        "reward": float(row.reward),
        "net_result": float(row.reward - row.total_buyin),
        "final_rank": row.final_rank,
        "duration_seconds": row.duration_seconds,
        "total_hands": row.total_hands,
        "registered_players": row.registered_players,
        "initial_stack": row.initial_stack,
        "final_stack": row.final_stack,
        "chip_delta": row.chip_delta,
    }


def hand_summary(row: SharedHand) -> dict[str, object]:
    replay = json.loads(row.replay_json)
    return {
        "public_id": row.public_id,
        "tournament_id": row.tournament.public_id,
        "contributor_id": row.tournament.member.public_id,
        "contributor_display_name": row.tournament.member.display_name,
        "hand_number": row.hand_number,
        "played_at": _public_datetime(row.played_at),
        "hero_position": row.hero_position,
        "active_players": row.active_players,
        "big_blind": row.big_blind,
        "total_pot": row.total_pot,
        "hero_net": row.hero_net,
        "is_all_in": row.is_all_in,
        "reached_showdown": row.reached_showdown,
        "hero_cards": replay.get("hero_cards", []),
        "board": replay.get("board", []),
    }


def dashboard(db: Session, member_id: int | None) -> dict[str, object]:
    # Revocation retains rows locally for the host but removes them from every
    # collective view; permanent erasure is a separate explicit admin action.
    tournaments_query = (
        select(SharedTournament)
        .join(Member, Member.id == SharedTournament.member_id)
        .where(Member.disabled_at.is_(None))
    )
    hands_query = (
        select(func.count(SharedHand.id))
        .join(Member, Member.id == SharedHand.member_id)
        .where(Member.disabled_at.is_(None))
    )
    if member_id is not None:
        tournaments_query = tournaments_query.where(SharedTournament.member_id == member_id)
        hands_query = hands_query.where(SharedHand.member_id == member_id)
    tournaments = list(db.scalars(tournaments_query))
    total_buyin = sum((row.total_buyin for row in tournaments), Decimal("0"))
    total_reward = sum((row.reward for row in tournaments), Decimal("0"))
    net = total_reward - total_buyin
    games = len(tournaments)
    wins = sum(row.final_rank == 1 for row in tournaments)
    itm = sum(row.reward > 0 for row in tournaments)
    return {
        "contributor_id": (
            db.scalar(select(Member.public_id).where(Member.id == member_id))
            if member_id is not None
            else None
        ),
        "contributors": int(
            db.scalar(
                select(func.count(Member.id)).where(
                    Member.disabled_at.is_(None),
                    Member.tournaments.any(),
                )
            )
            or 0
        ),
        "tournaments": games,
        "hands": int(db.scalar(hands_query) or 0),
        "total_buyin": float(total_buyin),
        "total_reward": float(total_reward),
        "net_result": float(net),
        "roi_percent": float((net / total_buyin * 100) if total_buyin else 0),
        "win_rate_percent": (wins / games * 100) if games else 0.0,
        "itm_percent": (itm / games * 100) if games else 0.0,
    }


TOURNAMENT_WITH_RELATIONS = selectinload(SharedTournament.member)
HAND_WITH_RELATIONS = selectinload(SharedHand.tournament).selectinload(SharedTournament.member)
