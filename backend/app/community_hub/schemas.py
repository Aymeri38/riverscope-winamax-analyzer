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
OpponentAlias = Annotated[str, StringConstraints(pattern=r"^OPPONENT_[1-9][0-9]*$")]
PlayerAlias = Annotated[str, StringConstraints(pattern=r"^(HERO|OPPONENT_[1-9][0-9]*)$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnrollRequest(StrictModel):
    invite_token: Annotated[str, StringConstraints(min_length=32, max_length=160)]
    display_name: Annotated[str, StringConstraints(min_length=2, max_length=80)]
    device_label: Annotated[str, StringConstraints(min_length=2, max_length=80)]
    policy_version: Literal["1"]
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
    policy_version: Literal["1"]


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


def is_opponent_alias(value: str) -> bool:
    return bool(re.fullmatch(r"OPPONENT_[1-9][0-9]*", value))
