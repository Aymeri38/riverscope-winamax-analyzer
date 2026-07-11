from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.process_guard import AnalysisForbiddenError, AnalysisInterlock
from app.main import app
from app.models import (
    Action,
    BoardCard,
    Hand,
    HeroHoleCard,
    ImportError,
    ImportFile,
    Player,
    Tournament,
)
from app.schemas.api import AnalyzerSettings
from app.services.data_management import export_tournaments_csv
from app.services.contribution import (
    COUNT_BUCKETS,
    build_contribution_preview,
    count_bucket,
    rounded_percentage,
)
from app.services.settings import save_settings


PRIVATE_ALIAS = "SyntheticPrivateAlias"
PRIVATE_PATH = r"C:\Users\PrivatePerson\Winamax Poker\history\secret.txt"
PRIVATE_EXTERNAL_ID = "987654321012345"
PRIVATE_DATE = "2037-05-06T07:08:09"
PRIVATE_CARDS = "As Kd Qh"
PRIVATE_NOTE = "SECRET_NOTE_NEVER_EXPORT"
PRIVATE_HASH = "feedface" * 8


def _seed_private_completed_data(db) -> None:
    tournament = Tournament(
        external_id=PRIVATE_EXTERNAL_ID,
        name=f"Expresso {PRIVATE_ALIAS}",
        started_at=datetime(2037, 5, 6, 7, 8, 9),
        ended_at=datetime(2037, 5, 6, 7, 18, 9),
        is_expresso=True,
        is_nitro=False,
        currency="EUR",
        buyin_amount=Decimal("777777"),
        fee_amount=Decimal("12345"),
        total_buyin=Decimal("790122"),
        multiplier=Decimal("99"),
        prize_pool=Decimal("888888"),
        reward=Decimal("999999"),
        ticket=f"ticket-{PRIVATE_ALIAS}",
        final_rank=1,
        duration_seconds=601,
        total_hands=1,
        registered_players=3,
        hero_name=PRIVATE_ALIAS,
        initial_stack=777777,
        final_stack=888888,
        chip_delta=111111,
        source_path=PRIVATE_PATH,
        completed=True,
        tags_json=json.dumps([PRIVATE_NOTE]),
        notes=PRIVATE_NOTE,
    )
    db.add(tournament)
    db.flush()

    player = Player(
        name_key=PRIVATE_HASH,
        display_name=PRIVATE_ALIAS,
        is_hero=True,
        anonymized_label=f"alias-{PRIVATE_ALIAS}",
    )
    db.add(player)
    db.flush()

    hand = Hand(
        external_id=f"hand-{PRIVATE_EXTERNAL_ID}",
        tournament_id=tournament.id,
        hand_number=424242,
        played_at=datetime(2037, 5, 6, 7, 9, 9),
        small_blind=777777,
        big_blind=888888,
        ante=999999,
        active_players=3,
        max_players=3,
        total_pot=7654321,
        hero_net=-654321,
        is_all_in=True,
        reached_showdown=True,
        board_text=PRIVATE_CARDS,
        action_text=f"{PRIVATE_ALIAS} raises 777777 with {PRIVATE_CARDS}",
        notes=PRIVATE_NOTE,
        tags_json=json.dumps([PRIVATE_NOTE]),
    )
    db.add(hand)
    db.flush()
    db.add_all(
        [
            HeroHoleCard(hand_id=hand.id, position=0, rank="A", suit="s"),
            HeroHoleCard(hand_id=hand.id, position=1, rank="K", suit="d"),
            BoardCard(hand_id=hand.id, street="flop", position=0, rank="Q", suit="h"),
            Action(
                hand_id=hand.id,
                player_id=player.id,
                sequence=7001,
                street="preflop",
                action_type="raise",
                amount=777777,
                to_amount=888888,
                pot_after=999999,
            ),
            Action(
                hand_id=hand.id,
                player_id=player.id,
                sequence=7002,
                street=PRIVATE_DATE,
                action_type=PRIVATE_ALIAS,
                amount=777777,
            ),
            Action(
                hand_id=hand.id,
                player_id=player.id,
                sequence=7003,
                street=PRIVATE_PATH,
                action_type=PRIVATE_NOTE,
                amount=777777,
            ),
        ]
    )

    imported = ImportFile(
        path=PRIVATE_PATH,
        file_hash=PRIVATE_HASH,
        file_type="hand_history",
        size_bytes=777777,
        modified_at=datetime(2037, 5, 6, 7, 8, 9),
        state="imported",
        tournament_id=tournament.id,
    )
    db.add(imported)
    db.flush()
    db.add_all(
        [
            ImportError(
                import_file_id=imported.id,
                line_number=424242,
                line_hash=PRIVATE_HASH,
                sanitized_line=f"{PRIVATE_ALIAS} {PRIVATE_CARDS} {PRIVATE_PATH}",
                error_code="unknown_hand_line",
                message=PRIVATE_NOTE,
            ),
            ImportError(
                import_file_id=imported.id,
                line_number=424243,
                line_hash="a" * 64,
                sanitized_line=PRIVATE_DATE,
                error_code=PRIVATE_ALIAS,
                message=PRIVATE_PATH,
            ),
            ImportError(
                import_file_id=imported.id,
                line_number=424244,
                line_hash="b" * 64,
                sanitized_line=PRIVATE_NOTE,
                error_code=PRIVATE_NOTE,
                message=PRIVATE_EXTERNAL_ID,
            ),
        ]
    )

    # A non-completed tournament must not influence any aggregate.
    incomplete = Tournament(
        external_id=f"incomplete-{PRIVATE_EXTERNAL_ID}",
        name=PRIVATE_NOTE,
        started_at=datetime(2037, 5, 6, 8, 8, 9),
        is_expresso=True,
        currency="EUR",
        buyin_amount=Decimal("1"),
        fee_amount=Decimal("0"),
        total_buyin=Decimal("1"),
        prize_pool=Decimal("3"),
        reward=Decimal("0"),
        total_hands=0,
        registered_players=3,
        hero_name=PRIVATE_ALIAS,
        completed=False,
    )
    db.add(incomplete)
    db.commit()


def _assert_canonical_and_private(body: dict[str, object]) -> dict[str, object]:
    payload = str(body["payload"])
    payload_bytes = payload.encode("utf-8")
    assert body["byte_size"] == len(payload_bytes)
    assert body["sha256"] == hashlib.sha256(payload_bytes).hexdigest()
    decoded = json.loads(payload)
    assert payload == json.dumps(
        decoded,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"

    for canary in (
        PRIVATE_ALIAS,
        PRIVATE_PATH,
        PRIVATE_EXTERNAL_ID,
        PRIVATE_DATE,
        PRIVATE_CARDS,
        PRIVATE_NOTE,
        PRIVATE_HASH,
        "777777",
        "424242",
        "7001",
    ):
        assert canary not in payload

    forbidden_keys = {
        "date",
        "generated_at",
        "user",
        "pseudo",
        "path",
        "external_id",
        "file_hash",
        "line_hash",
        "cards",
        "board",
        "notes",
        "tags",
        "line",
        "message",
        "amount",
        "sequence",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(decoded)
    return decoded


def test_count_privacy_transformations_are_coarse() -> None:
    labels = [label for _minimum, _maximum, label in COUNT_BUCKETS] + ["1000+"]
    assert [count_bucket(value) for value in (0, 1, 5, 10, 25, 50, 100, 250, 500, 1000)] == labels
    assert rounded_percentage(1, 3) == 35
    assert rounded_percentage(2, 3) == 65
    assert rounded_percentage(0, 0) == 0


def test_local_preview_is_canonical_aggregate_and_contains_no_canary(db) -> None:
    _seed_private_completed_data(db)
    preview = build_contribution_preview(db)
    body = preview.model_dump()
    decoded = _assert_canonical_and_private(body)

    assert body["filename"] == "winamax-analyzer-contribution.json"
    assert body["media_type"] == "application/json"
    assert body["encoding"] == "utf-8"
    assert body["network_sent"] is False
    assert decoded["scope"] == {
        "actions": "1-4",
        "completed_tournaments": "1-4",
        "hands": "1-4",
        "parser_diagnostics": "1-4",
    }
    assert decoded["actions"] == [
        {"count_bucket": "1-4", "percentage": 65, "street": "other", "type": "other"},
        {"count_bucket": "1-4", "percentage": 35, "street": "preflop", "type": "raise"},
    ]
    assert decoded["parser_diagnostics"] == [
        {"count_bucket": "1-4", "error_code": "other", "percentage": 65},
        {"count_bucket": "1-4", "error_code": "unknown_hand_line", "percentage": 35},
    ]


def test_preview_api_empty_database_and_exact_digest(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    with TestClient(app) as client:
        response = client.get("/api/contributions/preview")
    assert response.status_code == 200
    body = response.json()
    decoded = _assert_canonical_and_private(body)
    assert body["network_sent"] is False
    assert decoded["scope"] == {
        "actions": "0",
        "completed_tournaments": "0",
        "hands": "0",
        "parser_diagnostics": "0",
    }
    assert decoded["actions"] == []
    assert decoded["parser_diagnostics"] == []


def test_preview_api_refuses_when_file_guard_is_active(db, tmp_path) -> None:
    active = tmp_path / "active-Expresso.txt"
    active.write_text("Winamax Poker - active", encoding="utf-8")
    save_settings(
        db,
        AnalyzerSettings(history_paths=[str(tmp_path)], hero_name="HERO"),
    )
    with TestClient(app) as client:
        response = client.get("/api/contributions/preview")
    assert response.status_code == 423
    assert "payload" not in response.text


def test_preview_refuses_a_tripped_process_interlock(db) -> None:
    interlock = AnalysisInterlock()
    interlock.trip("synthetic Winamax detection")
    with pytest.raises(AnalysisForbiddenError):
        build_contribution_preview(db, interlock=interlock)


def test_anonymized_csv_removes_correlatable_identifiers(db) -> None:
    _seed_private_completed_data(db)
    exported = export_tournaments_csv(db, anonymize=True)
    assert "T000001" in exported
    assert "HERO" in exported
    for canary in (
        PRIVATE_ALIAS,
        PRIVATE_EXTERNAL_ID,
        PRIVATE_DATE,
        PRIVATE_PATH,
        PRIVATE_NOTE,
    ):
        assert canary not in exported
