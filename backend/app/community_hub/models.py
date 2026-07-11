from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
    opponents: Mapped[list[SharedTournamentOpponent]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )
    opponent_sync_receipt: Mapped[OpponentSyncReceipt | None] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", uselist=False
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
    opponent_observations: Mapped[list[SharedOpponentObservation]] = relationship(
        back_populates="hand", cascade="all, delete-orphan"
    )


class Opponent(HubBase):
    """A persisted public poker identity observed after completed tournaments.

    The deterministic identity is an HMAC and the display value is AES-GCM
    ciphertext.  Neither key is stored in SQLite.
    """

    __tablename__ = "opponents"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    identity_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    display_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    display_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    tournaments: Mapped[list[SharedTournamentOpponent]] = relationship(
        back_populates="opponent", passive_deletes=True
    )


class OpponentSuppression(HubBase):
    """Permanent opt-out tombstone keyed without retaining the display name."""

    __tablename__ = "opponent_suppressions"

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class OpponentSyncReceipt(HubBase):
    __tablename__ = "opponent_sync_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("shared_tournaments.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    tournament: Mapped[SharedTournament] = relationship(
        back_populates="opponent_sync_receipt"
    )


class SharedTournamentOpponent(HubBase):
    __tablename__ = "shared_tournament_opponents"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "alias", name="uq_shared_tournament_opponent_alias"
        ),
        UniqueConstraint(
            "tournament_id", "opponent_id", name="uq_shared_tournament_opponent_identity"
        ),
        Index("ix_shared_tournament_opponents_opponent", "opponent_id", "tournament_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("shared_tournaments.id", ondelete="CASCADE"), nullable=False
    )
    opponent_id: Mapped[int] = mapped_column(
        ForeignKey("opponents.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(20), nullable=False)
    final_rank: Mapped[int | None] = mapped_column(Integer)
    reward: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    starting_stack: Mapped[int | None] = mapped_column(Integer)
    final_stack: Mapped[int | None] = mapped_column(Integer)

    tournament: Mapped[SharedTournament] = relationship(back_populates="opponents")
    opponent: Mapped[Opponent] = relationship(back_populates="tournaments")
    observations: Mapped[list[SharedOpponentObservation]] = relationship(
        back_populates="tournament_opponent", cascade="all, delete-orphan"
    )


class SharedOpponentObservation(HubBase):
    __tablename__ = "shared_opponent_observations"
    __table_args__ = (
        UniqueConstraint(
            "shared_hand_id",
            "tournament_opponent_id",
            name="uq_shared_opponent_observation_hand_identity",
        ),
        Index(
            "ix_shared_opponent_observations_identity_hand",
            "tournament_opponent_id",
            "shared_hand_id",
        ),
        Index("ix_shared_opponent_observations_position", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shared_hand_id: Mapped[int] = mapped_column(
        ForeignKey("shared_hands.id", ondelete="CASCADE"), nullable=False
    )
    tournament_opponent_id: Mapped[int] = mapped_column(
        ForeignKey("shared_tournament_opponents.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[str | None] = mapped_column(String(16))
    starting_stack: Mapped[int] = mapped_column(Integer, nullable=False)
    stack_bb: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    invested: Mapped[int] = mapped_column(Integer, nullable=False)
    won: Mapped[int] = mapped_column(Integer, nullable=False)
    net: Mapped[int | None] = mapped_column(Integer)
    metrics_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    showed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_all_in: Mapped[bool] = mapped_column(Boolean, nullable=False)
    preflop_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    vpip: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pfr: Mapped[bool] = mapped_column(Boolean, nullable=False)
    limp: Mapped[bool] = mapped_column(Boolean, nullable=False)
    faced_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    three_bet: Mapped[bool] = mapped_column(Boolean, nullable=False)
    shove: Mapped[bool] = mapped_column(Boolean, nullable=False)
    postflop_aggressive_actions: Mapped[int] = mapped_column(Integer, nullable=False)
    postflop_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    postflop_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    postflop_folds: Mapped[int] = mapped_column(Integer, nullable=False)
    saw_flop: Mapped[bool] = mapped_column(Boolean, nullable=False)
    went_showdown: Mapped[bool] = mapped_column(Boolean, nullable=False)
    won_showdown: Mapped[bool] = mapped_column(Boolean, nullable=False)

    hand: Mapped[SharedHand] = relationship(back_populates="opponent_observations")
    tournament_opponent: Mapped[SharedTournamentOpponent] = relationship(
        back_populates="observations"
    )


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
