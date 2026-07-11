from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.process_guard import AnalysisForbiddenError, analysis_interlock
from app.models import Hand, ImportFile, Tournament
from app.schemas.api import AnalyzerSettings
from app.services.importer import import_pair


FIXTURES = Path(__file__).parents[2] / "fixtures"
HANDS = FIXTURES / "expresso_synthetic_hands.txt"
SUMMARY = FIXTURES / "expresso_synthetic_summary.txt"


def settings() -> AnalyzerSettings:
    return AnalyzerSettings(history_paths=[str(FIXTURES)], hero_name="HERO")


def test_import_is_transactional_and_idempotent(db) -> None:
    reference = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    assert import_pair(db, HANDS, SUMMARY, settings(), reference) == "imported"
    assert db.scalar(select(func.count(Tournament.id))) == 1
    assert db.scalar(select(func.count(Hand.id))) == 8
    tournament = db.scalar(select(Tournament))
    assert tournament is not None
    assert tournament.external_id == "4242424242"
    assert float(tournament.total_buyin) == 2
    assert float(tournament.reward) == 4
    assert tournament.final_rank == 1
    assert tournament.total_hands == 8
    assert tournament.chip_delta == 400
    assert import_pair(db, HANDS, SUMMARY, settings(), reference) == "skipped"
    assert db.scalar(select(func.count(Tournament.id))) == 1
    assert db.scalar(select(func.count(Hand.id))) == 8
    assert set(db.scalars(select(ImportFile.state)).all()) == {"imported"}


def test_recent_files_wait_even_with_final_summary(db) -> None:
    reference = datetime.fromtimestamp(HANDS.stat().st_mtime, UTC)
    assert import_pair(db, HANDS, SUMMARY, settings(), reference) == "waiting"
    assert db.scalar(select(func.count(Tournament.id))) == 0
    assert set(db.scalars(select(ImportFile.state)).all()) == {"waiting_for_completion"}


def test_guard_trip_after_parsing_rolls_back_without_import_state(db, monkeypatch) -> None:
    checks = 0

    def stop_after_parse() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise AnalysisForbiddenError("synthetic runtime detection")

    monkeypatch.setattr(analysis_interlock, "ensure_allowed", stop_after_parse)
    reference = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(AnalysisForbiddenError):
        import_pair(db, HANDS, SUMMARY, settings(), reference)
    assert checks >= 2
    assert db.scalar(select(func.count(Tournament.id))) == 0
    assert db.scalar(select(func.count(Hand.id))) == 0
    assert db.scalar(select(func.count(ImportFile.id))) == 0
