from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.community_hub.models import (
    Member,
    Opponent,
    OpponentSuppression,
    OpponentSyncReceipt,
    SharedHand,
    SharedOpponentObservation,
    SharedTournament,
    SharedTournamentOpponent,
)
from app.community_hub.opponent_identity import (
    OpponentIdentityError,
    OpponentIdentityService,
)
from app.community_hub.schemas import OpponentSyncRequest
from app.core.process_guard import AnalysisForbiddenError


METRICS_VERSION = "2"
PREFLOP_VOLUNTARY = frozenset({"CALL", "BET", "RAISE", "ALL_IN"})
AGGRESSIVE = frozenset({"BET", "RAISE", "ALL_IN"})
POSTFLOP_STREETS = frozenset({"FLOP", "TURN", "RIVER"})


def _public_datetime(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _ensure_allowed(db: Session, callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    try:
        callback()
    except AnalysisForbiddenError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Synchronisation adverse annulee par le verrou de securite.",
        ) from exc


def _canonical_identity_digest(
    prepared: list[tuple[object, str]],
) -> str:
    # Never hash raw display names: a stolen database must not support a direct
    # dictionary attack against an ordinary SHA digest of poker aliases.
    values = []
    for item, identity_key in prepared:
        values.append(
            {
                "alias": item.alias,
                "identity_key": identity_key,
                "final_rank": item.final_rank,
                "reward": str(item.reward) if item.reward is not None else None,
                "starting_stack": item.starting_stack,
                "final_stack": item.final_stack,
            }
        )
    canonical = json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _observed_aliases(hands: list[SharedHand]) -> set[str]:
    aliases: set[str] = set()
    try:
        for hand in hands:
            replay = json.loads(hand.replay_json)
            for player in replay.get("players", []):
                alias = player.get("alias")
                if isinstance(alias, str) and alias != "HERO":
                    aliases.add(alias)
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Replay adverse invalide.") from exc
    if any(alias not in {"OPPONENT_1", "OPPONENT_2"} for alias in aliases):
        raise HTTPException(status_code=422, detail="Alias adverse invalide.")
    return aliases


def _action_is_aggressive(action: dict[str, object], current_to: int) -> bool:
    action_type = action.get("action_type")
    if action_type in {"BET", "RAISE"}:
        return True
    if action_type != "ALL_IN":
        return False
    to_amount = action.get("to_amount")
    return isinstance(to_amount, int) and to_amount > current_to


def _observation_facts(
    replay: dict[str, object],
    alias: str,
    big_blind: int,
) -> dict[str, object] | None:
    players = replay.get("players")
    actions_value = replay.get("actions")
    if not isinstance(players, list) or not isinstance(actions_value, list):
        return None
    player = next(
        (
            value
            for value in players
            if isinstance(value, dict) and value.get("alias") == alias
        ),
        None,
    )
    if player is None:
        return None
    actions = sorted(
        (value for value in actions_value if isinstance(value, dict)),
        key=lambda value: int(value.get("sequence", 0)),
    )
    preflop = [value for value in actions if value.get("street") == "PREFLOP"]
    actor_preflop = [value for value in preflop if value.get("actor_alias") == alias]
    preflop_known = any(
        value.get("action_type") in {"FOLD", "CHECK", "CALL", "BET", "RAISE", "ALL_IN"}
        for value in actor_preflop
    )
    vpip = any(value.get("action_type") in PREFLOP_VOLUNTARY for value in actor_preflop)
    shove = any(value.get("action_type") == "ALL_IN" for value in actor_preflop)

    current_to = 0
    raises_before = 0
    faced_open = False
    three_bet = False
    pfr = False
    limp = False
    first_voluntary_seen = False
    for action in preflop:
        actor = action.get("actor_alias")
        action_type = action.get("action_type")
        aggressive = _action_is_aggressive(action, current_to)
        if (
            actor == alias
            and not first_voluntary_seen
            and action_type in {"FOLD", "CALL", "BET", "RAISE", "ALL_IN"}
        ):
            faced_open = raises_before > 0
            limp = action_type == "CALL" and raises_before == 0
            first_voluntary_seen = True
        if actor == alias and action_type in PREFLOP_VOLUNTARY:
            if aggressive:
                pfr = True
                if raises_before == 1:
                    three_bet = True
        if aggressive:
            raises_before += 1
        to_amount = action.get("to_amount")
        if isinstance(to_amount, int):
            current_to = max(current_to, to_amount)

    actor_postflop = [
        value
        for value in actions
        if value.get("actor_alias") == alias and value.get("street") in POSTFLOP_STREETS
    ]
    postflop_aggressive = sum(
        value.get("action_type") in AGGRESSIVE for value in actor_postflop
    )
    postflop_calls = sum(value.get("action_type") == "CALL" for value in actor_postflop)
    postflop_checks = sum(value.get("action_type") == "CHECK" for value in actor_postflop)
    postflop_folds = sum(value.get("action_type") == "FOLD" for value in actor_postflop)
    board = replay.get("board")
    board_has_flop = isinstance(board, list) and len(board) >= 3
    folded_preflop = any(value.get("action_type") == "FOLD" for value in actor_preflop)
    saw_flop = bool(actor_postflop) or (board_has_flop and not folded_preflop)
    showed = bool(player.get("showed"))
    winner = bool(player.get("is_winner"))
    reached_showdown = showed or any(
        value.get("actor_alias") == alias
        and value.get("street") == "SHOWDOWN"
        and value.get("action_type") in {"SHOW", "MUCK"}
        for value in actions
    )
    starting_stack = int(player.get("starting_stack") or 0)
    return {
        "position": player.get("position") if isinstance(player.get("position"), str) else None,
        "starting_stack": starting_stack,
        "stack_bb": (
            Decimal(starting_stack) / Decimal(big_blind) if big_blind > 0 else None
        ),
        "invested": int(player.get("invested") or 0),
        "won": int(player.get("won") or 0),
        "net": player.get("net") if isinstance(player.get("net"), int) else None,
        "showed": showed,
        "is_winner": winner,
        "is_all_in": bool(player.get("is_all_in")) or shove,
        "preflop_known": preflop_known,
        "vpip": vpip,
        "pfr": pfr,
        "limp": limp,
        "faced_open": faced_open,
        "three_bet": three_bet,
        "shove": shove,
        "postflop_aggressive_actions": postflop_aggressive,
        "postflop_calls": postflop_calls,
        "postflop_checks": postflop_checks,
        "postflop_folds": postflop_folds,
        "saw_flop": saw_flop,
        "went_showdown": reached_showdown,
        "won_showdown": reached_showdown and winner,
    }


def _stored_counts(db: Session, tournament_id: int) -> tuple[int, int]:
    opponents = int(
        db.scalar(
            select(func.count(SharedTournamentOpponent.id)).where(
                SharedTournamentOpponent.tournament_id == tournament_id
            )
        )
        or 0
    )
    observations = int(
        db.scalar(
            select(func.count(SharedOpponentObservation.id))
            .join(
                SharedTournamentOpponent,
                SharedTournamentOpponent.id
                == SharedOpponentObservation.tournament_opponent_id,
            )
            .where(SharedTournamentOpponent.tournament_id == tournament_id)
        )
        or 0
    )
    return opponents, observations


def sync_tournament_opponents(
    db: Session,
    *,
    member_id: int,
    tournament_public_id: str,
    request: OpponentSyncRequest,
    identity_service: OpponentIdentityService,
    ensure_allowed: Callable[[], None] | None = None,
    _retry_on_integrity: bool = True,
) -> tuple[bool, int, int]:
    _ensure_allowed(db, ensure_allowed)
    tournament = db.scalar(
        select(SharedTournament)
        .where(
            SharedTournament.public_id == tournament_public_id,
            SharedTournament.member_id == member_id,
        )
        .options(selectinload(SharedTournament.hands))
    )
    if tournament is None:
        raise HTTPException(status_code=404, detail="Tournoi introuvable.")
    now = datetime.now(UTC).replace(tzinfo=None)
    if tournament.ended_at > now - timedelta(seconds=60) or any(
        hand.played_at > now - timedelta(seconds=60) for hand in tournament.hands
    ):
        raise HTTPException(
            status_code=409,
            detail="Tournoi trop recent : enrichissement post-session uniquement.",
        )
    expected_aliases = _observed_aliases(tournament.hands)
    if {item.alias for item in request.opponents} != expected_aliases:
        raise HTTPException(status_code=422, detail="Liste adverse incomplete ou invalide.")

    prepared: list[tuple[object, str]] = []
    encrypted_by_alias = {}
    try:
        for item in request.opponents:
            encrypted = identity_service.encrypt(item.display_name)
            prepared.append((item, encrypted.identity_key))
            encrypted_by_alias[item.alias] = encrypted
    except OpponentIdentityError as exc:
        raise HTTPException(status_code=422, detail="Pseudo adverse invalide.") from exc
    if len({identity for _item, identity in prepared}) != len(prepared):
        raise HTTPException(status_code=409, detail="Identites adverses incompatibles.")
    digest = _canonical_identity_digest(prepared)
    receipt = db.scalar(
        select(OpponentSyncReceipt).where(
            OpponentSyncReceipt.tournament_id == tournament.id
        )
    )
    if receipt is not None:
        if not hmac.compare_digest(receipt.payload_digest, digest):
            raise HTTPException(
                status_code=409,
                detail="Enrichissement deja enregistre avec un contenu different.",
            )
        counts = _stored_counts(db, tournament.id)
        return False, counts[0], counts[1]

    _ensure_allowed(db, ensure_allowed)
    observation_count = 0
    stored_opponent_count = 0
    try:
        for item, identity_key in prepared:
            suppressed = db.scalar(
                select(OpponentSuppression.id).where(
                    OpponentSuppression.identity_key == identity_key
                )
            )
            if suppressed is not None:
                continue
            encrypted = encrypted_by_alias[item.alias]
            opponent = db.scalar(
                select(Opponent).where(Opponent.identity_key == identity_key)
            )
            if opponent is None:
                opponent = Opponent(
                    public_id=str(uuid4()),
                    identity_key=identity_key,
                    display_ciphertext=encrypted.ciphertext,
                    display_nonce=encrypted.nonce,
                    key_version=encrypted.key_version,
                    first_seen_at=tournament.started_at,
                    last_seen_at=tournament.started_at,
                )
                db.add(opponent)
                db.flush()
            else:
                opponent.first_seen_at = min(opponent.first_seen_at, tournament.started_at)
                opponent.last_seen_at = max(opponent.last_seen_at, tournament.started_at)
            link = SharedTournamentOpponent(
                tournament_id=tournament.id,
                opponent_id=opponent.id,
                alias=item.alias,
                final_rank=item.final_rank,
                reward=item.reward,
                starting_stack=item.starting_stack,
                final_stack=item.final_stack,
            )
            db.add(link)
            db.flush()
            stored_opponent_count += 1
            for hand in tournament.hands:
                replay = json.loads(hand.replay_json)
                facts = _observation_facts(replay, item.alias, hand.big_blind)
                if facts is None:
                    continue
                db.add(
                    SharedOpponentObservation(
                        shared_hand_id=hand.id,
                        tournament_opponent_id=link.id,
                        metrics_version=METRICS_VERSION,
                        **facts,
                    )
                )
                observation_count += 1
        db.add(OpponentSyncReceipt(tournament_id=tournament.id, payload_digest=digest))
        _ensure_allowed(db, ensure_allowed)
        db.commit()
        return True, stored_opponent_count, observation_count
    except IntegrityError as exc:
        db.rollback()
        receipt = db.scalar(
            select(OpponentSyncReceipt).where(
                OpponentSyncReceipt.tournament_id == tournament.id
            )
        )
        if receipt is not None and hmac.compare_digest(receipt.payload_digest, digest):
            counts = _stored_counts(db, tournament.id)
            return False, counts[0], counts[1]
        # A concurrent tournament may have inserted the same normalized HMAC
        # identity between our SELECT and INSERT. Retry once from a clean
        # transaction so both tournaments converge on one Opponent row.
        if _retry_on_integrity:
            return sync_tournament_opponents(
                db,
                member_id=member_id,
                tournament_public_id=tournament_public_id,
                request=request,
                identity_service=identity_service,
                ensure_allowed=ensure_allowed,
                _retry_on_integrity=False,
            )
        raise HTTPException(status_code=409, detail="Conflit d'enrichissement adverse.") from exc
    except (ValueError, TypeError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflit d'enrichissement adverse.") from exc


def _rate(made: int, opportunities: int) -> dict[str, object]:
    return {
        "made": made,
        "opportunities": opportunities,
        "percent": made / opportunities * 100 if opportunities else None,
    }


def _metrics(
    rows: list[tuple[SharedOpponentObservation, SharedHand, SharedTournament]],
) -> dict[str, object]:
    observations = [row[0] for row in rows]
    hands = len(observations)
    aggressive = sum(row.postflop_aggressive_actions for row in observations)
    calls = sum(row.postflop_calls for row in observations)
    checks = sum(row.postflop_checks for row in observations)
    folds = sum(row.postflop_folds for row in observations)
    aggression_opportunities = aggressive + calls + checks + folds
    saw_flop = sum(row.saw_flop for row in observations)
    went_showdown = sum(row.went_showdown for row in observations)
    known_net = [row.net for row in observations if row.net is not None]
    preflop_known = sum(row.preflop_known for row in observations)
    return {
        "tournaments": len({row[2].id for row in rows}),
        "hands": hands,
        "contributors": len({row[2].member_id for row in rows}),
        "net_chips": sum(known_net),
        "known_net_hands": len(known_net),
        "preflop_known_hands": preflop_known,
        "vpip": _rate(sum(row.vpip for row in observations), preflop_known),
        "pfr": _rate(sum(row.pfr for row in observations), preflop_known),
        "limp": _rate(sum(row.limp for row in observations), preflop_known),
        "three_bet": _rate(
            sum(row.three_bet for row in observations),
            sum(row.faced_open for row in observations),
        ),
        "shove": _rate(sum(row.shove for row in observations), preflop_known),
        "aggression": {
            "aggressive_actions": aggressive,
            "calls": calls,
            "checks": checks,
            "folds": folds,
            "opportunities": aggression_opportunities,
            "frequency_percent": (
                aggressive / aggression_opportunities * 100
                if aggression_opportunities
                else None
            ),
            "factor": aggressive / calls if calls else None,
        },
        "wtsd": _rate(went_showdown, saw_flop),
        "wsd": _rate(
            sum(row.won_showdown for row in observations), went_showdown
        ),
        "all_in": _rate(sum(row.is_all_in for row in observations), hands),
    }


def _visible_observation_query(opponent_id: int):  # type: ignore[no-untyped-def]
    return (
        select(SharedOpponentObservation, SharedHand, SharedTournament)
        .join(
            SharedTournamentOpponent,
            SharedTournamentOpponent.id
            == SharedOpponentObservation.tournament_opponent_id,
        )
        .join(SharedHand, SharedHand.id == SharedOpponentObservation.shared_hand_id)
        .join(SharedTournament, SharedTournament.id == SharedTournamentOpponent.tournament_id)
        .join(Member, Member.id == SharedTournament.member_id)
        .where(
            SharedTournamentOpponent.opponent_id == opponent_id,
            Member.disabled_at.is_(None),
        )
    )


def list_opponents(
    db: Session,
    identity_service: OpponentIdentityService,
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    visible = (
        select(
            Opponent,
            func.min(SharedTournament.started_at),
            func.max(SharedTournament.started_at),
            func.count(func.distinct(SharedTournament.id)),
            func.count(func.distinct(SharedOpponentObservation.shared_hand_id)),
            func.count(func.distinct(Member.id)),
        )
        .join(SharedTournamentOpponent, SharedTournamentOpponent.opponent_id == Opponent.id)
        .join(SharedTournament, SharedTournament.id == SharedTournamentOpponent.tournament_id)
        .join(Member, Member.id == SharedTournament.member_id)
        .outerjoin(
            SharedOpponentObservation,
            SharedOpponentObservation.tournament_opponent_id
            == SharedTournamentOpponent.id,
        )
        .where(Member.disabled_at.is_(None))
        .group_by(Opponent.id)
    )
    total = int(
        db.scalar(
            select(func.count(func.distinct(Opponent.id)))
            .join(SharedTournamentOpponent, SharedTournamentOpponent.opponent_id == Opponent.id)
            .join(SharedTournament, SharedTournament.id == SharedTournamentOpponent.tournament_id)
            .join(Member, Member.id == SharedTournament.member_id)
            .where(Member.disabled_at.is_(None))
        )
        or 0
    )
    rows = db.execute(
        visible.order_by(func.max(SharedTournament.started_at).desc(), Opponent.public_id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = []
    try:
        for opponent, first_seen, last_seen, tournaments, hands, contributors in rows:
            items.append(
                {
                    "public_id": opponent.public_id,
                    "display_name": identity_service.decrypt(
                        identity_key=opponent.identity_key,
                        ciphertext=opponent.display_ciphertext,
                        nonce=opponent.display_nonce,
                        key_version=opponent.key_version,
                    ),
                    "first_seen_at": _public_datetime(first_seen),
                    "last_seen_at": _public_datetime(last_seen),
                    "tournaments": int(tournaments),
                    "hands": int(hands),
                    "contributors": int(contributors),
                }
            )
    except OpponentIdentityError as exc:
        raise HTTPException(status_code=503, detail="Identite adverse indisponible.") from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _depth_bucket(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value < 5:
        return "0-5 BB"
    if value < 10:
        return "5-10 BB"
    if value < 15:
        return "10-15 BB"
    if value < 25:
        return "15-25 BB"
    return "25+ BB"


def opponent_profile(
    db: Session,
    public_id: str,
    identity_service: OpponentIdentityService,
) -> dict[str, object]:
    opponent = db.scalar(select(Opponent).where(Opponent.public_id == public_id))
    if opponent is None:
        raise HTTPException(status_code=404, detail="Adversaire introuvable.")
    rows = list(db.execute(_visible_observation_query(opponent.id)).all())
    visible_dates = db.execute(
        select(
            func.min(SharedTournament.started_at),
            func.max(SharedTournament.started_at),
        )
        .join(
            SharedTournamentOpponent,
            SharedTournamentOpponent.tournament_id == SharedTournament.id,
        )
        .join(Member, Member.id == SharedTournament.member_id)
        .where(
            SharedTournamentOpponent.opponent_id == opponent.id,
            Member.disabled_at.is_(None),
        )
    ).one()
    if visible_dates[0] is None or visible_dates[1] is None:
        raise HTTPException(status_code=404, detail="Adversaire introuvable.")
    try:
        display_name = identity_service.decrypt(
            identity_key=opponent.identity_key,
            ciphertext=opponent.display_ciphertext,
            nonce=opponent.display_nonce,
            key_version=opponent.key_version,
        )
    except OpponentIdentityError as exc:
        raise HTTPException(status_code=503, detail="Identite adverse indisponible.") from exc

    position_groups: dict[str, list] = {}
    depth_groups: dict[str, list] = {}
    for row in rows:
        position_groups.setdefault(row[0].position or "UNKNOWN", []).append(row)
        depth_groups.setdefault(_depth_bucket(row[0].stack_bb), []).append(row)
    position_order = {value: index for index, value in enumerate(("BTN", "SB", "BB", "UNKNOWN"))}
    depth_order = {
        value: index
        for index, value in enumerate(
            ("0-5 BB", "5-10 BB", "10-15 BB", "15-25 BB", "25+ BB", "unknown")
        )
    }
    recent = sorted(rows, key=lambda row: (row[1].played_at, row[0].id), reverse=True)[:20]
    return {
        "identity": {
            "public_id": opponent.public_id,
            "display_name": display_name,
            "first_seen_at": _public_datetime(visible_dates[0]),
            "last_seen_at": _public_datetime(visible_dates[1]),
        },
        "summary": _metrics(rows),
        "by_position": [
            {**_metrics(group), "position": position, "bucket": None}
            for position, group in sorted(
                position_groups.items(), key=lambda item: position_order.get(item[0], 99)
            )
        ],
        "by_depth": [
            {**_metrics(group), "position": None, "bucket": bucket}
            for bucket, group in sorted(
                depth_groups.items(), key=lambda item: depth_order.get(item[0], 99)
            )
        ],
        "recent_observations": [
            {
                "hand_id": hand.public_id,
                "tournament_id": tournament.public_id,
                "played_at": _public_datetime(hand.played_at),
                "position": observation.position,
                "stack_bb": (
                    float(observation.stack_bb) if observation.stack_bb is not None else None
                ),
                "invested": observation.invested,
                "won": observation.won,
                "net": observation.net,
                "showed": observation.showed,
                "is_winner": observation.is_winner,
                "is_all_in": observation.is_all_in,
                "preflop_known": observation.preflop_known,
                "vpip": observation.vpip,
                "pfr": observation.pfr,
                "limp": observation.limp,
                "faced_open": observation.faced_open,
                "three_bet": observation.three_bet,
                "shove": observation.shove,
                "postflop_aggressive_actions": observation.postflop_aggressive_actions,
                "postflop_calls": observation.postflop_calls,
                "postflop_checks": observation.postflop_checks,
                "postflop_folds": observation.postflop_folds,
                "saw_flop": observation.saw_flop,
                "went_showdown": observation.went_showdown,
                "won_showdown": observation.won_showdown,
            }
            for observation, hand, tournament in recent
        ],
    }


def suppress_opponent(db: Session, *, public_id: str, confirmation: str) -> None:
    if confirmation != "DELETE":
        raise ValueError("Suppression refusee : --confirm DELETE est requis.")
    opponent = db.scalar(select(Opponent).where(Opponent.public_id == public_id))
    if opponent is None:
        raise ValueError("Adversaire introuvable.")
    if db.scalar(
        select(OpponentSuppression.id).where(
            OpponentSuppression.identity_key == opponent.identity_key
        )
    ) is None:
        db.add(OpponentSuppression(identity_key=opponent.identity_key))
    db.delete(opponent)
    db.commit()


def purge_inactive_opponents(db: Session, *, retention_days: int) -> int:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=retention_days)
    ids = list(db.scalars(select(Opponent.id).where(Opponent.last_seen_at < cutoff)))
    if ids:
        db.execute(delete(Opponent).where(Opponent.id.in_(ids)))
        db.commit()
    return len(ids)
