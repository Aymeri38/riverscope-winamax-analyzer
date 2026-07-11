from __future__ import annotations

import csv
import io
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import config
from app.database.session import engine
from app.models import (
    Action,
    AnalysisResult,
    BoardCard,
    Hand,
    HandPlayer,
    HeroHoleCard,
    ImportError,
    ImportFile,
    LeakFlag,
    Player,
    Tournament,
    TournamentPlayer,
)


SAFE_BACKUP = re.compile(r"^winamax-analyzer-\d{8}-\d{6}\.db$")


def create_backup() -> Path:
    backup_dir = config.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"winamax-analyzer-{datetime.now():%Y%m%d-%H%M%S}.db"
    source_connection = sqlite3.connect(config.database_path)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    return target


def list_backups() -> list[dict[str, object]]:
    backup_dir = config.data_dir / "backups"
    if not backup_dir.exists():
        return []
    return [
        {"name": path.name, "size_bytes": path.stat().st_size, "created_at": path.stat().st_mtime}
        for path in sorted(backup_dir.glob("winamax-analyzer-*.db"), reverse=True)
    ]


def restore_backup(name: str) -> None:
    if not SAFE_BACKUP.fullmatch(name):
        raise ValueError("Nom de sauvegarde invalide")
    source = (config.data_dir / "backups" / name).resolve()
    expected_parent = (config.data_dir / "backups").resolve()
    if source.parent != expected_parent or not source.is_file():
        raise FileNotFoundError(name)
    with sqlite3.connect(source) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError("Sauvegarde SQLite invalide")
    engine.dispose()
    safety = config.database_path.with_suffix(".before-restore.db")
    if config.database_path.exists():
        shutil.copy2(config.database_path, safety)
    shutil.copy2(source, config.database_path)


def export_tournaments_csv(db: Session, anonymize: bool = True) -> str:
    rows = db.scalars(select(Tournament).order_by(Tournament.started_at)).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "tournament_id",
            "date_utc",
            "format",
            "buy_in",
            "multiplier",
            "prize_pool",
            "rank",
            "reward",
            "net",
            "duration_seconds",
            "hands",
            "chip_ev",
            "hero",
        ]
    )
    for index, tournament in enumerate(rows, 1):
        net = float(tournament.reward) - float(tournament.total_buyin)
        tournament_id = f"T{index:06d}" if anonymize else tournament.external_id
        played_at = "" if anonymize else tournament.started_at.isoformat()
        format_name = (
            "Expresso Nitro" if tournament.is_nitro else "Expresso"
        ) if anonymize else tournament.name
        writer.writerow(
            [
                tournament_id,
                played_at,
                format_name,
                float(tournament.total_buyin),
                float(tournament.multiplier) if tournament.multiplier is not None else "",
                float(tournament.prize_pool),
                tournament.final_rank or "",
                float(tournament.reward),
                net,
                tournament.duration_seconds or "",
                tournament.total_hands,
                tournament.chip_delta if tournament.chip_delta is not None else "",
                "HERO" if anonymize else tournament.hero_name,
            ]
        )
    return output.getvalue()


def delete_analyzed_data(db: Session) -> None:
    # Settings are deliberately retained so a rescan can rebuild everything.
    for model in (
        LeakFlag,
        AnalysisResult,
        Action,
        BoardCard,
        HeroHoleCard,
        HandPlayer,
        TournamentPlayer,
        ImportError,
        ImportFile,
        Hand,
        Player,
        Tournament,
    ):
        db.execute(delete(model))
    db.commit()
