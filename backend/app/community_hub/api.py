from __future__ import annotations

import json
from collections.abc import Sequence

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.community_hub.config import HubConfig, MAX_BODY_BYTES, get_hub_config
from app.community_hub.database import HubDatabase
from app.community_hub.middleware import BodySizeLimitMiddleware, NoStoreMiddleware
from app.community_hub.models import Device, Member, Opponent, SharedHand, SharedTournament
from app.community_hub.opponent_identity import OpponentIdentityError, OpponentIdentityService
from app.community_hub.opponents import (
    list_opponents,
    opponent_profile,
    sync_tournament_opponents,
)
from app.community_hub.rate_limit import HubRateLimitMiddleware, InMemoryRateLimiter
from app.community_hub.schemas import (
    ContributorProfileResponse,
    ConsentUpgradeRequest,
    ConsentUpgradeResponse,
    EnrollRequest,
    EnrollResponse,
    OpponentListResponse,
    OpponentProfileResponse,
    OpponentSyncRequest,
    OpponentSyncResponse,
    SyncTournamentRequest,
    SyncTournamentResponse,
)
from app.community_hub.security import (
    AuthenticatedDevice,
    authenticate_device,
    get_hub_db,
    require_collective_access,
    require_contribution,
    require_opponent_policy,
    utcnow_naive,
)
from app.community_hub.service import (
    HAND_WITH_RELATIONS,
    TOURNAMENT_WITH_RELATIONS,
    contributor_profile,
    contributor_id_to_internal,
    dashboard,
    enroll,
    hand_summary,
    sync_tournament,
    tournament_summary,
)
from app.core.process_guard import AnalysisInterlock, analysis_interlock


def _clean_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    # Pydantic's default response echoes rejected values.  The hub deliberately
    # returns only locations and error codes, never a submitted pseudo or card.
    return [
        {
            "loc": list(error.get("loc", ())),
            "type": str(error.get("type", "validation_error")),
            "msg": "Champ refuse ou invalide.",
        }
        for error in exc.errors()
    ]


def create_hub_app(
    database: HubDatabase,
    *,
    docs_enabled: bool | None = None,
    trusted_hosts: Sequence[str] | None = None,
    interlock: AnalysisInterlock | None = None,
    hub_config: HubConfig | None = None,
) -> FastAPI:
    config = hub_config or get_hub_config()
    show_docs = config.docs_enabled if docs_enabled is None else docs_enabled
    app = FastAPI(
        title="Winamax Analyzer Community Hub",
        version="1",
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )
    app.state.hub_database = database
    app.state.hub_config = config
    app.state.process_interlock = interlock or analysis_interlock
    app.state.opponent_identity_service = (
        OpponentIdentityService(
            identity_key=config.opponent_identity_key,
            encryption_key=config.opponent_encryption_key,
            key_version=config.opponent_key_version,
        )
        if config.opponent_tracking_enabled
        and config.opponent_identity_key is not None
        and config.opponent_encryption_key is not None
        else None
    )
    if app.state.opponent_identity_service is not None:
        validation_db = database.session()
        try:
            app.state.process_interlock.ensure_allowed()
            for stored_opponent in validation_db.scalars(select(Opponent)):
                # The startup monitor is already running.  Check its one-way
                # latch before every decryption so a Winamax appearance stops
                # the validation pass instead of waiting for the whole table.
                app.state.process_interlock.ensure_allowed()
                app.state.opponent_identity_service.decrypt(
                    identity_key=stored_opponent.identity_key,
                    ciphertext=stored_opponent.display_ciphertext,
                    nonce=stored_opponent.display_nonce,
                    key_version=stored_opponent.key_version,
                )
            app.state.process_interlock.ensure_allowed()
        except OpponentIdentityError as exc:
            raise ValueError("Cle de chiffrement adverse incompatible avec la base.") from exc
        finally:
            validation_db.close()
    app.state.rate_limiter = InMemoryRateLimiter(
        max_buckets=config.rate_limit_max_buckets
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(trusted_hosts or config.trusted_hosts),
    )
    # Added last so even authentication and TrustedHost errors are non-cacheable.
    app.add_middleware(NoStoreMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        return JSONResponse(status_code=422, content={"detail": _clean_validation_errors(exc)})

    @app.middleware("http")
    async def process_interlock(request, call_next):  # type: ignore[no-untyped-def]
        if request.app.state.process_interlock.blocked:
            return JSONResponse(
                status_code=503,
                content={"detail": "Hub arrete par le verrou de securite."},
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        if request.app.state.process_interlock.blocked:
            return JSONResponse(
                status_code=503,
                content={"detail": "Hub arrete par le verrou de securite."},
                headers={"Cache-Control": "no-store"},
            )
        return response

    @app.post("/v1/enroll", response_model=EnrollResponse, status_code=201)
    def enroll_route(
        payload: EnrollRequest,
        request: Request,
        db: Session = Depends(get_hub_db),
    ) -> EnrollResponse:
        if payload.policy_version == "2" and not request.app.state.hub_config.opponent_tracking_enabled:
            raise HTTPException(status_code=503, detail="Suivi adverse indisponible.")
        member, device, raw_token = enroll(db, payload)
        return EnrollResponse(
            member_id=member.public_id,
            device_id=device.public_id,
            device_token=raw_token,
            display_name=member.display_name,
            policy_version=member.policy_version,
        )

    secure = APIRouter(prefix="/v1", dependencies=[Depends(authenticate_device)])

    @secure.post("/sync/tournaments", response_model=SyncTournamentResponse)
    def sync_route(
        payload: SyncTournamentRequest,
        response: Response,
        request: Request,
        auth: AuthenticatedDevice = Depends(authenticate_device),
        db: Session = Depends(get_hub_db),
    ) -> SyncTournamentResponse:
        limits = request.app.state.hub_config
        row, created = sync_tournament(
            db,
            auth.member_id,
            payload,
            ensure_allowed=request.app.state.process_interlock.ensure_allowed,
            max_tournaments=limits.max_tournaments_per_member,
            max_hands=limits.max_hands_per_member,
            max_payload_bytes=limits.max_payload_bytes_per_member,
            max_receipts_per_tournament=limits.max_receipts_per_tournament,
        )
        response.status_code = 201 if created else 200
        return SyncTournamentResponse(
            status="created" if created else "existing",
            public_id=row.public_id,
            hand_count=row.total_hands,
        )

    @secure.delete("/device", status_code=204)
    def revoke_current_device(
        auth: AuthenticatedDevice = Depends(authenticate_device),
        db: Session = Depends(get_hub_db),
    ) -> Response:
        device = db.get(Device, auth.device_id)
        if device is None:
            raise HTTPException(status_code=401, detail="Jeton invalide.")
        device.revoked_at = utcnow_naive()
        db.commit()
        return Response(status_code=204)

    @secure.get("/me")
    def current_member(
        request: Request,
        auth: AuthenticatedDevice = Depends(authenticate_device),
        db: Session = Depends(get_hub_db),
    ) -> dict[str, object]:
        member = db.get(Member, auth.member_id)
        if member is None:
            raise HTTPException(status_code=401, detail="Jeton invalide.")
        has_contribution = db.scalar(
            select(SharedTournament.id)
            .where(SharedTournament.member_id == member.id)
            .limit(1)
        ) is not None
        return {
            "member_id": member.public_id,
            "display_name": member.display_name,
            "has_contribution": has_contribution,
            "policy_version": member.policy_version,
            "opponent_tracking_required": request.app.state.hub_config.opponent_tracking_enabled,
        }

    @secure.post("/consent", response_model=ConsentUpgradeResponse)
    def upgrade_consent(
        payload: ConsentUpgradeRequest,
        request: Request,
        auth: AuthenticatedDevice = Depends(authenticate_device),
        db: Session = Depends(get_hub_db),
    ) -> ConsentUpgradeResponse:
        if not request.app.state.hub_config.opponent_tracking_enabled:
            raise HTTPException(status_code=503, detail="Suivi adverse indisponible.")
        member = db.get(Member, auth.member_id)
        if member is None:
            raise HTTPException(status_code=401, detail="Jeton invalide.")
        member.policy_version = payload.policy_version
        member.consented_at = utcnow_naive()
        db.commit()
        return ConsentUpgradeResponse(
            policy_version="2", opponent_tracking_enabled=True
        )

    @secure.get("/contributors", dependencies=[Depends(require_collective_access)])
    def contributors(db: Session = Depends(get_hub_db)) -> dict[str, object]:
        rows = db.execute(
            select(
                Member,
                func.count(func.distinct(SharedTournament.id)),
                func.count(func.distinct(SharedHand.id)),
            )
            .join(SharedTournament, SharedTournament.member_id == Member.id)
            .outerjoin(SharedHand, SharedHand.member_id == Member.id)
            .where(Member.disabled_at.is_(None))
            .group_by(Member.id)
            .order_by(Member.created_at.asc())
        ).all()
        return {
            "items": [
                {
                    "public_id": member.public_id,
                    "display_name": member.display_name,
                    "tournament_count": int(tournament_count),
                    "hand_count": int(hand_count),
                    "joined_at": member.created_at.isoformat() + "Z",
                }
                for member, tournament_count, hand_count in rows
            ]
        }

    @secure.get(
        "/contributors/{public_id}/profile",
        response_model=ContributorProfileResponse,
        dependencies=[Depends(require_collective_access)],
    )
    def contributor_profile_route(
        public_id: str,
        db: Session = Depends(get_hub_db),
    ) -> ContributorProfileResponse:
        # The response model is an output allowlist: an accidental player,
        # action, replay, or opponent field makes response validation fail.
        return ContributorProfileResponse.model_validate(
            contributor_profile(db, public_id)
        )

    @secure.get("/tournaments", dependencies=[Depends(require_collective_access)])
    def tournaments(
        contributor_id: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=1_000_000),
        db: Session = Depends(get_hub_db),
    ) -> dict[str, object]:
        member_id = contributor_id_to_internal(db, contributor_id)
        filters = [Member.disabled_at.is_(None)]
        if member_id is not None:
            filters.append(SharedTournament.member_id == member_id)
        total = int(
            db.scalar(
                select(func.count(SharedTournament.id))
                .join(Member, Member.id == SharedTournament.member_id)
                .where(*filters)
            )
            or 0
        )
        query = (
            select(SharedTournament)
            .join(Member, Member.id == SharedTournament.member_id)
            .options(TOURNAMENT_WITH_RELATIONS)
            .where(*filters)
            .order_by(SharedTournament.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return {
            "items": [tournament_summary(row) for row in db.scalars(query)],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @secure.get(
        "/tournaments/{public_id}", dependencies=[Depends(require_collective_access)]
    )
    def tournament_detail(public_id: str, db: Session = Depends(get_hub_db)) -> dict[str, object]:
        row = db.scalar(
            select(SharedTournament)
            .options(
                TOURNAMENT_WITH_RELATIONS,
                selectinload(SharedTournament.hands),
            )
            .join(Member, Member.id == SharedTournament.member_id)
            .where(
                SharedTournament.public_id == public_id,
                Member.disabled_at.is_(None),
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Tournoi introuvable.")
        result = tournament_summary(row)
        result["hands"] = [
            {
                "public_id": hand.public_id,
                "hand_number": hand.hand_number,
                "played_at": hand.played_at.isoformat() + "Z",
                "hero_position": hand.hero_position,
                "active_players": hand.active_players,
                "big_blind": hand.big_blind,
                "total_pot": hand.total_pot,
                "hero_net": hand.hero_net,
                "is_all_in": hand.is_all_in,
                "reached_showdown": hand.reached_showdown,
            }
            for hand in row.hands
        ]
        return result

    @secure.get("/hands", dependencies=[Depends(require_collective_access)])
    def hands(
        contributor_id: str | None = None,
        tournament_id: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=1_000_000),
        db: Session = Depends(get_hub_db),
    ) -> dict[str, object]:
        member_id = contributor_id_to_internal(db, contributor_id)
        filters = [Member.disabled_at.is_(None)]
        if member_id is not None:
            filters.append(SharedHand.member_id == member_id)
        if tournament_id is not None:
            internal_tournament_id = db.scalar(
                select(SharedTournament.id)
                .join(Member, Member.id == SharedTournament.member_id)
                .where(
                    SharedTournament.public_id == tournament_id,
                    Member.disabled_at.is_(None),
                )
            )
            if internal_tournament_id is None:
                raise HTTPException(status_code=404, detail="Tournoi introuvable.")
            filters.append(SharedHand.tournament_id == internal_tournament_id)
        total = int(
            db.scalar(
                select(func.count(SharedHand.id))
                .join(Member, Member.id == SharedHand.member_id)
                .where(*filters)
            )
            or 0
        )
        query = (
            select(SharedHand)
            .join(Member, Member.id == SharedHand.member_id)
            .options(HAND_WITH_RELATIONS)
            .where(*filters)
            .order_by(SharedHand.played_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return {
            "items": [hand_summary(row) for row in db.scalars(query)],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @secure.get(
        "/hands/{public_id}/replay", dependencies=[Depends(require_collective_access)]
    )
    def replay(public_id: str, db: Session = Depends(get_hub_db)) -> dict[str, object]:
        row = db.scalar(
            select(SharedHand)
            .options(HAND_WITH_RELATIONS)
            .join(Member, Member.id == SharedHand.member_id)
            .where(
                SharedHand.public_id == public_id,
                Member.disabled_at.is_(None),
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Main introuvable.")
        return {**hand_summary(row), "replay": json.loads(row.replay_json)}

    @secure.get("/dashboard", dependencies=[Depends(require_collective_access)])
    def dashboard_route(
        contributor_id: str | None = None,
        db: Session = Depends(get_hub_db),
    ) -> dict[str, object]:
        return dashboard(db, contributor_id_to_internal(db, contributor_id))

    def opponent_identity(request: Request) -> OpponentIdentityService:
        service = request.app.state.opponent_identity_service
        if not isinstance(service, OpponentIdentityService):
            raise HTTPException(status_code=503, detail="Suivi adverse indisponible.")
        return service

    @secure.post(
        "/sync/tournaments/{public_id}/opponents",
        response_model=OpponentSyncResponse,
        dependencies=[
            Depends(require_contribution),
            Depends(require_opponent_policy),
        ],
    )
    def sync_opponents_route(
        public_id: str,
        payload: OpponentSyncRequest,
        response: Response,
        request: Request,
        auth: AuthenticatedDevice = Depends(authenticate_device),
        db: Session = Depends(get_hub_db),
    ) -> OpponentSyncResponse:
        created, opponent_count, observation_count = sync_tournament_opponents(
            db,
            member_id=auth.member_id,
            tournament_public_id=public_id,
            request=payload,
            identity_service=opponent_identity(request),
            ensure_allowed=request.app.state.process_interlock.ensure_allowed,
        )
        response.status_code = 201 if created else 200
        return OpponentSyncResponse(
            status="created" if created else "existing",
            opponent_count=opponent_count,
            observation_count=observation_count,
        )

    @secure.get(
        "/opponents",
        response_model=OpponentListResponse,
        dependencies=[Depends(require_collective_access)],
    )
    def opponents_route(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=1_000_000),
        db: Session = Depends(get_hub_db),
    ) -> OpponentListResponse:
        return OpponentListResponse.model_validate(
            list_opponents(
                db,
                opponent_identity(request),
                limit=limit,
                offset=offset,
            )
        )

    @secure.get(
        "/opponents/{public_id}/profile",
        response_model=OpponentProfileResponse,
        dependencies=[Depends(require_collective_access)],
    )
    def opponent_profile_route(
        public_id: str,
        request: Request,
        db: Session = Depends(get_hub_db),
    ) -> OpponentProfileResponse:
        return OpponentProfileResponse.model_validate(
            opponent_profile(db, public_id, opponent_identity(request))
        )

    app.include_router(secure)
    # Added last so the limiter is the outermost user middleware. It uses the
    # direct ASGI peer and deliberately ignores proxy forwarding headers.
    app.add_middleware(
        HubRateLimitMiddleware,
        limiter=app.state.rate_limiter,
        enroll_per_minute=config.rate_limit_enroll_per_minute,
        sync_per_minute=config.rate_limit_sync_per_minute,
        other_per_minute=config.rate_limit_other_per_minute,
    )
    return app
