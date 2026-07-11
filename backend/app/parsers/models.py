from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal


IssueSeverity = Literal["info", "warning", "error"]


@dataclass(slots=True)
class ParseIssue:
    """A non-fatal parsing problem.

    ``line_excerpt`` is always privacy-sanitized by the parser.  It must never be
    replaced with the original source line in logs.
    """

    code: str
    message: str
    line_number: int | None = None
    line_excerpt: str | None = None
    severity: IssueSeverity = "warning"


@dataclass(slots=True)
class ParsedAction:
    sequence: int
    street: str
    actor: str
    action_type: str
    amount: Decimal | None = None
    to_amount: Decimal | None = None
    all_in: bool = False
    cards: list[str] = field(default_factory=list)
    description: str | None = None
    pot_name: str | None = None


@dataclass(slots=True)
class PotAward:
    player: str
    amount: Decimal
    pot_name: str = "pot"


@dataclass(slots=True)
class ParsedPlayer:
    seat: int
    name: str
    starting_stack: Decimal
    position: str | None = None
    is_button: bool = False
    hole_cards: list[str] = field(default_factory=list)
    showed: bool = False
    invested: Decimal = Decimal("0")
    won: Decimal = Decimal("0")
    ending_stack: Decimal | None = None
    is_all_in: bool = False

    @property
    def net(self) -> Decimal:
        return self.won - self.invested

    @property
    def is_winner(self) -> bool:
        return self.won > 0


@dataclass(slots=True)
class ParsedHand:
    external_id: str
    tournament_id: str | None
    tournament_name: str | None
    hand_number: int | None
    played_at: datetime | None
    level: int | None
    game_type: str | None
    buy_in_amount: Decimal | None
    fee_amount: Decimal | None
    currency: str | None
    small_blind: Decimal | None
    big_blind: Decimal | None
    ante: Decimal | None = None
    table_name: str | None = None
    max_players: int | None = None
    button_seat: int | None = None
    players: list[ParsedPlayer] = field(default_factory=list)
    hero_name: str | None = None
    hero_cards: list[str] = field(default_factory=list)
    actions: list[ParsedAction] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    awards: list[PotAward] = field(default_factory=list)
    total_pot: Decimal | None = None
    rake: Decimal | None = None
    reached_showdown: bool = False
    complete: bool = False
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def active_players(self) -> int:
        return len(self.players)

    @property
    def hero(self) -> ParsedPlayer | None:
        if not self.hero_name:
            return None
        hero_key = self.hero_name.casefold()
        return next((player for player in self.players if player.name.casefold() == hero_key), None)

    @property
    def hero_net(self) -> Decimal | None:
        player = self.hero
        return player.net if player else None

    @property
    def is_all_in(self) -> bool:
        return any(action.all_in for action in self.actions)

    @property
    def winners(self) -> list[str]:
        return [player.name for player in self.players if player.is_winner]


@dataclass(slots=True)
class HandHistoryParseResult:
    hands: list[ParsedHand] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    encoding: str = "unicode"
    source_hash: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.hands) and all(hand.complete for hand in self.hands)

    @property
    def tournament_ids(self) -> set[str]:
        return {hand.tournament_id for hand in self.hands if hand.tournament_id}

    @property
    def last_hand_at(self) -> datetime | None:
        values = [hand.played_at for hand in self.hands if hand.played_at]
        return max(values) if values else None


@dataclass(slots=True)
class TournamentSummary:
    tournament_id: str | None = None
    name: str | None = None
    hero_name: str | None = None
    buy_in_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    currency: str | None = None
    registered_players: int | None = None
    mode: str | None = None
    tournament_type: str | None = None
    speed: str | None = None
    flight_id: str | None = None
    levels: str | None = None
    prize_pool: Decimal | None = None
    started_at: datetime | None = None
    duration_seconds: int | None = None
    final_rank: int | None = None
    reward: Decimal | None = None
    ticket: str | None = None
    complete: bool = False
    issues: list[ParseIssue] = field(default_factory=list)
    encoding: str = "unicode"
    source_hash: str = ""

    @property
    def total_buy_in(self) -> Decimal | None:
        if self.buy_in_amount is None and self.fee_amount is None:
            return None
        return (self.buy_in_amount or Decimal("0")) + (self.fee_amount or Decimal("0"))

    @property
    def multiplier(self) -> Decimal | None:
        total = self.total_buy_in
        if not total or self.prize_pool is None:
            return None
        return self.prize_pool / total

    @property
    def is_expresso(self) -> bool:
        return bool(self.name and "expresso" in self.name.casefold())

    @property
    def is_nitro(self) -> bool:
        return bool(self.name and "nitro" in self.name.casefold())
