from __future__ import annotations

from datetime import datetime

import pytest

from app.analytics import (
    UNKNOWN_OPPONENT_MESSAGE,
    calculate_chip_ev,
    calculate_dashboard,
    calculate_equity,
    calculate_hero_stats,
    calculate_itm,
    calculate_roi,
    calculate_segmented_stats,
    classify_hand,
    detect_leaks,
    group_sessions,
)


def test_dashboard_roi_itm_places_hourly_and_downswing() -> None:
    tournaments = [
        {
            "id": "T1",
            "started_at": "2026-01-01T10:00:00",
            "buy_in": 10,
            "winnings": 50,
            "rank": 1,
            "duration_seconds": 600,
            "hands_count": 12,
        },
        {
            "id": "T2",
            "started_at": "2026-01-01T11:00:00",
            "buy_in": 10,
            "winnings": 0,
            "rank": 2,
            "duration_seconds": 600,
            "hands_count": 8,
        },
        {
            "id": "T3",
            "started_at": "2026-01-02T09:00:00",
            "buy_in": 10,
            "winnings": 0,
            "rank": 3,
            "duration_seconds": 600,
            "hands_count": 10,
        },
    ]

    dashboard = calculate_dashboard(tournaments)

    assert dashboard["games_count"] == 3
    assert dashboard["hands_count"] == 30
    assert dashboard["total_buy_ins"] == 30
    assert dashboard["total_winnings"] == 50
    assert dashboard["net_result"] == 20
    assert dashboard["roi_percent"] == pytest.approx(66.67, abs=0.01)
    assert dashboard["itm_percent"] == pytest.approx(33.33, abs=0.01)
    assert dashboard["win_rate_percent"] == pytest.approx(33.33, abs=0.01)
    assert dashboard["second_place_rate_percent"] == pytest.approx(33.33, abs=0.01)
    assert dashboard["third_place_rate_percent"] == pytest.approx(33.33, abs=0.01)
    assert dashboard["hourly_gain"] == 40
    assert dashboard["biggest_downswing"] == 20
    assert [point["cumulative"] for point in dashboard["bankroll_curve"]] == [40, 30, 20]
    assert [row["period"] for row in dashboard["results_by_day"]] == ["2026-01-01", "2026-01-02"]
    assert dashboard["ev_curve"] == []  # never invent an unavailable EV curve


def test_empty_dashboard_has_null_derived_rates() -> None:
    dashboard = calculate_dashboard([])
    assert dashboard["games_count"] == 0
    assert dashboard["roi_percent"] is None
    assert dashboard["itm_percent"] is None
    assert dashboard["hourly_gain"] is None


def test_individual_roi_itm_helpers_and_incomplete_guard() -> None:
    tournaments = [
        {"id": "done", "buy_in": 2, "winnings": 6, "rank": 1, "completed": True},
        {"id": "active", "buy_in": 50, "winnings": 500, "rank": 1, "completed": False},
    ]
    assert calculate_roi(tournaments) == pytest.approx(200.0)
    assert calculate_itm(tournaments) == pytest.approx(100.0)
    assert calculate_dashboard(tournaments)["games_count"] == 1


def test_chip_ev_uses_only_complete_observed_chip_deltas() -> None:
    tournaments = [
        {"id": "T1", "hero_chip_delta": 100},
        {"id": "T2", "hero_chip_delta": -50},
        {"id": "T3", "buy_in": 5, "winnings": 20},  # money is not a chip substitute
    ]

    result = calculate_chip_ev(tournaments)

    assert result["available"] is True
    assert result["games_count"] == 2
    assert result["total_chip_delta"] == 50
    assert result["chip_ev_per_game"] == 25
    assert result["excluded_tournaments"] == [{"tournament_id": "T3", "reason": "missing_chip_deltas"}]


def test_chip_ev_can_sum_complete_hand_deltas_and_reject_partial_data() -> None:
    tournaments = [
        {"id": "T1", "hands_count": 2, "completed": True},
        {"id": "T2", "hands_count": 2, "completed": True},
    ]
    hands = [
        {"tournament_id": "T1", "hero_chip_delta": 30},
        {"tournament_id": "T1", "hero_chip_delta": -10},
        {"tournament_id": "T2", "hero_chip_delta": 5},
    ]

    result = calculate_chip_ev(tournaments, hands)

    assert result["chip_ev_per_game"] == 20
    assert result["games_count"] == 1
    assert {row["tournament_id"]: row["reason"] for row in result["excluded_tournaments"]} == {"T2": "missing_hands"}


def test_chip_ev_accepts_parser_hero_net_as_exact_hand_delta() -> None:
    result = calculate_chip_ev(
        [{"tournament_id": "T", "complete": True, "hands_count": 2}],
        [
            {"tournament_id": "T", "complete": True, "hero_net": 80},
            {"tournament_id": "T", "complete": True, "hero_net": -20},
        ],
    )
    assert result["chip_ev_per_game"] == 60


def test_sessions_split_only_after_more_than_configured_idle_gap() -> None:
    tournaments = [
        {"id": "T1", "started_at": datetime(2026, 1, 1, 10, 0), "duration_seconds": 300, "buy_in": 1, "winnings": 0},
        # 15 minutes after T1 ended: same session.
        {"id": "T2", "started_at": datetime(2026, 1, 1, 10, 20), "duration_seconds": 600, "buy_in": 1, "winnings": 4},
        # Exactly 30 minutes after T2 ended: still same session.
        {"id": "T3", "started_at": datetime(2026, 1, 1, 11, 0), "duration_seconds": 300, "buy_in": 1, "winnings": 0},
        # 31 minutes after T3 ended: a new session.
        {"id": "T4", "started_at": datetime(2026, 1, 1, 11, 36), "duration_seconds": 300, "buy_in": 1, "winnings": 2},
    ]

    sessions = group_sessions(tournaments, gap_minutes=30)

    assert [session["games_count"] for session in sessions] == [3, 1]
    assert sessions[0]["net_result"] == 1
    assert sessions[0]["roi_percent"] == pytest.approx(33.33, abs=0.01)
    assert sessions[0]["tournament_ids"] == ["T1", "T2", "T3"]
    assert sessions[1]["tournament_ids"] == ["T4"]


def _action(player: str, action: str, order: int) -> dict[str, object]:
    return {"player_name": player, "street": "preflop", "action_type": action, "sequence": order}


def test_vpip_pfr_and_three_bet_use_opportunity_denominators() -> None:
    hands = [
        {"id": "H1", "hero_name": "Hero", "hero_hole_cards": ["As", "Kd"], "actions": [_action("Hero", "raise", 1)]},
        {
            "id": "H2",
            "hero_name": "Hero",
            "hero_hole_cards": ["7s", "7d"],
            "actions": [_action("Villain", "raise", 1), _action("Hero", "call", 2)],
        },
        {
            "id": "H3",
            "hero_name": "Hero",
            "hero_hole_cards": ["Ah", "Qh"],
            "actions": [_action("Villain", "raise", 1), _action("Hero", "raise", 2)],
        },
        {"id": "H4", "hero_name": "Hero", "hero_hole_cards": ["3s", "2d"], "actions": [_action("Hero", "fold", 1)]},
    ]

    stats = calculate_hero_stats(hands)

    assert stats["vpip"] == {"numerator": 3, "denominator": 4, "percentage": 75.0}
    assert stats["pfr"] == {"numerator": 2, "denominator": 4, "percentage": 50.0}
    assert stats["three_bet"] == {"numerator": 1, "denominator": 2, "percentage": 50.0}
    assert stats["call_vs_open"] == {"numerator": 1, "denominator": 2, "percentage": 50.0}


def test_postflop_frequencies_use_actual_opportunities() -> None:
    hands = [
        {
            "id": "cbet",
            "hero_name": "Hero",
            "hero_hole_cards": ["As", "Kd"],
            "board": ["2c", "7d", "Jh"],
            "actions": [
                _action("Hero", "raise", 1),
                _action("Villain", "call", 2),
                {"player_name": "Hero", "street": "flop", "action_type": "bet", "sequence": 3},
                {"player_name": "Villain", "street": "flop", "action_type": "fold", "sequence": 4},
            ],
        },
        {
            "id": "fold-to-cbet",
            "hero_name": "Hero",
            "hero_hole_cards": ["8s", "7s"],
            "board": ["Ac", "Qd", "3h"],
            "actions": [
                _action("Villain", "raise", 1),
                _action("Hero", "call", 2),
                {"player_name": "Villain", "street": "flop", "action_type": "bet", "sequence": 3},
                {"player_name": "Hero", "street": "flop", "action_type": "fold", "sequence": 4},
            ],
        },
    ]
    stats = calculate_hero_stats(hands)
    assert stats["cbet_flop"] == {"numerator": 1, "denominator": 1, "percentage": 100.0}
    assert stats["fold_vs_cbet"] == {"numerator": 1, "denominator": 1, "percentage": 100.0}


def test_villain_showdown_is_not_attributed_to_hero_after_preflop_fold() -> None:
    stats = calculate_hero_stats(
        [
            {
                "id": "hero-folded",
                "hero_name": "Hero",
                "hero_hole_cards": ["8s", "2d"],
                "board": ["Ac", "Kd", "Qh", "4s", "5c"],
                "reached_showdown": True,
                "actions": [
                    _action("Hero", "fold", 1),
                    _action("Villain1", "raise", 2),
                    _action("Villain2", "call", 3),
                ],
            }
        ]
    )
    assert stats["went_to_showdown"]["numerator"] == 0
    assert stats["went_to_showdown"]["denominator"] == 0


def test_hu_button_and_effective_stack_use_parser_player_data() -> None:
    hand = {
        "id": "hu-button",
        "hero_name": "Hero",
        "big_blind": 20,
        "max_players": 2,
        "hero_hole_cards": ["As", "9s"],
        "players": [
            {"name": "Hero", "position": "SB", "is_button": True, "starting_stack": 430},
            {"name": "Villain", "position": "BB", "starting_stack": 170},
        ],
        "actions": [_action("Hero", "raise", 1)],
    }
    segmented = calculate_segmented_stats([hand], "Hero")
    assert segmented["by_position"]["BTN"]["hands"] == 1
    assert segmented["by_stack_depth"]["5-10 BB"]["hands"] == 1  # effective stack = 170 / 20 = 8.5 BB


def test_equity_exact_known_cards_and_ev() -> None:
    result = calculate_equity(
        ["As", "Ah"],
        ["Kc", "Kd"],
        ["2c", "3d", "4h", "5s", "9c"],
        final_pot=200,
        hero_investment=100,
        actual_result=100,
    )

    assert result["available"] is True
    assert result["method"] == "exact"
    assert result["win_probability"] == 100
    assert result["tie_probability"] == 0
    assert result["loss_probability"] == 0
    assert result["equity_percent"] == 100
    assert result["ev_chips"] == 100
    assert result["actual_minus_ev_chips"] == 0


def test_equity_refuses_to_reconstruct_unknown_opponent_cards() -> None:
    result = calculate_equity(["As", "Ah"], None, ["2c", "3d", "4h"])
    assert result["available"] is False
    assert result["message"] == UNKNOWN_OPPONENT_MESSAGE
    assert result["equity_percent"] is None


def test_equity_counts_a_board_play_as_a_tie() -> None:
    result = calculate_equity(
        ["2c", "3d"],
        ["4s", "5c"],
        ["Ah", "Kh", "Qh", "Jh", "Th"],
    )
    assert result["tie_probability"] == 100
    assert result["equity_percent"] == 50


def test_leak_rule_is_transparent_and_threshold_is_configurable() -> None:
    stats = {
        "hands": 20,
        "vpip": {"numerator": 14, "denominator": 20, "percentage": 70.0},
        "pfr": {"numerator": 8, "denominator": 20, "percentage": 40.0},
    }
    alerts = detect_leaks(stats, thresholds={"minimum_observations": 20, "vpip_max": 55, "vpip_pfr_gap_max": 50})
    vpip_alert = next(alert for alert in alerts if alert["code"] == "vpip_high")
    assert vpip_alert["observed_statistic"] == 70
    assert vpip_alert["threshold_used"] == {"operator": ">", "value": 55.0}
    assert "GTO absolue" in vpip_alert["disclaimer"]


def test_classification_never_uses_a_loss_as_proof_of_a_mistake() -> None:
    result = classify_hand(
        {
            "id": "H-loss",
            "hero_hole_cards": ["As", "Ks"],
            "hero_net": -500,
            "actions": [{"action_type": "raise", "amount": 40, "pot_before": 100}],
        }
    )
    assert result["classification"] == "standard"
    assert result["decision_quality"] == "no_signal"
    assert result["financial_result"] == {"known": True, "amount": -500.0, "outcome": "loss"}
