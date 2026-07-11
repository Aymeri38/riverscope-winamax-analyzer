from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.community_hub.models import (
    Device,
    Member,
    OpponentSyncReceipt,
    SharedTournament,
)


DEVICE_TOKEN_PREFIX = "wxa_dev_"
INVITE_TOKEN_PREFIX = "wxa_inv_"
DEVICE_TOKEN_LIFETIME = timedelta(days=365)
bearer = HTTPBearer(auto_error=False)


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def generate_secret(prefix: str) -> str:
    # token_urlsafe receives a byte count; 32 bytes provides 256 bits.
    return prefix + secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def normalize_public_name(value: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not 2 <= len(normalized) <= 80:
        raise ValueError("Le nom public doit contenir de 2 a 80 caracteres.")
    if any(not char.isprintable() or unicodedata.category(char) == "Cf" for char in normalized):
        raise ValueError("Les caracteres de controle et bidi sont interdits.")
    normalized = " ".join(normalized.split())
    key = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()
    return normalized, key


def normalize_device_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not 2 <= len(normalized) <= 80:
        raise ValueError("Le libelle appareil doit contenir de 2 a 80 caracteres.")
    if any(not char.isprintable() or unicodedata.category(char) == "Cf" for char in normalized):
        raise ValueError("Les caracteres de controle et bidi sont interdits.")
    return " ".join(normalized.split())


@dataclass(frozen=True, slots=True)
class AuthenticatedDevice:
    member_id: int
    member_public_id: str
    device_id: int
    device_public_id: str


def get_hub_db(request: Request):  # type: ignore[no-untyped-def]
    yield from request.app.state.hub_database.dependency()


def authenticate_device(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_hub_db),
) -> AuthenticatedDevice:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if len(token) > 200 or not token.startswith(DEVICE_TOKEN_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    digest = hash_secret(token)
    row = db.execute(
        select(Device, Member)
        .join(Member, Member.id == Device.member_id)
        .where(Device.token_hash == digest)
    ).first()
    if row is None:
        # Preserve a constant-time comparison on the rejection path too.
        hmac.compare_digest(digest, "0" * 64)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    device, member = row
    if not hmac.compare_digest(device.token_hash, digest):
        raise HTTPException(status_code=401, detail="Jeton invalide.")
    if (
        device.revoked_at is not None
        or device.expires_at <= utcnow_naive()
        or member.disabled_at is not None
    ):
        raise HTTPException(status_code=401, detail="Jeton revoque.")
    device.last_seen_at = utcnow_naive()
    db.commit()
    return AuthenticatedDevice(
        member_id=member.id,
        member_public_id=member.public_id,
        device_id=device.id,
        device_public_id=device.public_id,
    )


def require_contribution(
    auth: AuthenticatedDevice = Depends(authenticate_device),
    db: Session = Depends(get_hub_db),
) -> AuthenticatedDevice:
    contributed = db.scalar(
        select(SharedTournament.id)
        .where(SharedTournament.member_id == auth.member_id)
        .limit(1)
    )
    if contributed is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Synchronisez au moins une partie terminee avant de consulter les contributions.",
        )
    return auth


def require_opponent_policy(
    auth: AuthenticatedDevice = Depends(authenticate_device),
    db: Session = Depends(get_hub_db),
) -> AuthenticatedDevice:
    policy_version = db.scalar(
        select(Member.policy_version).where(Member.id == auth.member_id)
    )
    if policy_version != "2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le consentement explicite a la politique v2 est requis.",
        )
    return auth


def require_collective_access(
    request: Request,
    auth: AuthenticatedDevice = Depends(require_contribution),
    db: Session = Depends(get_hub_db),
) -> AuthenticatedDevice:
    """Require policy v2 for every shared read when tracking is enabled."""
    if request.app.state.hub_config.opponent_tracking_enabled:
        policy_version = db.scalar(
            select(Member.policy_version).where(Member.id == auth.member_id)
        )
        if policy_version != "2":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Le consentement explicite a la politique v2 est requis.",
            )
        pending_enrichment = db.scalar(
            select(SharedTournament.id)
            .outerjoin(
                OpponentSyncReceipt,
                OpponentSyncReceipt.tournament_id == SharedTournament.id,
            )
            .where(
                SharedTournament.member_id == auth.member_id,
                OpponentSyncReceipt.id.is_(None),
            )
            .limit(1)
        )
        if pending_enrichment is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Synchronisez les enrichissements adverses termines avant consultation.",
            )
    return auth
