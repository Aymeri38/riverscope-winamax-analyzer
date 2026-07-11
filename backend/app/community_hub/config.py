from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HUB_PORT = 8040
MAX_BODY_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_TOURNAMENTS_PER_MEMBER = 50_000
DEFAULT_MAX_HANDS_PER_MEMBER = 1_000_000
DEFAULT_MAX_PAYLOAD_BYTES_PER_MEMBER = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_RECEIPTS_PER_TOURNAMENT = 16
DEFAULT_RATE_LIMIT_ENROLL_PER_MINUTE = 10
DEFAULT_RATE_LIMIT_SYNC_PER_MINUTE = 20
DEFAULT_RATE_LIMIT_OTHER_PER_MINUTE = 240
DEFAULT_RATE_LIMIT_MAX_BUCKETS = 10_000


@dataclass(frozen=True, slots=True)
class HubConfig:
    data_dir: Path
    database_path: Path
    host: str
    port: int
    docs_enabled: bool
    trusted_hosts: tuple[str, ...]
    max_tournaments_per_member: int
    max_hands_per_member: int
    max_payload_bytes_per_member: int
    max_receipts_per_tournament: int
    rate_limit_enroll_per_minute: int
    rate_limit_sync_per_minute: int
    rate_limit_other_per_minute: int
    rate_limit_max_buckets: int


def _positive_int(env: dict[str, str] | os._Environ[str], name: str, default: int) -> int:
    value = int(env.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} doit etre strictement positif.")
    return value


def _contains_cloud_directory(value: str | Path) -> bool:
    # Split both path syntaxes before using the host OS Path implementation.
    # Otherwise a Windows path is one opaque POSIX segment on the Linux hub.
    parts = tuple(part for part in re.split(r"[\\/]+", str(value)) if part)
    cloud_parts = {"onedrive", "onedriveconsumer", "onedrivecommercial"}
    return any(
        part.casefold() in cloud_parts or part.casefold().startswith("onedrive -")
        for part in parts
    )


def get_hub_config(environ: dict[str, str] | os._Environ[str] | None = None) -> HubConfig:
    env = environ if environ is not None else os.environ
    configured_value = str(env.get("WXA_HUB_DATA_DIR", PROJECT_ROOT / "hub-data"))
    if configured_value.startswith(("\\\\", "//")):
        raise ValueError("WXA_HUB_DATA_DIR ne peut pas etre un chemin reseau UNC.")
    configured_data_dir = Path(configured_value)
    if not configured_data_dir.is_absolute():
        configured_data_dir = PROJECT_ROOT / configured_data_dir
    data_dir = configured_data_dir.resolve()
    if _contains_cloud_directory(configured_value) or _contains_cloud_directory(data_dir):
        raise ValueError("WXA_HUB_DATA_DIR ne peut pas etre place dans OneDrive.")
    host = env.get("WXA_HUB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(env.get("WXA_HUB_PORT", str(DEFAULT_HUB_PORT)))
    if not 1 <= port <= 65535:
        raise ValueError("WXA_HUB_PORT doit etre compris entre 1 et 65535.")
    configured_hosts = tuple(
        value.strip()
        for value in env.get("WXA_HUB_TRUSTED_HOSTS", "").split(",")
        if value.strip()
    )
    if any("*" in host for host in configured_hosts):
        raise ValueError("WXA_HUB_TRUSTED_HOSTS exige des noms exacts, sans wildcard.")
    defaults = (host, "127.0.0.1", "localhost", "[::1]", "testserver")
    trusted_hosts = tuple(dict.fromkeys((*configured_hosts, *defaults)))
    return HubConfig(
        data_dir=data_dir,
        database_path=data_dir / "community_hub.db",
        host=host,
        port=port,
        docs_enabled=env.get("WXA_HUB_ENABLE_DOCS") == "YES",
        trusted_hosts=trusted_hosts,
        max_tournaments_per_member=_positive_int(
            env,
            "WXA_HUB_MAX_TOURNAMENTS_PER_MEMBER",
            DEFAULT_MAX_TOURNAMENTS_PER_MEMBER,
        ),
        max_hands_per_member=_positive_int(
            env,
            "WXA_HUB_MAX_HANDS_PER_MEMBER",
            DEFAULT_MAX_HANDS_PER_MEMBER,
        ),
        max_payload_bytes_per_member=_positive_int(
            env,
            "WXA_HUB_MAX_PAYLOAD_BYTES_PER_MEMBER",
            DEFAULT_MAX_PAYLOAD_BYTES_PER_MEMBER,
        ),
        max_receipts_per_tournament=_positive_int(
            env,
            "WXA_HUB_MAX_RECEIPTS_PER_TOURNAMENT",
            DEFAULT_MAX_RECEIPTS_PER_TOURNAMENT,
        ),
        rate_limit_enroll_per_minute=_positive_int(
            env,
            "WXA_HUB_RATE_LIMIT_ENROLL_PER_MINUTE",
            DEFAULT_RATE_LIMIT_ENROLL_PER_MINUTE,
        ),
        rate_limit_sync_per_minute=_positive_int(
            env,
            "WXA_HUB_RATE_LIMIT_SYNC_PER_MINUTE",
            DEFAULT_RATE_LIMIT_SYNC_PER_MINUTE,
        ),
        rate_limit_other_per_minute=_positive_int(
            env,
            "WXA_HUB_RATE_LIMIT_OTHER_PER_MINUTE",
            DEFAULT_RATE_LIMIT_OTHER_PER_MINUTE,
        ),
        rate_limit_max_buckets=_positive_int(
            env,
            "WXA_HUB_RATE_LIMIT_MAX_BUCKETS",
            DEFAULT_RATE_LIMIT_MAX_BUCKETS,
        ),
    )
