from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.parsers import is_complete, parse_hand_history, parse_tournament_summary


FIXTURES = Path(__file__).parents[2] / "fixtures"
HANDS = FIXTURES / "expresso_synthetic_hands.txt"
SUMMARY = FIXTURES / "expresso_synthetic_summary.txt"
INCOMPLETE = FIXTURES / "expresso_synthetic_incomplete.txt"


def test_parse_fully_synthetic_expresso_hands() -> None:
    result = parse_hand_history(HANDS)

    assert result.encoding == "utf-8"
    assert result.complete is True
    assert len(result.hands) == 8
    assert result.issues == []

    first = result.hands[0]
    assert first.tournament_id == "4242424242"
    assert first.tournament_name == "Expresso Synthetic"
    assert first.hand_number == 1
    assert first.level == 1
    assert first.buy_in_amount == Decimal("1.80")
    assert first.fee_amount == Decimal("0.20")
    assert first.currency == "EUR"
    assert first.small_blind == Decimal("5")
    assert first.big_blind == Decimal("10")
    assert first.max_players == 3
    assert first.button_seat == 2
    assert first.hero_name == "HERO"
    assert len(first.hero_cards) == 2
    assert first.total_pot == Decimal("15")
    assert first.rake == 0
    assert {player.name for player in first.players} == {"HERO", "VILLAIN_1", "VILLAIN_2"}
    assert any(action.action_type == "fold" and action.actor == "HERO" for action in first.actions)


def test_parse_streets_actions_board_showdown_and_all_in() -> None:
    result = parse_hand_history(HANDS, hero_name="HERO")
    second = result.hands[1]

    assert len(second.board) == 5
    assert second.reached_showdown is True
    assert second.is_all_in is True
    assert second.total_pot == Decimal("405")
    assert second.hero_net == Decimal("200")
    assert {action.street for action in second.actions} >= {"preflop", "flop", "turn", "river", "showdown"}
    assert [award.pot_name for award in second.awards] == ["main pot", "side pot 1"]
    assert [award.amount for award in second.awards] == [Decimal("400"), Decimal("5")]
    assert all(player.position in {"BTN", "SB", "BB"} for player in second.players)


def test_parse_tournament_summary() -> None:
    summary = parse_tournament_summary(SUMMARY)

    assert summary.complete is True
    assert summary.issues == []
    assert summary.tournament_id == "4242424242"
    assert summary.name == "Expresso Synthetic"
    assert summary.hero_name == "HERO"
    assert summary.buy_in_amount == Decimal("1.80")
    assert summary.fee_amount == Decimal("0.20")
    assert summary.total_buy_in == Decimal("2.00")
    assert summary.prize_pool == Decimal("4")
    assert summary.multiplier == Decimal("2")
    assert summary.registered_players == 3
    assert summary.final_rank == 1
    assert summary.reward == Decimal("4")
    assert summary.duration_seconds == 300
    assert summary.is_expresso is True
    assert summary.is_nitro is False


def test_incomplete_hand_and_missing_summary_are_never_complete() -> None:
    result = parse_hand_history(INCOMPLETE)
    summary = parse_tournament_summary(SUMMARY)

    assert len(result.hands) == 1
    assert result.complete is False
    assert result.hands[0].complete is False
    assert "missing_hand_summary" in {issue.code for issue in result.issues}
    assert is_complete(result, summary) is False
    assert is_complete(result) is False
    assert is_complete(summary) is False

    no_rank_text = SUMMARY.read_text(encoding="utf-8").replace("You finished in 1st place\n", "")
    no_rank = parse_tournament_summary(no_rank_text)
    assert no_rank.complete is False
    assert "missing_final_rank" in {issue.code for issue in no_rank.issues}
    assert is_complete(parse_hand_history(HANDS), no_rank) is False


def test_cp1252_french_summary() -> None:
    text = """Winamax Poker - Résumé du tournoi : Expresso(3030303030)
Joueur : HERO
Droits d'entrée : 1,80€ + 0,20€
Joueurs inscrits : 3
Cagnotte : 4€
Tournoi commencé 2018/04/03 10:00:00 UTC
Vous avez joué 3min 5s
Vous avez terminé à la 2e place
Vous avez gagné 0€
"""
    summary = parse_tournament_summary(text.encode("cp1252"))

    assert summary.encoding == "cp1252"
    assert summary.complete is True
    assert summary.tournament_id == "3030303030"
    assert summary.buy_in_amount == Decimal("1.80")
    assert summary.fee_amount == Decimal("0.20")
    assert summary.prize_pool == Decimal("4")
    assert summary.final_rank == 2
    assert summary.duration_seconds == 185
    assert summary.reward == 0
    assert summary.issues == []


def test_utf8_bom_and_direct_text_inputs() -> None:
    data = b"\xef\xbb\xbf" + HANDS.read_bytes()
    from_bytes = parse_hand_history(data)
    from_text = parse_hand_history(HANDS.read_text(encoding="utf-8"))

    assert from_bytes.encoding == "utf-8-sig"
    assert len(from_bytes.hands) == len(from_text.hands) == 8
    assert from_bytes.source_hash != from_text.source_hash


def test_duplicate_hand_ids_are_idempotently_ignored() -> None:
    text = HANDS.read_text(encoding="utf-8")
    result = parse_hand_history(text + "\n" + text)

    assert len(result.hands) == 8
    assert sum(issue.code == "duplicate_hand" for issue in result.issues) == 8


def test_unknown_line_creates_privacy_sanitized_issue() -> None:
    private_alias = "SyntheticPrivateAlias"
    text = INCOMPLETE.read_text(encoding="utf-8").replace("VILLAIN_1", private_alias)
    inserted = text.replace("*** PRE-FLOP ***", f"{private_alias} performs mystery [As Kd]\n*** PRE-FLOP ***")
    result = parse_hand_history(inserted)
    issue = next(issue for issue in result.issues if issue.code == "unknown_hand_line")

    assert issue.line_number is not None
    assert issue.line_excerpt is not None
    assert "As" not in issue.line_excerpt
    assert "Kd" not in issue.line_excerpt
    assert "[CARDS]" in issue.line_excerpt
    assert private_alias not in issue.line_excerpt
    assert "VILLAIN_" in issue.line_excerpt


def test_completion_requires_quiet_last_hand_and_matching_tournament() -> None:
    hands = parse_hand_history(HANDS)
    summary = parse_tournament_summary(SUMMARY)
    assert hands.last_hand_at is not None

    assert is_complete(hands, summary, now=hands.last_hand_at + timedelta(seconds=59)) is False
    assert (
        is_complete(
            hands,
            summary,
            now=hands.last_hand_at + timedelta(seconds=59),
            quiet_period_seconds=1,
        )
        is False
    )
    assert is_complete(hands, summary, now=hands.last_hand_at + timedelta(seconds=60)) is True

    other = parse_tournament_summary(
        SUMMARY.read_text(encoding="utf-8").replace("4242424242", "5151515151")
    )
    assert is_complete(hands, other, now=hands.last_hand_at + timedelta(hours=1)) is False


def test_empty_or_unrelated_document_reports_no_hands() -> None:
    for payload in (b"", "not a hand history"):
        result = parse_hand_history(payload)

        assert result.hands == []
        assert any(issue.code == "no_hands" and issue.severity == "error" for issue in result.issues)
