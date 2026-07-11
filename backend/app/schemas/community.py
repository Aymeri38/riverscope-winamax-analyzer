from __future__ import annotations

from datetime import datetime
import ipaddress
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator, model_validator


COMMUNITY_SCHEMA_VERSION = "1"
COMMUNITY_CONSENT_VERSION = "2"


class StrictCommunityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommunityJoinRequest(StrictCommunityModel):
    hub_url: str = Field(min_length=1, max_length=2048)
    invite: SecretStr = Field(min_length=32, max_length=160)
    consent: bool
    consent_version: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=2, max_length=80)

    @field_validator("hub_url")
    @classmethod
    def validate_hub_url(cls, value: str) -> str:
        raw = value.strip()
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Adresse du hub invalide")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("L'adresse du hub ne doit contenir ni identifiants, ni requête")
        hostname = parsed.hostname.casefold()
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = hostname == "localhost"
        if parsed.scheme != "https" and not loopback:
            raise ValueError("HTTPS est obligatoire hors adresse loopback")
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    @model_validator(mode="after")
    def require_current_consent(self) -> CommunityJoinRequest:
        if not self.consent:
            raise ValueError("Le consentement explicite est obligatoire")
        if self.consent_version not in {"1", COMMUNITY_CONSENT_VERSION}:
            raise ValueError("Version de consentement non prise en charge")
        return self


class CommunityLocalConfig(StrictCommunityModel):
    enabled: bool = False
    hub_url: str | None = None
    consent_version: str | None = None
    enrolled_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_contact_at: datetime | None = None
    last_error_code: str | None = None
    remote_has_contribution: bool = False
    opponent_tracking_required: bool = False


class CommunityStatusResponse(StrictCommunityModel):
    configured: bool
    available: bool
    online: bool | None
    pending: int = Field(ge=0)
    synced: int = Field(ge=0)
    last_sync_at: datetime | None
    consent_version: str
    required_consent_version: str = COMMUNITY_CONSENT_VERSION
    opponent_tracking_enabled: bool = False
    blocked_reason: str | None = None


class CommunityJoinResponse(StrictCommunityModel):
    configured: Literal[True]
    available: bool
    pending: int = Field(ge=0)
    synced: int = Field(ge=0)
    consent_version: str


class CommunityConsentRequest(StrictCommunityModel):
    consent: Literal[True]
    policy_version: Literal["2"]


class CommunityConsentResponse(StrictCommunityModel):
    policy_version: Literal["2"]
    opponent_tracking_enabled: Literal[True]


class CommunitySyncResponse(StrictCommunityModel):
    queued: int = Field(ge=0)
    synced: int = Field(ge=0)
    pending: int = Field(ge=0)
    online: bool
    available: bool
    error_code: str | None = None


class CommunityLeaveResponse(StrictCommunityModel):
    configured: Literal[False]
    remote_revoked: bool
    message: str


class CommunityEnrollmentResponse(StrictCommunityModel):
    member_id: str
    device_id: str
    device_token: SecretStr = Field(min_length=1)
    display_name: str
    policy_version: Literal["1", "2"]


class CommunitySyncHubResponse(StrictCommunityModel):
    status: Literal["created", "existing"]
    public_id: str = Field(min_length=1, max_length=100)
    hand_count: int = Field(ge=0)


class CommunityMeResponse(StrictCommunityModel):
    member_id: str
    display_name: str
    has_contribution: StrictBool
    policy_version: str = "1"
    opponent_tracking_required: StrictBool = False


class CommunityPlayerPayload(StrictCommunityModel):
    alias: str = Field(pattern=r"^(HERO|OPPONENT_[12])$")
    seat: int
    position: Literal["BTN", "SB", "BB", "UTG", "CO", "MP", "UNKNOWN"]
    starting_stack: int
    ending_stack: int | None
    invested: int
    won: int
    net: int | None
    hole_cards: list[str] | None = None
    showed: bool
    is_winner: bool
    is_all_in: bool


class CommunityActionPayload(StrictCommunityModel):
    sequence: int
    actor_alias: str = Field(pattern=r"^(HERO|OPPONENT_[12])$")
    street: str
    action_type: str
    amount: int | None
    to_amount: int | None
    pot_after: int | None
    is_all_in: bool


class CommunityHandPayload(StrictCommunityModel):
    hand_number: int
    played_at: datetime
    level: int | None
    small_blind: int
    big_blind: int
    ante: int
    button_seat: int | None
    max_players: int
    active_players: int
    total_pot: int | None
    hero_net: int | None
    is_all_in: bool
    reached_showdown: bool
    hero_cards: list[str]
    board: list[str]
    players: list[CommunityPlayerPayload]
    actions: list[CommunityActionPayload]


class CommunityTournamentData(StrictCommunityModel):
    started_at: datetime
    ended_at: datetime
    format: str
    is_nitro: bool
    currency: str
    total_buyin: float
    multiplier: float | None
    prize_pool: float
    reward: float
    final_rank: int
    duration_seconds: int
    total_hands: int
    registered_players: int
    initial_stack: int | None
    final_stack: int | None
    chip_delta: int | None
    hands: list[CommunityHandPayload]


class CommunityTournamentPayload(StrictCommunityModel):
    schema_version: Literal["1"] = COMMUNITY_SCHEMA_VERSION
    client_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    tournament: CommunityTournamentData


class CommunityOpponentEntryPayload(StrictCommunityModel):
    alias: str = Field(pattern=r"^OPPONENT_[12]$")
    display_name: str = Field(min_length=1, max_length=200, repr=False)
    final_rank: int | None = Field(default=None, ge=1, le=3)
    reward: float | None = Field(default=None, ge=0)
    starting_stack: int | None = Field(default=None, ge=0)
    final_stack: int | None = Field(default=None, ge=0)


class CommunityOpponentPayload(StrictCommunityModel):
    schema_version: Literal["1"] = "1"
    opponents: list[CommunityOpponentEntryPayload] = Field(max_length=2)


class CommunityOpponentSyncHubResponse(StrictCommunityModel):
    status: Literal["created", "existing"]
    opponent_count: int = Field(ge=0, le=2)
    observation_count: int = Field(ge=0)
