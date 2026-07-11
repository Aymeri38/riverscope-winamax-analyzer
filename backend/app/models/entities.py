from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ImportFile(Base):
    __tablename__ = "import_files"
    __table_args__ = (
        CheckConstraint(
            "state IN ('detected','waiting_for_completion','imported','failed')",
            name="ck_import_state",
        ),
        Index("ix_import_files_hash", "file_hash"),
        Index("ix_import_files_mtime", "modified_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    file_type: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(30), default="detected", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id", ondelete="SET NULL"))

    tournament: Mapped[Tournament | None] = relationship(back_populates="import_files")
    errors: Mapped[list[ImportError]] = relationship(back_populates="import_file", cascade="all, delete-orphan")


class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        Index("ix_tournaments_started_buyin", "started_at", "total_buyin"),
        Index("ix_tournaments_rank", "final_rank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_expresso: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_nitro: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    buyin_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_buyin: Mapped[Decimal] = mapped_column(Numeric(12, 2), index=True, default=0, nullable=False)
    multiplier: Mapped[float | None] = mapped_column(Numeric(10, 2))
    prize_pool: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    reward: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    ticket: Mapped[str | None] = mapped_column(String(200))
    final_rank: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    total_hands: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    registered_players: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    hero_name: Mapped[str] = mapped_column(String(200), nullable=False)
    initial_stack: Mapped[int | None] = mapped_column(Integer)
    final_stack: Mapped[int | None] = mapped_column(Integer)
    chip_delta: Mapped[int | None] = mapped_column(Integer)
    source_path: Mapped[str | None] = mapped_column(Text)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    import_files: Mapped[list[ImportFile]] = relationship(back_populates="tournament")
    hands: Mapped[list[Hand]] = relationship(back_populates="tournament", cascade="all, delete-orphan")
    players: Mapped[list[TournamentPlayer]] = relationship(back_populates="tournament", cascade="all, delete-orphan")
    leak_flags: Mapped[list[LeakFlag]] = relationship(back_populates="tournament")
    community_sync: Mapped[CommunitySyncRecord | None] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", uselist=False
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_hero: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anonymized_label: Mapped[str | None] = mapped_column(String(40))

    tournaments: Mapped[list[TournamentPlayer]] = relationship(back_populates="player")
    hand_entries: Mapped[list[HandPlayer]] = relationship(back_populates="player")
    actions: Mapped[list[Action]] = relationship(back_populates="player")


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"
    __table_args__ = (UniqueConstraint("tournament_id", "player_id", name="uq_tournament_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    final_rank: Mapped[int | None] = mapped_column(Integer)
    reward: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    starting_stack: Mapped[int | None] = mapped_column(Integer)
    final_stack: Mapped[int | None] = mapped_column(Integer)
    display_alias: Mapped[str | None] = mapped_column(String(40))

    tournament: Mapped[Tournament] = relationship(back_populates="players")
    player: Mapped[Player] = relationship(back_populates="tournaments")


class Hand(Base):
    __tablename__ = "hands"
    __table_args__ = (
        UniqueConstraint("tournament_id", "hand_number", name="uq_tournament_hand_number"),
        Index("ix_hands_played_tournament", "played_at", "tournament_id"),
        Index("ix_hands_blinds", "big_blind", "small_blind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    hand_number: Mapped[int] = mapped_column(Integer, nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    level: Mapped[int | None] = mapped_column(Integer)
    small_blind: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    big_blind: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ante: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    button_seat: Mapped[int | None] = mapped_column(Integer)
    max_players: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    active_players: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    total_pot: Mapped[int | None] = mapped_column(Integer)
    hero_net: Mapped[int | None] = mapped_column(Integer)
    is_all_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reached_showdown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    board_text: Mapped[str | None] = mapped_column(String(40))
    action_text: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    tournament: Mapped[Tournament] = relationship(back_populates="hands")
    player_entries: Mapped[list[HandPlayer]] = relationship(back_populates="hand", cascade="all, delete-orphan")
    actions: Mapped[list[Action]] = relationship(back_populates="hand", cascade="all, delete-orphan", order_by="Action.sequence")
    board_cards: Mapped[list[BoardCard]] = relationship(back_populates="hand", cascade="all, delete-orphan")
    hero_hole_cards: Mapped[list[HeroHoleCard]] = relationship(back_populates="hand", cascade="all, delete-orphan")
    analysis: Mapped[AnalysisResult | None] = relationship(back_populates="hand", cascade="all, delete-orphan", uselist=False)
    leak_flags: Mapped[list[LeakFlag]] = relationship(back_populates="hand")


class HandPlayer(Base):
    __tablename__ = "hand_players"
    __table_args__ = (UniqueConstraint("hand_id", "player_id", name="uq_hand_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hand_id: Mapped[int] = mapped_column(ForeignKey("hands.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    seat: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[str | None] = mapped_column(String(10), index=True)
    starting_stack: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ending_stack: Mapped[int | None] = mapped_column(Integer)
    invested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    won: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    net: Mapped[int | None] = mapped_column(Integer)
    hole_cards: Mapped[str | None] = mapped_column(String(20))
    showed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_all_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    hand: Mapped[Hand] = relationship(back_populates="player_entries")
    player: Mapped[Player] = relationship(back_populates="hand_entries")


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("hand_id", "sequence", name="uq_hand_action_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hand_id: Mapped[int] = mapped_column(ForeignKey("hands.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    street: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    amount: Mapped[int | None] = mapped_column(Integer)
    to_amount: Mapped[int | None] = mapped_column(Integer)
    pot_after: Mapped[int | None] = mapped_column(Integer)
    is_all_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    hand: Mapped[Hand] = relationship(back_populates="actions")
    player: Mapped[Player] = relationship(back_populates="actions")


class BoardCard(Base):
    __tablename__ = "board_cards"
    __table_args__ = (UniqueConstraint("hand_id", "position", name="uq_board_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hand_id: Mapped[int] = mapped_column(ForeignKey("hands.id", ondelete="CASCADE"), index=True)
    street: Mapped[str] = mapped_column(String(10), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[str] = mapped_column(String(2), nullable=False)
    suit: Mapped[str] = mapped_column(String(1), nullable=False)

    hand: Mapped[Hand] = relationship(back_populates="board_cards")


class HeroHoleCard(Base):
    __tablename__ = "hero_hole_cards"
    __table_args__ = (UniqueConstraint("hand_id", "position", name="uq_hero_card_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hand_id: Mapped[int] = mapped_column(ForeignKey("hands.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[str] = mapped_column(String(2), nullable=False)
    suit: Mapped[str] = mapped_column(String(1), nullable=False)

    hand: Mapped[Hand] = relationship(back_populates="hero_hole_cards")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    hand_id: Mapped[int] = mapped_column(ForeignKey("hands.id", ondelete="CASCADE"), unique=True, index=True)
    classification: Mapped[str] = mapped_column(String(60), default="données insuffisantes", nullable=False)
    decision_quality: Mapped[str | None] = mapped_column(String(100))
    financial_result: Mapped[int | None] = mapped_column(Integer)
    win_probability: Mapped[float | None] = mapped_column(Numeric(8, 6))
    tie_probability: Mapped[float | None] = mapped_column(Numeric(8, 6))
    loss_probability: Mapped[float | None] = mapped_column(Numeric(8, 6))
    theoretical_ev_chips: Mapped[float | None] = mapped_column(Numeric(14, 4))
    actual_result_chips: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    data_quality: Mapped[str] = mapped_column(String(40), default="insufficient", nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(30), default="rules-v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    hand: Mapped[Hand] = relationship(back_populates="analysis")


class LeakFlag(Base):
    __tablename__ = "leak_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id", ondelete="SET NULL"), index=True)
    hand_id: Mapped[int | None] = mapped_column(ForeignKey("hands.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    threshold_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hand_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    tournament: Mapped[Tournament | None] = relationship(back_populates="leak_flags")
    hand: Mapped[Hand | None] = relationship(back_populates="leak_flags")


class ImportError(Base):
    __tablename__ = "import_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_file_id: Mapped[int] = mapped_column(ForeignKey("import_files.id", ondelete="CASCADE"), index=True)
    line_number: Mapped[int | None] = mapped_column(Integer)
    line_hash: Mapped[str | None] = mapped_column(String(64))
    sanitized_line: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    import_file: Mapped[ImportFile] = relationship(back_populates="errors")


class CommunitySyncRecord(Base):
    """Local delivery queue. It never stores a community bearer token or payload."""

    __tablename__ = "community_sync_records"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','synced')",
            name="ck_community_sync_state",
        ),
        Index("ix_community_sync_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    client_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    remote_public_id: Mapped[str | None] = mapped_column(String(100))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    tournament: Mapped[Tournament] = relationship(back_populates="community_sync")
