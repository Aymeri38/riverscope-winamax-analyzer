from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContributionPreviewResponse(BaseModel):
    """Exact, local-only preview of a privacy-minimized contribution payload."""

    filename: Literal["winamax-analyzer-contribution.json"]
    media_type: Literal["application/json"]
    encoding: Literal["utf-8"]
    payload: str
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    network_sent: Literal[False]
    redactions: list[str]
    exclusions: list[str]
    warnings: list[str]
