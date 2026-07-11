from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


DEFAULT_LEAK_THRESHOLDS: dict[str, float] = {
    "limp_fold_pct": 45.0,
    "oop_call_pct": 35.0,
    "vpip_pct": 55.0,
    "pfr_min_pct": 25.0,
    "vpip_pfr_gap_pct": 18.0,
    "button_vpip_min_pct": 45.0,
    "bb_fold_pct": 62.0,
    "short_call_shove_pct": 32.0,
    "invested_fold_pct": 25.0,
    "cbet_pct": 85.0,
    "fold_to_cbet_pct": 65.0,
    "turn_aggression_min_pct": 25.0,
    "river_hero_call_pct": 35.0,
    "river_aggression_min_pct": 20.0,
    "depth_result_min_chips_per_hand": -5.0,
    "heads_up_win_min_pct": 45.0,
    "third_place_pct": 42.0,
}


class AnalyzerSettings(BaseModel):
    history_paths: list[str] = Field(default_factory=list)
    hero_name: str = ""
    stable_delay_seconds: int = Field(default=10, ge=10, le=600)
    active_grace_seconds: int = Field(default=60, ge=60, le=3600)
    currency: str = "EUR"
    session_gap_minutes: int = Field(default=30, ge=5, le=240)
    leak_thresholds: dict[str, float] = Field(default_factory=lambda: DEFAULT_LEAK_THRESHOLDS.copy())
    auto_start: bool = False
    theme: Literal["dark", "light", "system"] = "dark"
    ai_enabled: bool = False
    ai_provider: str | None = None
    anonymize_exports: bool = True
    community_sync_interval_seconds: int = Field(default=60, ge=30, le=3600)

    @field_validator("history_paths")
    @classmethod
    def normalize_paths(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(path.strip() for path in value if path.strip()))


class RescanResponse(BaseModel):
    scanned: int
    imported: int
    waiting: int
    failed: int
    skipped: int
    message: str


class SettingsPatch(BaseModel):
    history_paths: list[str] | None = None
    hero_name: str | None = None
    stable_delay_seconds: int | None = Field(default=None, ge=10, le=600)
    active_grace_seconds: int | None = Field(default=None, ge=60, le=3600)
    currency: str | None = None
    session_gap_minutes: int | None = Field(default=None, ge=5, le=240)
    leak_thresholds: dict[str, float] | None = None
    auto_start: bool | None = None
    theme: Literal["dark", "light", "system"] | None = None
    ai_enabled: bool | None = None
    ai_provider: str | None = None
    anonymize_exports: bool | None = None
    community_sync_interval_seconds: int | None = Field(default=None, ge=30, le=3600)


class RestoreRequest(BaseModel):
    backup_name: str
    confirm: bool = False


class DeleteRequest(BaseModel):
    confirmation: str


class AiAnalysisRequest(BaseModel):
    hand_id: int
    confirmed: bool = False
    provider: str | None = None


class ApiMessage(BaseModel):
    message: str
    details: dict[str, Any] | None = None
