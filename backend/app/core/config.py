from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class AppConfig:
    project_root: Path
    data_dir: Path
    database_path: Path
    frontend_dist: Path
    host: str = "127.0.0.1"
    port: int = 8000


def get_config() -> AppConfig:
    data_dir = Path(os.environ.get("WXA_DATA_DIR", PROJECT_ROOT / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        database_path=data_dir / "winamax_analyzer.db",
        frontend_dist=PROJECT_ROOT / "frontend" / "dist",
        host="127.0.0.1",
        port=int(os.environ.get("WXA_PORT", "8000")),
    )


config = get_config()

