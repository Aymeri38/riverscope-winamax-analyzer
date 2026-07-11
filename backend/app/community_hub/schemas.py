from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


StrictText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Card = Annotated[str, StringConstraints(pattern=r"^[2-9TJQKA][cdhs]$")]
ClientKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
OpponentAlias = Annotated[str, StringConstraints(pattern=r"^OPPONENT_[12]$")]
PlayerAlias = Annotated[str, StringConstraints(pattern=r"^(HERO|OPPONENT_[12])$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnrollRequest(StrictModel):
    invite_token: Annotated[str, StringConstraints(min_length=32, max_length=160)]
    display_name: Annotated[str, StringConstraints(min_length=2, max_length=80)]
    device_label: Annotated[str, StringConstraints(min_length=2, max_length=80)]
    policy_version: Literal["1", "2"]
    consent: Literal[True]

    @field_validator("display_name", "device_label")
    @classmethod
    def reject_ambiguous_text(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).strip()
        if any(not char.isprintable() or unicodedata.category(char) == "Cf" for char in normalized):
            raise ValueError("Les caracteres de controle et bidi sont interdits.")
        if "  " in normalized:
            normalized = " ".join(normalized.split())
        return normalized


class EnrollResponse(StrictModel):
    member_id: str
    device_id: str
    device_token: str
    display_name: str
    policy_version: Literal["1", "2"]


class ReplayPlayer(StrictModel):
    alias: PlayerAlias
    seat: int = Field(ge=1, le=10)
    position: Annotated[str, StringConstraints(pattern=r"^(BTN|SB|BB|UTG|CO|MP|UNKNOWN)$")]
    starting_stack: int = Field(ge=0, le=100_000_000)
    ending_stack: int | None = Field(default=None, ge=0, le=100_000_000)
    invested: int = Field(default=0, ge=0, le=100_000_000)
    won: int = Field(default=0, ge=0, le=100_000_000)
    net: int | None = Field(default=None, ge=-100_000_000, le=100_000_000)
    hole_cards: list[Card] | None = Field(default=None, max_length=2)
    showed: bool = False
    is_winner: bool = False
    is_all_in: bool = False

    @model_validator(mode="after")
    def known_cards_only_at_showdown(self) -> "ReplayPlayer":
        if self.alias != "HERO" and self.hole_cards and not self.showed:
            raise ValueError("Les cartes adverses ne sont admises que si elles ont ete revelees.")
        if self.hole_cards and len(set(self.hole_cards)) != len(self.hole_cards):
            raise ValueError("Une carte ne peut pas etre dupliquee.")
        return self


class ReplayAction(StrictModel):
    sequence: int = Field(ge=1, le=10_000)
    actor_alias: PlayerAlias
    street: Literal["PREFLOP", "FLOP", "TURN", "RIVER", "SHOWDOWN"]
    action_type: Literal[
        "POST_SB",
        "POST_BB",
        "POST_ANTE",
        "FOLD",
        "CHECK",
        "CALL",
        "BET",
        "RAISE",
        "ALL_IN",
        "UNCALLED_RETURN",
        "COLLECT",
        "SHOW",
        "MUCK",
    ]
    amount: int | None = Field(default=None, ge=0, le=100_000_000)
    to_amount: int | None = Field(default=None, ge=0, le=100_000_000)
    pot_after: int | None = Field(default=None, ge=0, le=500_000_000)
    is_all_in: bool = False


class SharedHandInput(StrictModel):
    hand_number: int = Field(ge=1, le=100_000)
    played_at: datetime
    level: int | None = Field(default=None, ge=0, le=100_000)
    small_blind: int = Field(ge=0, le=100_000_000)
    big_blind: int = Field(gt=0, le=100_000_000)
    ante: int = Field(default=0, ge=0, le=100_000_000)
    button_seat: int | None = Field(default=None, ge=1, le=10)
    max_players: int = Field(ge=2, le=3)
    active_players: int = Field(ge=2, le=3)
    total_pot: int | None = Field(default=None, ge=0, le=500_000_000)
    hero_net: int | None = Field(default=None, ge=-100_000_000, le=100_000_000)
    is_all_in: bool = False
    reached_showdown: bool = False
    hero_cards: list[Card] = Field(default_factory=list, max_length=2)
    board: list[Card] = Field(default_factory=list, max_length=5)
    players: list[ReplayPlayer] = Field(min_length=2, max_length=3)
    actions: list[ReplayAction] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_replay(self) -> "SharedHandInput":
        aliases = [player.alias for player in self.players]
        if aliases.count("HERO") != 1:
            raise ValueError("Chaque main doit contenir exactement un joueur HERO.")
        if len(set(aliases)) != len(aliases):
            raise ValueError("Les alias joueurs doivent etre uniques.")
        if len({player.seat for player in self.players}) != len(self.players):
            raise ValueError("Les sieges joueurs doivent etre uniques.")
        if self.active_players > self.max_players or len(self.players) > self.max_players:
            raise ValueError("Le nombre de joueurs est incoherent.")
        known_aliases = set(aliases)
        if any(action.actor_alias not in known_aliases for action in self.actions):
            raise ValueError("Une action reference un alias absent de la main.")
        sequences = [action.sequence for action in self.actions]
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise ValueError("Les actions doivent utiliser des numeros publics consecutifs.")
        all_cards = [*self.hero_cards, *self.board]
        for player in self.players:
            if player.alias != "HERO":
                all_cards.extend(player.hole_cards or [])
        if len(set(all_cards)) != len(all_cards):
            raise ValueError("La meme carte apparait plusieurs fois.")
        hero = next(player for player in self.players if player.alias == "HERO")
        if hero.hole_cards and self.hero_cards and hero.hole_cards != self.hero_cards:
            raise ValueError("Les cartes HERO sont incoherentes.")
        return self


class SharedTournamentInput(StrictModel):
    started_at: datetime
    ended_at: datetime
    format: Literal["EXPRESSO"]
    is_nitro: bool = False
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    total_buyin: Decimal = Field(ge=0, le=1_000_000)
    multiplier: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    prize_pool: Decimal = Field(ge=0, le=100_000_000)
    reward: Decimal = Field(ge=0, le=100_000_000)
    final_rank: int = Field(ge=1, le=10)
    duration_seconds: int = Field(ge=0, le=604_800)
    total_hands: int = Field(ge=1, le=1000)
    registered_players: int = Field(ge=2, le=3)
    initial_stack: int | None = Field(default=None, ge=0, le=100_000_000)
    final_stack: int | None = Field(default=None, ge=0, le=100_000_000)
    chip_delta: int | None = Field(default=None, ge=-100_000_000, le=100_000_000)
    hands: list[SharedHandInput] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def completed_and_consistent(self) -> "SharedTournamentInput":
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at doit etre posterieur a started_at.")
        if self.final_rank > self.registered_players:
            raise ValueError("Le classement final depasse le nombre de joueurs.")
        if self.total_hands != len(self.hands):
            raise ValueError("total_hands doit correspondre au nombre de mains transmises.")
        hand_numbers = [hand.hand_number for hand in self.hands]
        if sorted(hand_numbers) != list(range(1, len(hand_numbers) + 1)):
            raise ValueError("Les mains doivent utiliser des numeros publics consecutifs.")
        return self


class SyncTournamentRequest(StrictModel):
    schema_version: Literal["1"]
    client_key: ClientKey
    tournament: SharedTournamentInput

    @field_validator("client_key")
    @classmethod
    def normalize_client_key(cls, value: str) -> str:
        return value.lower()


class SyncTournamentResponse(StrictModel):
    status: Literal["created", "existing"]
    public_id: str
    hand_count: int


class ConsentUpgradeRequest(StrictModel):
    consent: Literal[True]
    policy_version: Literal["2"]


class ConsentUpgradeResponse(StrictModel):
    policy_version: Literal["2"]
    opponent_tracking_enabled: Literal[True]


class OpponentTournamentInput(StrictModel):
    alias: Annotated[str, StringConstraints(pattern=r"^OPPONENT_[12]$")]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)] = Field(
        repr=False
    )
    final_rank: int | None = Field(default=None, ge=1, le=3)
    reward: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    starting_stack: int | None = Field(default=None, ge=0, le=100_000_000)
    final_stack: int | None = Field(default=None, ge=0, le=100_000_000)


class OpponentSyncRequest(StrictModel):
    schema_version: Literal["1"]
    opponents: list[OpponentTournamentInput] = Field(max_length=2)

    @model_validator(mode="after")
    def aliases_are_unique(self) -> "OpponentSyncRequest":
        aliases = [opponent.alias for opponent in self.opponents]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Alias adverse duplique.")
        if aliases != sorted(aliases):
            raise ValueError("Les alias adverses doivent etre ordonnes.")
        return self


class OpponentSyncResponse(StrictModel):
    status: Literal["created", "existing"]
    opponent_count: int
    observation_count: int


class OpponentListItem(StrictModel):
    public_id: str
    display_name: str
    first_seen_at: datetime
    last_seen_at: datetime
    tournaments: int
    hands: int
    contributors: int


class OpponentListResponse(StrictModel):
    items: list[OpponentListItem]
    total: int
    limit: int
    offset: int


class OpponentRateStat(StrictModel):
    made: int
    opportunities: int
    percent: float | None


class OpponentAggressionStat(StrictModel):
    aggressive_actions: int
    calls: int
    checks: int
    folds: int
    opportunities: int
    frequency_percent: float | None
    factor: float | None


class OpponentProfileMetrics(StrictModel):
    tournaments: int
    hands: int
    contributors: int
    net_chips: int
    known_net_hands: int
    preflop_known_hands: int
    vpip: OpponentRateStat
    pfr: OpponentRateStat
    limp: OpponentRateStat
    three_bet: OpponentRateStat
    shove: OpponentRateStat
    aggression: OpponentAggressionStat
    wtsd: OpponentRateStat
    wsd: OpponentRateStat
    all_in: OpponentRateStat


class OpponentProfileIdentity(StrictModel):
    public_id: str
    display_name: str
    first_seen_at: datetime
    last_seen_at: datetime


class OpponentProfileBreakdown(OpponentProfileMetrics):
    position: str | None = None
    bucket: str | None = None


class OpponentRecentObservation(StrictModel):
    hand_id: str
    tournament_id: str
    played_at: datetime
    position: str | None
    stack_bb: float | None
    invested: int
    won: int
    net: int | None
    showed: bool
    is_winner: bool
    is_all_in: bool
    preflop_known: bool
    vpip: bool
    pfr: bool
    limp: bool
    faced_open: bool
    three_bet: bool
    shove: bool
    postflop_aggressive_actions: int
    postflop_calls: int
    postflop_checks: int
    postflop_folds: int
    saw_flop: bool
    went_showdown: bool
    won_showdown: bool


class OpponentProfileResponse(StrictModel):
    identity: OpponentProfileIdentity
    summary: OpponentProfileMetrics
    by_position: list[OpponentProfileBreakdown]
    by_depth: list[OpponentProfileBreakdown]
    recent_observations: list[OpponentRecentObservation] = Field(max_length=20)


class ContributorProfileIdentity(StrictModel):
    public_id: str
    display_name: str
    joined_at: datetime


class ContributorProfileSummary(StrictModel):
    games: int
    hands: int
    currency: str | None
    total_buyins: float | None
    total_winnings: float | None
    net_result: float | None
    roi_percent: float | None
    wins: int
    second_places: int
    third_places: int
    win_rate_percent: float
    second_place_percent: float
    third_place_percent: float
    itm_count: int
    itm_percent: float
    average_buyin: float | None
    average_winnings: float | None
    average_net: float | None
    average_duration_seconds: float
    average_hands: float
    chip_ev_per_game: float | None
    chip_ev_games: int
    chip_ev_coverage_percent: float
    first_game_at: datetime
    last_game_at: datetime


class ContributorProfileBreakdown(StrictModel):
    currency: str
    buyin: float | None = None
    multiplier: float | None = None
    games: int
    hands: int
    total_buyins: float
    total_winnings: float
    net_result: float
    roi_percent: float
    wins: int
    win_rate_percent: float
    itm_count: int
    itm_percent: float
    average_net: float
    chip_ev_per_game: float | None
    chip_ev_games: int
    chip_ev_coverage_percent: float


class ContributorProfileTrendDay(StrictModel):
    date: str
    currency: str
    games: int
    total_buyins: float
    total_winnings: float
    net_result: float
    cumulative_net: float


class ContributorProfileTournament(StrictModel):
    public_id: str
    started_at: datetime
    ended_at: datetime
    format: str
    is_nitro: bool
    currency: str
    total_buyin: float
    multiplier: float | None
    prize_pool: float
    reward: float
    net_result: float
    final_rank: int
    duration_seconds: int
    total_hands: int
    registered_players: int
    chip_delta: int | None


class ContributorProfileResponse(StrictModel):
    contributor: ContributorProfileIdentity
    summary: ContributorProfileSummary
    by_currency: list[ContributorProfileBreakdown]
    by_limit: list[ContributorProfileBreakdown]
    by_multiplier: list[ContributorProfileBreakdown]
    trend: list[ContributorProfileTrendDay]
    recent_tournaments: list[ContributorProfileTournament] = Field(max_length=10)


def is_opponent_alias(value: str) -> bool:
    return bool(re.fullmatch(r"OPPONENT_[12]", value))
