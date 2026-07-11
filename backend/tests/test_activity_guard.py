from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.api import AnalyzerSettings
from app.services.activity_guard import detect_active_tournaments


TEST_ROOT = Path(__file__).parents[1] / ".test-data" / "active-history"


def test_recent_or_unpaired_expresso_is_conservatively_active() -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    hand = TEST_ROOT / "synthetic_active_Expresso.txt"
    hand.write_text(
        'Winamax Poker - Tournament "Expresso" buyIn: 1.00€ + 0.00€ level: 1 '
        '- HandId: #6600000000000000001-1-1000000001 - Holdem no limit (5/10) - 2020/01/03 10:00:00 UTC\n',
        encoding="utf-8",
    )
    settings = AnalyzerSettings(history_paths=[str(TEST_ROOT)], hero_name="HERO")
    try:
        result = detect_active_tournaments(settings, now=datetime(2020, 1, 3, 10, 0, 30, tzinfo=UTC))
        assert result["active"] is True
        assert result["reason_count"] == 1
        assert "récemment modifié" in result["reasons"][0]["reason"] or "résumé final absent" in result["reasons"][0]["reason"]
    finally:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)


def test_completed_old_pair_is_not_active() -> None:
    fixtures = Path(__file__).parents[2] / "fixtures"
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    hand = TEST_ROOT / "synthetic_Expresso_history.txt"
    summary = TEST_ROOT / "synthetic_Expresso_history_summary.txt"
    shutil.copy2(fixtures / "expresso_synthetic_hands.txt", hand)
    shutil.copy2(fixtures / "expresso_synthetic_summary.txt", summary)
    settings = AnalyzerSettings(history_paths=[str(TEST_ROOT)], hero_name="HERO")
    try:
        result = detect_active_tournaments(settings, now=datetime(2027, 1, 1, tzinfo=UTC))
        assert result["active"] is False
        assert result["checked_tournaments"] == 1
    finally:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
