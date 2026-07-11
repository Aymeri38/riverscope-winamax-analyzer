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


def _profile_percent(numerator: int | Decimal, denominator: int | Decimal) -> float:
    if not denominator:
        return 0.0
    return float(Decimal(numerator) / Decimal(denominator) * 100)


def _profile_breakdown(
    rows: list[SharedTournament],
    *,
    currency: str,
    buyin: Decimal | None = None,
    multiplier: Decimal | None = None,
) -> dict[str, object]:
    games = len(rows)
    hands = sum(row.total_hands for row in rows)
    total_buyins = sum((row.total_buyin for row in rows), Decimal("0"))
    total_winnings = sum((row.reward for row in rows), Decimal("0"))
    net = total_winnings - total_buyins
    wins = sum(row.final_rank == 1 for row in rows)
    itm = sum(row.reward > 0 for row in rows)
    chip_values = [row.chip_delta for row in rows if row.chip_delta is not None]
    return {
        "currency": currency,
        "buyin": float(buyin) if buyin is not None else None,
        "multiplier": float(multiplier) if multiplier is not None else None,
        "games": games,
        "hands": hands,
        "total_buyins": float(total_buyins),
        "total_winnings": float(total_winnings),
        "net_result": float(net),
        "roi_percent": _profile_percent(net, total_buyins),
        "wins": wins,
        "win_rate_percent": _profile_percent(wins, games),
        "itm_count": itm,
        "itm_percent": _profile_percent(itm, games),
        "average_net": float(net / games) if games else 0.0,
        "chip_ev_per_game": (
            float(Decimal(sum(chip_values)) / len(chip_values)) if chip_values else None
        ),
        "chip_ev_games": len(chip_values),
        "chip_ev_coverage_percent": _profile_percent(len(chip_values), games),
    }


def _profile_tournament(row: SharedTournament) -> dict[str, object]:
    """Return only target-hero tournament data; never hand or opponent data."""
    return {
        "public_id": row.public_id,
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
        "chip_delta": row.chip_delta,
    }


def contributor_profile(
    db: Session,
    public_id: str,
    *,
    recent_limit: int = 10,
) -> dict[str, object]:
    """Build a consented contributor profile, isolated from every other member.

    The query is deliberately rooted in the target member id.  The response is
    aggregated exclusively from ``SharedTournament`` and never reads replay
    JSON, player aliases, actions, cards, or another member's rows.
    """
    member = db.scalar(
        select(Member).where(
            Member.public_id == public_id,
            Member.disabled_at.is_(None),
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Contributeur introuvable.")

    rows = list(
        db.scalars(
            select(SharedTournament)
            .where(SharedTournament.member_id == member.id)
            .order_by(SharedTournament.started_at.asc(), SharedTournament.id.asc())
        )
    )
    # Do not expose the identity of an enrolled account that has not actually
    # contributed.  Such members are intentionally absent from /contributors.
    if not rows:
        raise HTTPException(status_code=404, detail="Contributeur introuvable.")

    games = len(rows)
    hands = sum(row.total_hands for row in rows)
    total_buyins = sum((row.total_buyin for row in rows), Decimal("0"))
    total_winnings = sum((row.reward for row in rows), Decimal("0"))
    net = total_winnings - total_buyins
    wins = sum(row.final_rank == 1 for row in rows)
    second_places = sum(row.final_rank == 2 for row in rows)
    third_places = sum(row.final_rank == 3 for row in rows)
    itm = sum(row.reward > 0 for row in rows)
    chip_values = [row.chip_delta for row in rows if row.chip_delta is not None]
    currencies = sorted({row.currency for row in rows})

    currency_groups: dict[str, list[SharedTournament]] = {}
    limit_groups: dict[tuple[str, Decimal], list[SharedTournament]] = {}
    multiplier_groups: dict[
        tuple[str, Decimal | None], list[SharedTournament]
    ] = {}
    day_groups: dict[tuple[str, str], list[SharedTournament]] = {}
    for row in rows:
        currency_groups.setdefault(row.currency, []).append(row)
        limit_groups.setdefault((row.currency, row.total_buyin), []).append(row)
        multiplier_groups.setdefault((row.currency, row.multiplier), []).append(row)
        day_groups.setdefault(
            (row.started_at.date().isoformat(), row.currency), []
        ).append(row)

    by_currency = [
        _profile_breakdown(group, currency=currency)
        for currency, group in sorted(currency_groups.items())
    ]
    by_limit = [
        _profile_breakdown(group, currency=currency, buyin=buyin)
        for (currency, buyin), group in sorted(
            limit_groups.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]
    by_multiplier = [
        _profile_breakdown(group, currency=currency, multiplier=multiplier)
        for (currency, multiplier), group in sorted(
            multiplier_groups.items(),
            key=lambda item: (
                item[0][0],
                item[0][1] is None,
                item[0][1] if item[0][1] is not None else Decimal("0"),
            ),
        )
    ]

    cumulative_by_currency: dict[str, Decimal] = {}
    trend: list[dict[str, object]] = []
    for (day, currency), group in sorted(day_groups.items()):
        day_buyins = sum((row.total_buyin for row in group), Decimal("0"))
        day_winnings = sum((row.reward for row in group), Decimal("0"))
        day_net = day_winnings - day_buyins
        cumulative_by_currency[currency] = (
            cumulative_by_currency.get(currency, Decimal("0")) + day_net
        )
        trend.append(
            {
                "date": day,
                "currency": currency,
                "games": len(group),
                "total_buyins": float(day_buyins),
                "total_winnings": float(day_winnings),
                "net_result": float(day_net),
                "cumulative_net": float(cumulative_by_currency[currency]),
            }
        )

    bounded_recent_limit = max(0, min(recent_limit, 10))
    recent_rows = rows[-bounded_recent_limit:] if bounded_recent_limit else []
    return {
        "contributor": {
            "public_id": member.public_id,
            "display_name": member.display_name,
            "joined_at": _public_datetime(member.created_at),
        },
        "summary": {
            "games": games,
            "hands": hands,
            "currency": currencies[0] if len(currencies) == 1 else None,
            "total_buyins": float(total_buyins) if len(currencies) == 1 else None,
            "total_winnings": float(total_winnings) if len(currencies) == 1 else None,
            "net_result": float(net) if len(currencies) == 1 else None,
            "roi_percent": (
                _profile_percent(net, total_buyins) if len(currencies) == 1 else None
            ),
            "wins": wins,
            "second_places": second_places,
            "third_places": third_places,
            "win_rate_percent": _profile_percent(wins, games),
            "second_place_percent": _profile_percent(second_places, games),
            "third_place_percent": _profile_percent(third_places, games),
            "itm_count": itm,
            "itm_percent": _profile_percent(itm, games),
            "average_buyin": float(total_buyins / games) if len(currencies) == 1 else None,
            "average_winnings": (
                float(total_winnings / games) if len(currencies) == 1 else None
            ),
            "average_net": float(net / games) if len(currencies) == 1 else None,
            "average_duration_seconds": sum(row.duration_seconds for row in rows) / games,
            "average_hands": hands / games,
            "chip_ev_per_game": (
                float(Decimal(sum(chip_values)) / len(chip_values)) if chip_values else None
            ),
            "chip_ev_games": len(chip_values),
            "chip_ev_coverage_percent": _profile_percent(len(chip_values), games),
            "first_game_at": _public_datetime(rows[0].started_at),
            "last_game_at": _public_datetime(rows[-1].started_at),
        },
        "by_currency": by_currency,
        "by_limit": by_limit,
        "by_multiplier": by_multiplier,
        "trend": trend,
        "recent_tournaments": [
            _profile_tournament(row) for row in reversed(recent_rows)
        ],
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
