from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting
from app.schemas.api import AnalyzerSettings


SETTINGS_KEY = "analyzer"


def _detected_default_paths() -> list[str]:
    profile = Path(os.environ.get("USERPROFILE", Path.home()))
    appdata = Path(os.environ.get("APPDATA", profile / "AppData" / "Roaming"))
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    candidates = [
        appdata / "winamax" / "documents" / "accounts",
        profile / "Documents" / "Winamax Poker" / "accounts",
        profile / "OneDrive" / "Documents" / "Winamax Poker" / "accounts",
    ]
    if onedrive:
        candidates.append(Path(onedrive) / "Documents" / "Winamax Poker" / "accounts")
    histories: list[str] = []
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        for history in candidate.glob("*/history"):
            if history.is_dir():
                histories.append(str(history.resolve()))
    return list(dict.fromkeys(histories))


def default_settings() -> AnalyzerSettings:
    paths = _detected_default_paths()
    hero = ""
    if paths:
        try:
            hero = Path(paths[0]).parent.name
        except IndexError:
            pass
    return AnalyzerSettings(history_paths=paths, hero_name=hero)


def load_settings(db: Session) -> AnalyzerSettings:
    row = db.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
    if row is None:
        value = default_settings()
        db.add(Setting(key=SETTINGS_KEY, value_json=value.model_dump_json()))
        db.commit()
        return value
    try:
        return AnalyzerSettings.model_validate_json(row.value_json)
    except (ValueError, json.JSONDecodeError):
        return default_settings()


def save_settings(db: Session, value: AnalyzerSettings) -> AnalyzerSettings:
    row = db.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
    if row is None:
        row = Setting(key=SETTINGS_KEY, value_json=value.model_dump_json())
        db.add(row)
    else:
        row.value_json = value.model_dump_json()
    db.commit()
    return value
