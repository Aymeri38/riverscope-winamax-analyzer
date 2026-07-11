from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.community_hub.database import HubBase


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Member(HubBase):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    policy_version: Mapped[str] = mapped_column(String(16), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)

    devices: Mapped[list[Device]] = relationship(back_populates="member")
    tournaments: Mapped[list[SharedTournament]] = relationship(back_populates="member")


class Invite(HubBase):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by_member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    target_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_by_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class Device(HubBase):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    member: Mapped[Member] = relationship(back_populates="devices")


class SharedTournament(HubBase):
    __tablename__ = "shared_tournaments"
    __table_args__ = (
        UniqueConstraint("member_id", "client_key", name="uq_shared_tournament_member_client_key"),
        UniqueConstraint(
            "member_id", "content_digest", name="uq_shared_tournament_member_content_digest"
        ),
        Index("ix_shared_tournaments_member_started", "member_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    client_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    is_nitro: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    total_buyin: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    multiplier: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    prize_pool: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reward: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    total_hands: Mapped[int] = mapped_column(Integer, nullable=False)
    registered_players: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_stack: Mapped[int | None] = mapped_column(Integer)
    final_stack: Mapped[int | None] = mapped_column(Integer)
    chip_delta: Mapped[int | None] = mapped_column(Integer)
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    member: Mapped[Member] = relationship(back_populates="tournaments")
    hands: Mapped[list[SharedHand]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", order_by="SharedHand.hand_number"
    )


class SharedHand(HubBase):
    __tablename__ = "shared_hands"
    __table_args__ = (
        UniqueConstraint("tournament_id", "hand_number", name="uq_shared_hand_tournament_number"),
        Index("ix_shared_hands_member_played", "member_id", "played_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("shared_tournaments.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    hand_number: Mapped[int] = mapped_column(Integer, nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    hero_position: Mapped[str | None] = mapped_column(String(16))
    active_players: Mapped[int] = mapped_column(Integer, nullable=False)
    big_blind: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pot: Mapped[int | None] = mapped_column(Integer)
    hero_net: Mapped[int | None] = mapped_column(Integer)
    is_all_in: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reached_showdown: Mapped[bool] = mapped_column(Boolean, nullable=False)
    replay_json: Mapped[str] = mapped_column(Text, nullable=False)

    tournament: Mapped[SharedTournament] = relationship(back_populates="hands")


class SyncReceipt(HubBase):
    __tablename__ = "sync_receipts"
    __table_args__ = (
        UniqueConstraint("member_id", "client_key", name="uq_sync_receipt_member_client_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    client_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("shared_tournaments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
