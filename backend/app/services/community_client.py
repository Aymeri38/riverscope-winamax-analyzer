from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.community_secret import (
    CommunitySecretError,
    CommunitySecretStore,
    CommunitySecrets,
    DpapiCommunitySecretStore,
)
from app.core.process_guard import analysis_interlock
from app.models import CommunitySyncRecord, Hand, HandPlayer, Tournament, TournamentPlayer
from app.schemas.community import (
    COMMUNITY_CONSENT_VERSION,
    COMMUNITY_SCHEMA_VERSION,
    CommunityActionPayload,
    CommunityEnrollmentResponse,
    CommunityHandPayload,
    CommunityJoinRequest,
    CommunityLocalConfig,
    CommunityMeResponse,
    CommunityPlayerPayload,
    CommunityStatusResponse,
    CommunitySyncHubResponse,
    CommunitySyncResponse,
    CommunityTournamentData,
    CommunityTournamentPayload,
)
from app.services.activity_guard import detect_active_tournaments
from app.services.settings import (
    delete_community_config,
    load_community_config,
    load_settings,
    save_community_config,
)


class CommunityError(RuntimeError):
    code = "community_error"


class CommunityNotConfiguredError(CommunityError):
    code = "not_configured"


class CommunityAlreadyConfiguredError(CommunityError):
    code = "already_configured"


class CommunityConfigurationError(CommunityError):
    code = "invalid_community_configuration"


class CommunityActivityError(CommunityError):
    code = "post_session_guard"


class CommunityPendingError(CommunityError):
    code = "pending_sync"


class CommunityContributionRequiredError(CommunityError):
    code = "no_contribution"


class CommunityOfflineError(CommunityError):
    code = "hub_offline"


class CommunityResourceNotFoundError(CommunityError):
    code = "resource_not_found"


class CommunityRemoteError(CommunityError):
    code = "hub_rejected"

    def __init__(self, code: str = "hub_rejected") -> None:
        super().__init__(code)
        self.code = code


_FORBIDDEN_PUBLIC_RESPONSE_KEYS = frozenset(
    {"token", "device_token", "access_token", "invite", "invite_token", "hub_url", "url"}
)


def _assert_public_hub_response(value: Any, access_token: str) -> None:
    """Prevent a hub regression from reflecting connection secrets to React."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).casefold() in _FORBIDDEN_PUBLIC_RESPONSE_KEYS:
                raise CommunityRemoteError("unsafe_proxy_response")
            _assert_public_hub_response(nested, access_token)
    elif isinstance(value, list):
        for nested in value:
            _assert_public_hub_response(nested, access_token)
    elif isinstance(value, str) and access_token and access_token in value:
        raise CommunityRemoteError("unsafe_proxy_response")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_community_post_session(db: Session) -> None:
    """Fail closed without reading Winamax memory, windows, traffic, or files beyond histories."""
    analysis_interlock.ensure_allowed()
    if detect_active_tournaments(load_settings(db))["active"]:
        raise CommunityActivityError("Une partie est active ou potentiellement active.")
    analysis_interlock.ensure_allowed()


def _canonical_bytes(payload: CommunityTournamentPayload) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _client_key(client_secret: bytes, external_tournament_id: str) -> str:
    return hmac.new(
        client_secret,
        external_tournament_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


_CARD_PATTERN = re.compile(r"([2-9TJQKA])([cdhs])", re.IGNORECASE)
_POSITIONS = frozenset({"BTN", "SB", "BB", "UTG", "CO", "MP"})
_STREETS = frozenset({"PREFLOP", "FLOP", "TURN", "RIVER", "SHOWDOWN"})
_ACTION_TYPES = {
    "post_small_blind": "POST_SB",
    "post_big_blind": "POST_BB",
    "post_ante": "POST_ANTE",
    "fold": "FOLD",
    "check": "CHECK",
    "call": "CALL",
    "bet": "BET",
    "raise": "RAISE",
    "all_in": "ALL_IN",
    "collect": "COLLECT",
    "show": "SHOW",
    "muck": "MUCK",
    "uncalled_return": "UNCALLED_RETURN",
}


def _cards_from_text(value: str | None) -> list[str]:
    if not value:
        return []
    return [f"{rank.upper()}{suit.lower()}" for rank, suit in _CARD_PATTERN.findall(value)]


def _money(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def _as_utc(value: datetime) -> datetime:
    """The importer normalizes persisted naive timestamps to UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _tournament_aliases(tournament: Tournament) -> dict[int, str]:
    player_ids: list[int] = []
    hero_ids: set[int] = set()
    for entry in sorted(tournament.players, key=lambda item: (item.id, item.player_id)):
        if entry.player.is_hero or entry.player.display_name == tournament.hero_name:
            hero_ids.add(entry.player_id)
        elif entry.player_id not in player_ids:
            player_ids.append(entry.player_id)
    for hand in sorted(tournament.hands, key=lambda item: (item.hand_number, item.id)):
        for entry in sorted(hand.player_entries, key=lambda item: (item.seat, item.player_id)):
            if entry.player.is_hero or entry.player.display_name == tournament.hero_name:
                hero_ids.add(entry.player_id)
            elif entry.player_id not in player_ids:
                player_ids.append(entry.player_id)
    aliases = {player_id: "HERO" for player_id in hero_ids}
    aliases.update(
        {player_id: f"OPPONENT_{index}" for index, player_id in enumerate(player_ids, start=1)}
    )
    return aliases


def serialize_completed_tournament(
    tournament: Tournament,
    client_secret: bytes,
) -> CommunityTournamentPayload:
    """Serialize the strict hub allowlist; raw identifiers and free text never enter it."""
    if not tournament.completed or tournament.ended_at is None or tournament.final_rank is None:
        raise ValueError("Seuls les tournois terminés sont sérialisables")
    if not tournament.is_expresso:
        raise ValueError("Seuls les tournois Expresso sont partageables")

    aliases = _tournament_aliases(tournament)
    hands: list[CommunityHandPayload] = []
    sorted_hands = sorted(tournament.hands, key=lambda item: (item.hand_number, item.played_at))
    for hand_ordinal, hand in enumerate(sorted_hands, start=1):
        hero_cards = [
            f"{card.rank.upper()}{card.suit.lower()}"
            for card in sorted(hand.hero_hole_cards, key=lambda item: item.position)
        ]
        board = [
            f"{card.rank.upper()}{card.suit.lower()}"
            for card in sorted(hand.board_cards, key=lambda item: item.position)
        ]
        players: list[CommunityPlayerPayload] = []
        for entry in sorted(hand.player_entries, key=lambda item: (item.seat, item.player_id)):
            alias = aliases.get(entry.player_id)
            if alias is None:
                # This is deterministic within the tournament and cannot reveal a pseudo.
                opponent_count = sum(value.startswith("OPPONENT_") for value in aliases.values())
                alias = f"OPPONENT_{opponent_count + 1}"
                aliases[entry.player_id] = alias
            exposed_cards: list[str] | None
            if alias == "HERO":
                exposed_cards = hero_cards or _cards_from_text(entry.hole_cards) or None
            elif entry.showed:
                exposed_cards = _cards_from_text(entry.hole_cards) or None
            else:
                exposed_cards = None
            players.append(
                CommunityPlayerPayload(
                    alias=alias,
                    seat=entry.seat,
                    position=(entry.position or "").upper()
                    if (entry.position or "").upper() in _POSITIONS
                    else "UNKNOWN",
                    starting_stack=entry.starting_stack,
                    ending_stack=entry.ending_stack,
                    invested=entry.invested,
                    won=entry.won,
                    net=entry.net,
                    hole_cards=exposed_cards,
                    showed=entry.showed,
                    is_winner=entry.is_winner,
                    is_all_in=entry.is_all_in,
                )
            )
        actions: list[CommunityActionPayload] = []
        for action in sorted(hand.actions, key=lambda item: item.sequence):
            action_type = _ACTION_TYPES.get(action.action_type.casefold())
            street = action.street.upper()
            if action_type is None or street not in _STREETS:
                continue
            actions.append(
                CommunityActionPayload(
                    sequence=len(actions) + 1,
                    actor_alias=aliases.get(action.player_id, "OPPONENT_1"),
                    street=street,
                    action_type=action_type,
                    amount=action.amount,
                    to_amount=action.to_amount,
                    pot_after=action.pot_after,
                    is_all_in=action.is_all_in,
                )
            )
        hands.append(
            CommunityHandPayload(
                # Public ordinal only: the raw Winamax hand number is never transmitted.
                hand_number=hand_ordinal,
                played_at=_as_utc(hand.played_at),
                level=hand.level,
                small_blind=hand.small_blind,
                big_blind=hand.big_blind,
                ante=hand.ante,
                button_seat=hand.button_seat,
                max_players=hand.max_players,
                active_players=hand.active_players,
                total_pot=hand.total_pot,
                hero_net=hand.hero_net,
                is_all_in=hand.is_all_in,
                reached_showdown=hand.reached_showdown,
                hero_cards=hero_cards,
                board=board,
                players=players,
                actions=actions,
            )
        )

    return CommunityTournamentPayload(
        client_key=_client_key(client_secret, tournament.external_id),
        tournament=CommunityTournamentData(
            started_at=_as_utc(tournament.started_at),
            ended_at=_as_utc(tournament.ended_at),
            format="EXPRESSO",
            is_nitro=tournament.is_nitro,
            currency=tournament.currency.upper(),
            total_buyin=float(tournament.total_buyin),
            multiplier=_money(tournament.multiplier),
            prize_pool=float(tournament.prize_pool),
            reward=float(tournament.reward),
            final_rank=tournament.final_rank,
            duration_seconds=tournament.duration_seconds
            if tournament.duration_seconds is not None
            else max(0, int((tournament.ended_at - tournament.started_at).total_seconds())),
            total_hands=len(hands),
            registered_players=tournament.registered_players,
            initial_stack=tournament.initial_stack,
            final_stack=tournament.final_stack,
            chip_delta=tournament.chip_delta,
            hands=hands,
        ),
    )


def _completed_tournaments(
    db: Session,
    tournament_ids: list[int] | None = None,
) -> list[Tournament]:
    statement = (
        select(Tournament)
        .where(
            Tournament.completed.is_(True),
            Tournament.is_expresso.is_(True),
            Tournament.ended_at.is_not(None),
            Tournament.final_rank.is_not(None),
        )
        .options(
            selectinload(Tournament.players).joinedload(TournamentPlayer.player),
            selectinload(Tournament.hands).selectinload(Hand.player_entries).joinedload(
                HandPlayer.player
            ),
            selectinload(Tournament.hands).selectinload(Hand.actions),
            selectinload(Tournament.hands).selectinload(Hand.board_cards),
            selectinload(Tournament.hands).selectinload(Hand.hero_hole_cards),
        )
        .order_by(Tournament.started_at, Tournament.id)
    )
    if tournament_ids is not None:
        if not tournament_ids:
            return []
        statement = statement.where(Tournament.id.in_(tournament_ids))
    return list(
        db.scalars(statement)
        .unique()
        .all()
    )


class CommunityClient:
    def __init__(
        self,
        *,
        secret_store: CommunitySecretStore | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 8.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        total_response_timeout_seconds: float = 30.0,
        ca_cert_path: Path | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be at least 1024")
        if total_response_timeout_seconds <= 0:
            raise ValueError("total_response_timeout_seconds must be positive")
        self.secret_store = secret_store or DpapiCommunitySecretStore()
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._total_response_timeout_seconds = total_response_timeout_seconds
        configured_ca = os.environ.get("WXA_COMMUNITY_CA_CERT")
        self._ca_cert_path = ca_cert_path or (Path(configured_ca) if configured_ca else None)
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()

    def _http(self) -> httpx.Client:
        verify: bool | ssl.SSLContext = True
        if self._ca_cert_path is not None:
            ca_path = self._ca_cert_path.expanduser()
            if not ca_path.is_file():
                raise CommunityConfigurationError("community_ca_not_found")
            try:
                context = ssl.create_default_context()
                context.load_verify_locations(cafile=str(ca_path))
            except (OSError, ssl.SSLError) as exc:
                raise CommunityConfigurationError("community_ca_invalid") from exc
            verify = context
        return httpx.Client(
            transport=self._transport,
            timeout=self._timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            verify=verify,
            headers={"User-Agent": "Winamax-Analyzer-Community/1"},
        )

    @staticmethod
    def _endpoint(config_value: CommunityLocalConfig, path: str) -> str:
        if not config_value.hub_url:
            raise CommunityNotConfiguredError()
        return f"{config_value.hub_url.rstrip('/')}{path}"

    @staticmethod
    def _auth_headers(secrets_value: CommunitySecrets) -> dict[str, str]:
        return {"Authorization": f"Bearer {secrets_value.access_token}"}

    def _request_json(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        accepted_statuses: set[int],
        **kwargs: Any,
    ) -> tuple[int, Any | None]:
        """Read a decoded response through a hard cap, including compressed bodies."""
        deadline = self._clock() + self._total_response_timeout_seconds
        with client.stream(method, url, **kwargs) as response:
            if self._clock() > deadline:
                raise CommunityRemoteError("response_deadline_exceeded")
            status_code = response.status_code
            if status_code not in accepted_statuses:
                return status_code, None
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                    if declared_size < 0:
                        raise ValueError("negative content length")
                    if declared_size > self._max_response_bytes:
                        raise CommunityRemoteError("response_too_large")
                except ValueError as exc:
                    raise CommunityRemoteError("invalid_content_length") from exc
            payload = bytearray()
            for chunk in response.iter_bytes():
                if self._clock() > deadline:
                    raise CommunityRemoteError("response_deadline_exceeded")
                payload.extend(chunk)
                if len(payload) > self._max_response_bytes:
                    raise CommunityRemoteError("response_too_large")
        try:
            return status_code, json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CommunityRemoteError("invalid_json_response") from exc

    def _request_status(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> int:
        # The body is deliberately not buffered. Closing the stream aborts an
        # unexpectedly large response from a compromised hub.
        deadline = self._clock() + self._total_response_timeout_seconds
        with client.stream(method, url, **kwargs) as response:
            if self._clock() > deadline:
                raise CommunityRemoteError("response_deadline_exceeded")
            return response.status_code

    def join(self, db: Session, request: CommunityJoinRequest) -> dict[str, Any]:
        ensure_community_post_session(db)
        with self._lock:
            existing_config = load_community_config(db)
            if existing_config.enabled or self.secret_store.load() is not None:
                raise CommunityAlreadyConfiguredError()
            body = {
                "invite_token": request.invite.get_secret_value(),
                "display_name": request.display_name,
                "device_label": "Windows PC",
                "policy_version": request.consent_version,
                "consent": request.consent,
            }
            try:
                with self._http() as client:
                    response_status, response_data = self._request_json(
                        client,
                        "POST",
                        f"{request.hub_url}/v1/enroll",
                        accepted_statuses={200, 201},
                        json=body,
                    )
            except httpx.RequestError as exc:
                raise CommunityOfflineError() from exc
            if response_status not in {200, 201}:
                raise CommunityRemoteError(f"enroll_http_{response_status}")
            try:
                enrollment = CommunityEnrollmentResponse.model_validate(response_data)
            except ValueError as exc:
                raise CommunityRemoteError("invalid_enrollment_response") from exc
            ensure_community_post_session(db)
            secrets_value = CommunitySecrets(
                access_token=enrollment.device_token.get_secret_value(),
                client_secret=secrets.token_bytes(32),
            )
            self.secret_store.save(secrets_value)
            config_value = CommunityLocalConfig(
                enabled=True,
                hub_url=request.hub_url,
                consent_version=request.consent_version,
                enrolled_at=utcnow(),
                last_contact_at=utcnow(),
            )
            save_community_config(db, config_value)
            db.execute(delete(CommunitySyncRecord))
            db.commit()
            self.enqueue_completed(db, secrets_value=secrets_value)
            return self.status(db).model_dump(mode="json")

    def leave(self, db: Session) -> bool:
        ensure_community_post_session(db)
        with self._lock:
            config_value = load_community_config(db)
            try:
                credentials = self.secret_store.load()
            except CommunitySecretError:
                # A corrupt DPAPI blob must remain locally recoverable through
                # leave; it cannot be used for remote revocation.
                credentials = None
            remote_revoked = False
            if config_value.enabled and config_value.hub_url and credentials is not None:
                try:
                    with self._http() as client:
                        response_status = self._request_status(
                            client,
                            "DELETE",
                            self._endpoint(config_value, "/v1/device"),
                            headers=self._auth_headers(credentials),
                        )
                    remote_revoked = response_status in {200, 204}
                except (httpx.RequestError, CommunityError):
                    remote_revoked = False
                ensure_community_post_session(db)
            self.secret_store.delete()
            db.execute(delete(CommunitySyncRecord))
            delete_community_config(db)
            db.commit()
        ensure_community_post_session(db)
        return remote_revoked

    def enqueue_completed(
        self,
        db: Session,
        *,
        secrets_value: CommunitySecrets | None = None,
    ) -> int:
        config_value = load_community_config(db)
        if not config_value.enabled:
            return 0
        credentials = secrets_value or self.secret_store.load()
        if credentials is None:
            raise CommunityNotConfiguredError()
        queued = 0
        candidate_ids = list(
            db.scalars(
                select(Tournament.id)
                .outerjoin(
                    CommunitySyncRecord,
                    CommunitySyncRecord.tournament_id == Tournament.id,
                )
                .where(
                    Tournament.completed.is_(True),
                    Tournament.is_expresso.is_(True),
                    Tournament.ended_at.is_not(None),
                    Tournament.final_rank.is_not(None),
                    (
                        (CommunitySyncRecord.id.is_(None))
                        | (CommunitySyncRecord.schema_version != COMMUNITY_SCHEMA_VERSION)
                    ),
                )
            ).all()
        )
        if not candidate_ids:
            return 0
        existing = {
            record.tournament_id: record
            for record in db.scalars(
                select(CommunitySyncRecord).where(
                    CommunitySyncRecord.tournament_id.in_(candidate_ids)
                )
            ).all()
        }
        for tournament in _completed_tournaments(db, candidate_ids):
            analysis_interlock.ensure_allowed()
            payload = serialize_completed_tournament(tournament, credentials.client_secret)
            digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
            record = existing.get(tournament.id)
            if record is None:
                db.add(
                    CommunitySyncRecord(
                        tournament_id=tournament.id,
                        client_key=payload.client_key,
                        schema_version=COMMUNITY_SCHEMA_VERSION,
                        payload_sha256=digest,
                        state="pending",
                    )
                )
                queued += 1
            elif record.payload_sha256 != digest or record.client_key != payload.client_key:
                record.client_key = payload.client_key
                record.schema_version = COMMUNITY_SCHEMA_VERSION
                record.payload_sha256 = digest
                record.state = "pending"
                record.synced_at = None
                record.remote_public_id = None
                record.last_error_code = None
                queued += 1
        db.commit()
        return queued

    def sync(self, db: Session) -> CommunitySyncResponse:
        ensure_community_post_session(db)
        with self._lock:
            config_value = load_community_config(db)
            credentials = self.secret_store.load()
            if not config_value.enabled or credentials is None:
                raise CommunityNotConfiguredError()
            queued = self.enqueue_completed(db, secrets_value=credentials)
            records = list(
                db.scalars(
                    select(CommunitySyncRecord)
                    .where(CommunitySyncRecord.state == "pending")
                    .order_by(CommunitySyncRecord.id)
                ).all()
            )
            delivered = 0
            online = True
            last_error: str | None = None
            remote_has_contribution = config_value.remote_has_contribution
            if not records:
                try:
                    with self._http() as client:
                        probe_status, probe_data = self._request_json(
                            client,
                            "GET",
                            self._endpoint(config_value, "/v1/me"),
                            accepted_statuses={200},
                            headers=self._auth_headers(credentials),
                        )
                except CommunityRemoteError as exc:
                    last_error = exc.code
                except httpx.RequestError:
                    online = False
                    last_error = "hub_offline"
                else:
                    if probe_status == 200:
                        try:
                            me = CommunityMeResponse.model_validate(probe_data)
                        except ValueError:
                            last_error = "invalid_me_response"
                        else:
                            remote_has_contribution = me.has_contribution
                    else:
                        last_error = f"probe_http_{probe_status}"
            for record in records:
                ensure_community_post_session(db)
                tournament = db.scalar(
                    select(Tournament)
                    .where(Tournament.id == record.tournament_id)
                    .options(
                        selectinload(Tournament.players).joinedload(TournamentPlayer.player),
                        selectinload(Tournament.hands)
                        .selectinload(Hand.player_entries)
                        .joinedload(HandPlayer.player),
                        selectinload(Tournament.hands).selectinload(Hand.actions),
                        selectinload(Tournament.hands).selectinload(Hand.board_cards),
                        selectinload(Tournament.hands).selectinload(Hand.hero_hole_cards),
                    )
                )
                if tournament is None or not tournament.completed:
                    continue
                payload = serialize_completed_tournament(tournament, credentials.client_secret)
                record.attempts += 1
                record.last_attempt_at = utcnow()
                try:
                    headers = self._auth_headers(credentials)
                    headers["Content-Type"] = "application/json"
                    with self._http() as client:
                        response_status, response_data = self._request_json(
                            client,
                            "POST",
                            self._endpoint(config_value, "/v1/sync/tournaments"),
                            accepted_statuses={200, 201},
                            headers=headers,
                            content=_canonical_bytes(payload),
                        )
                except CommunityRemoteError as exc:
                    last_error = exc.code
                    record.last_error_code = last_error
                    db.commit()
                    break
                except httpx.RequestError:
                    online = False
                    last_error = "hub_offline"
                    record.last_error_code = last_error
                    db.commit()
                    break
                if response_status not in {200, 201}:
                    last_error = f"sync_http_{response_status}"
                    record.last_error_code = last_error
                    db.commit()
                    break
                try:
                    hub_result = CommunitySyncHubResponse.model_validate(response_data)
                except ValueError:
                    last_error = "invalid_sync_response"
                    record.last_error_code = last_error
                    db.commit()
                    break
                ensure_community_post_session(db)
                record.state = "synced"
                record.synced_at = utcnow()
                record.remote_public_id = hub_result.public_id
                record.last_error_code = None
                delivered += 1
                remote_has_contribution = True
                db.commit()

            pending = int(
                db.scalar(
                    select(func.count()).select_from(CommunitySyncRecord).where(
                        CommunitySyncRecord.state == "pending"
                    )
                )
                or 0
            )
            synced_total = int(
                db.scalar(
                    select(func.count()).select_from(CommunitySyncRecord).where(
                        CommunitySyncRecord.state == "synced"
                    )
                )
                or 0
            )
            now = utcnow()
            config_value = load_community_config(db).model_copy(
                update={
                    "last_sync_at": now if delivered else config_value.last_sync_at,
                    "last_contact_at": now if online else config_value.last_contact_at,
                    "last_error_code": last_error,
                    "remote_has_contribution": remote_has_contribution,
                }
            )
            ensure_community_post_session(db)
            save_community_config(db, config_value)
            return CommunitySyncResponse(
                queued=queued,
                synced=delivered,
                pending=pending,
                online=online,
                available=online
                and pending == 0
                and (synced_total > 0 or remote_has_contribution)
                and last_error is None,
                error_code=last_error,
            )

    def status(self, db: Session) -> CommunityStatusResponse:
        with self._lock:
            return self._status_unlocked(db)

    def _status_unlocked(self, db: Session) -> CommunityStatusResponse:
        ensure_community_post_session(db)
        config_value = load_community_config(db)
        credentials = self.secret_store.load()
        credentials_present = credentials is not None
        if config_value.enabled and credentials is not None:
            self.enqueue_completed(db, secrets_value=credentials)
        pending = int(
            db.scalar(
                select(func.count()).select_from(CommunitySyncRecord).where(
                    CommunitySyncRecord.state == "pending"
                )
            )
            or 0
        )
        synced = int(
            db.scalar(
                select(func.count()).select_from(CommunitySyncRecord).where(
                    CommunitySyncRecord.state == "synced"
                )
            )
            or 0
        )
        configured = bool(config_value.enabled and credentials_present)
        online: bool | None = None
        if config_value.last_error_code:
            online = False
        elif config_value.last_contact_at:
            online = True
        reason: str | None = None
        if not configured:
            reason = "not_configured"
        elif pending:
            reason = "pending_sync"
        elif online is False:
            reason = "hub_offline"
        elif synced == 0 and not config_value.remote_has_contribution:
            reason = "no_contribution"
        result = CommunityStatusResponse(
            configured=configured,
            available=configured
            and pending == 0
            and (synced > 0 or config_value.remote_has_contribution)
            and online is True,
            online=online,
            pending=pending,
            synced=synced,
            last_sync_at=config_value.last_sync_at,
            consent_version=COMMUNITY_CONSENT_VERSION,
            blocked_reason=reason,
        )
        ensure_community_post_session(db)
        return result

    def proxy_get(
        self,
        db: Session,
        path: str,
        *,
        params: dict[str, str | int | None] | None = None,
    ) -> Any:
        ensure_community_post_session(db)
        with self._lock:
            config_value = load_community_config(db)
            credentials = self.secret_store.load()
            if not config_value.enabled or credentials is None:
                raise CommunityNotConfiguredError()
            self.enqueue_completed(db, secrets_value=credentials)
            pending = int(
                db.scalar(
                    select(func.count()).select_from(CommunitySyncRecord).where(
                        CommunitySyncRecord.state == "pending"
                    )
                )
                or 0
            )
            if pending:
                raise CommunityPendingError()
            synced = int(
                db.scalar(
                    select(func.count()).select_from(CommunitySyncRecord).where(
                        CommunitySyncRecord.state == "synced"
                    )
                )
                or 0
            )
            if synced == 0 and not config_value.remote_has_contribution:
                raise CommunityContributionRequiredError()
            safe_params = {key: value for key, value in (params or {}).items() if value is not None}
            try:
                with self._http() as client:
                    response_status, data = self._request_json(
                        client,
                        "GET",
                        self._endpoint(config_value, path),
                        accepted_statuses={200},
                        headers=self._auth_headers(credentials),
                        params=safe_params,
                    )
            except CommunityRemoteError as exc:
                self._record_connection_result(db, config_value, error=exc.code)
                raise
            except httpx.RequestError as exc:
                self._record_connection_result(db, config_value, error="hub_offline")
                raise CommunityOfflineError() from exc
            if response_status != 200:
                if response_status == 404:
                    self._record_connection_result(db, config_value, error=None)
                    raise CommunityResourceNotFoundError()
                code = f"proxy_http_{response_status}"
                self._record_connection_result(db, config_value, error=code)
                raise CommunityRemoteError(code)
            try:
                _assert_public_hub_response(data, credentials.access_token)
            except CommunityRemoteError:
                self._record_connection_result(db, config_value, error="unsafe_proxy_response")
                raise
            ensure_community_post_session(db)
            self._record_connection_result(db, config_value, error=None)
            return data

    @staticmethod
    def _record_connection_result(
        db: Session,
        config_value: CommunityLocalConfig,
        *,
        error: str | None,
    ) -> None:
        save_community_config(
            db,
            config_value.model_copy(
                update={
                    "last_contact_at": utcnow() if error is None else config_value.last_contact_at,
                    "last_error_code": error,
                }
            ),
        )


def sync_community_after_rescan(db: Session, client: CommunityClient) -> CommunitySyncResponse | None:
    """Best-effort offline queue: imports never fail because the personal hub is unavailable."""
    config_value = load_community_config(db)
    if not config_value.enabled:
        return None
    try:
        return client.sync(db)
    except (CommunityError, CommunitySecretError, OSError, ValueError):
        db.rollback()
        return None
