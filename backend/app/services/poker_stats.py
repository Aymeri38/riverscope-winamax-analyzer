from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.models import Action, Hand, HandPlayer


AGGRESSIVE = {"bet", "raise", "shove"}
VOLUNTARY = {"call", "bet", "raise", "shove"}


def _kind(action: Action) -> str:
    value = action.action_type.casefold().replace("-", "_")
    aliases = {
        "folds": "fold",
        "calls": "call",
        "checks": "check",
        "bets": "bet",
        "raises": "raise",
        "posts": "post",
        "collected": "collect",
    }
    return aliases.get(value, value)


def _metric(numerator: int, denominator: int) -> dict[str, float | int | None]:
    return {
        "value": round(numerator / denominator * 100, 2) if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _hero_entry(hand: Hand) -> HandPlayer | None:
    return next((entry for entry in hand.player_entries if entry.player.is_hero), None)


def calculate_hero_stats(hands: list[Hand], include_slices: bool = True) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    denominator: Counter[str] = Counter()

    for hand in hands:
        hero = _hero_entry(hand)
        if hero is None:
            continue
        actions = sorted(hand.actions, key=lambda action: action.sequence)
        pre = [action for action in actions if action.street in {"preflop", "pre-flop", "ante_blinds"}]
        voluntary_pre = [
            action
            for action in pre
            if not _kind(action).startswith("post_")
            and _kind(action) not in {"post", "collect", "show", "muck", "uncalled_return"}
        ]
        hero_pre = [action for action in voluntary_pre if action.player_id == hero.player_id]
        denominator["hands"] += 1

        if any(_kind(action) in VOLUNTARY for action in hero_pre):
            counters["vpip"] += 1
        if any(_kind(action) in {"raise", "shove"} for action in hero_pre):
            counters["pfr"] += 1

        first_hero_index = next(
            (index for index, action in enumerate(voluntary_pre) if action.player_id == hero.player_id), None
        )
        before_hero = voluntary_pre[:first_hero_index] if first_hero_index is not None else voluntary_pre
        first_hero = voluntary_pre[first_hero_index] if first_hero_index is not None else None
        opponent_opened = any(
            action.player_id != hero.player_id and _kind(action) in {"raise", "shove"} for action in before_hero
        )
        any_limp_before = any(
            action.player_id != hero.player_id and _kind(action) == "call" for action in before_hero
        )

        if first_hero and _kind(first_hero) == "call" and not opponent_opened:
            counters["limp"] += 1
            later = voluntary_pre[first_hero_index + 1 :]  # type: ignore[operator]
            faced_raise_after_limp = any(
                action.player_id != hero.player_id and _kind(action) in {"raise", "shove"} for action in later
            )
            if faced_raise_after_limp:
                denominator["limp_response"] += 1
                hero_after = [action for action in later if action.player_id == hero.player_id]
                response = _kind(hero_after[-1]) if hero_after else None
                if response == "fold":
                    counters["limp_fold"] += 1
                elif response == "call":
                    counters["limp_call"] += 1
                elif response in {"raise", "shove"}:
                    counters["limp_raise"] += 1

        if first_hero and _kind(first_hero) in {"raise", "shove"} and not opponent_opened:
            counters["open_raise"] += 1
        if first_hero and not opponent_opened:
            denominator["open_opportunity"] += 1

        if opponent_opened and first_hero:
            denominator["face_open"] += 1
            response = _kind(first_hero)
            if response == "fold":
                counters["fold_face_open"] += 1
            elif response == "call":
                counters["call_face_open"] += 1
            elif response in {"raise", "shove"}:
                counters["three_bet"] += 1

        if hero.position in {"SB", "BB"} and first_hero:
            denominator["oop_decisions"] += 1
            if _kind(first_hero) == "call":
                counters["oop_call"] += 1

        hero_first_raise_index = next(
            (
                index
                for index, action in enumerate(voluntary_pre)
                if action.player_id == hero.player_id and _kind(action) in {"raise", "shove"}
            ),
            None,
        )
        if hero_first_raise_index is not None:
            after_raise = voluntary_pre[hero_first_raise_index + 1 :]
            opponent_reraise_index = next(
                (
                    index
                    for index, action in enumerate(after_raise)
                    if action.player_id != hero.player_id and _kind(action) in {"raise", "shove"}
                ),
                None,
            )
            if opponent_reraise_index is not None:
                denominator["face_three_bet"] += 1
                responses = [
                    action
                    for action in after_raise[opponent_reraise_index + 1 :]
                    if action.player_id == hero.player_id
                ]
                if responses and _kind(responses[0]) == "fold":
                    counters["fold_face_three_bet"] += 1

        if any(action.player_id == hero.player_id and action.is_all_in for action in pre):
            counters["shove"] += 1
        opponent_shove_index = next(
            (
                index
                for index, action in enumerate(pre)
                if action.player_id != hero.player_id and action.is_all_in
            ),
            None,
        )
        if opponent_shove_index is not None:
            denominator["face_shove"] += 1
            if any(
                action.player_id == hero.player_id and _kind(action) in {"call", "raise", "shove"}
                for action in pre[opponent_shove_index + 1 :]
            ):
                counters["call_shove"] += 1

        if hero.position == "BB":
            denominator["bb_hands"] += 1
            if all(
                _kind(action) == "fold"
                for action in voluntary_pre
                if action.player_id != hero.player_id
            ) and not hero_pre:
                counters["bb_walk"] += 1

        flop = [action for action in actions if action.street == "flop"]
        turn = [action for action in actions if action.street == "turn"]
        river = [action for action in actions if action.street == "river"]
        hero_folded_preflop = any(
            action.player_id == hero.player_id and _kind(action) == "fold" for action in pre
        )
        saw_flop = bool(hand.board_cards) and not hero_folded_preflop
        hero_won = hero.won > 0
        if saw_flop:
            denominator["saw_flop"] += 1
            if hero_won:
                counters["won_saw_flop"] += 1
        if hand.reached_showdown and hero.showed:
            denominator["showdown"] += 1
            counters["went_showdown"] += 1
            if hero_won:
                counters["won_showdown"] += 1

        pre_aggressors = [action.player_id for action in pre if _kind(action) in {"raise", "shove"}]
        hero_pre_aggressor = bool(pre_aggressors and pre_aggressors[-1] == hero.player_id)
        hero_flop_aggression = any(
            action.player_id == hero.player_id and _kind(action) in AGGRESSIVE for action in flop
        )
        if saw_flop and hero_pre_aggressor:
            denominator["cbet_opportunity"] += 1
            if hero_flop_aggression:
                counters["cbet_flop"] += 1

        opponent_pre_aggressor = bool(pre_aggressors and pre_aggressors[-1] != hero.player_id)
        opponent_flop_bet_index = next(
            (
                index
                for index, action in enumerate(flop)
                if action.player_id != hero.player_id and _kind(action) in AGGRESSIVE
            ),
            None,
        )
        if opponent_pre_aggressor and opponent_flop_bet_index is not None:
            denominator["face_cbet"] += 1
            if any(
                action.player_id == hero.player_id and _kind(action) == "fold"
                for action in flop[opponent_flop_bet_index + 1 :]
            ):
                counters["fold_face_cbet"] += 1

        for street_actions in (flop, turn, river):
            hero_checked = False
            for action in street_actions:
                if action.player_id != hero.player_id:
                    continue
                kind = _kind(action)
                if kind == "check":
                    hero_checked = True
                elif kind in {"raise", "shove"} and hero_checked:
                    counters["check_raise"] += 1
                    break

        post = flop + turn + river
        hero_post = [action for action in post if action.player_id == hero.player_id]
        for action in hero_post:
            kind = _kind(action)
            if kind in AGGRESSIVE:
                counters["aggressive_actions"] += 1
            if kind == "call":
                counters["calls_postflop"] += 1
            if kind in AGGRESSIVE | {"call", "check", "fold"}:
                denominator["postflop_actions"] += 1

        if hero_flop_aggression:
            denominator["turn_barrel_opportunity"] += 1
            hero_turn_aggression = any(
                action.player_id == hero.player_id and _kind(action) in AGGRESSIVE for action in turn
            )
            if hero_turn_aggression:
                counters["barrel_turn"] += 1
                denominator["river_barrel_opportunity"] += 1
                if any(
                    action.player_id == hero.player_id and _kind(action) in AGGRESSIVE for action in river
                ):
                    counters["barrel_river"] += 1

        if any(action.player_id == hero.player_id and _kind(action) == "fold" for action in river):
            counters["fold_river"] += 1
        if any(action.player_id == hero.player_id and _kind(action) == "call" for action in river):
            counters["hero_call_river"] += 1
        if river:
            denominator["river_seen"] += 1

        hero_folded = any(
            action.player_id == hero.player_id and _kind(action) == "fold" for action in actions
        )
        if hero_folded:
            denominator["fold_hands"] += 1
            if hero.starting_stack and hero.invested / hero.starting_stack >= 0.25:
                counters["invested_stack_fold"] += 1
        counters["chip_result"] += hero.net or 0
        if (hero.net or 0) < 0:
            counters["losing_hands"] += 1

    hands_count = denominator["hands"]
    metrics = {
        "vpip": _metric(counters["vpip"], hands_count),
        "pfr": _metric(counters["pfr"], hands_count),
        "limp": _metric(counters["limp"], hands_count),
        "limp_fold": _metric(counters["limp_fold"], denominator["limp_response"]),
        "limp_call": _metric(counters["limp_call"], denominator["limp_response"]),
        "limp_raise": _metric(counters["limp_raise"], denominator["limp_response"]),
        "open_raise": _metric(counters["open_raise"], denominator["open_opportunity"]),
        "fold_face_open": _metric(counters["fold_face_open"], denominator["face_open"]),
        "call_face_open": _metric(counters["call_face_open"], denominator["face_open"]),
        "three_bet": _metric(counters["three_bet"], denominator["face_open"]),
        "fold_face_three_bet": _metric(counters["fold_face_three_bet"], denominator["face_three_bet"]),
        "shove": _metric(counters["shove"], hands_count),
        "call_shove": _metric(counters["call_shove"], denominator["face_shove"]),
        "oop_call": _metric(counters["oop_call"], denominator["oop_decisions"]),
        "invested_stack_fold": _metric(counters["invested_stack_fold"], denominator["fold_hands"]),
        "bb_walk": _metric(counters["bb_walk"], denominator["bb_hands"]),
        "cbet_flop": _metric(counters["cbet_flop"], denominator["cbet_opportunity"]),
        "fold_face_cbet": _metric(counters["fold_face_cbet"], denominator["face_cbet"]),
        "check_raise": _metric(counters["check_raise"], denominator["saw_flop"]),
        "aggression_frequency": _metric(counters["aggressive_actions"], denominator["postflop_actions"]),
        "aggression_factor": {
            "value": round(counters["aggressive_actions"] / counters["calls_postflop"], 2)
            if counters["calls_postflop"]
            else None,
            "numerator": counters["aggressive_actions"],
            "denominator": counters["calls_postflop"],
        },
        "went_to_showdown": _metric(counters["went_showdown"], denominator["saw_flop"]),
        "won_at_showdown": _metric(counters["won_showdown"], denominator["showdown"]),
        "won_when_saw_flop": _metric(counters["won_saw_flop"], denominator["saw_flop"]),
        "barrel_turn": _metric(counters["barrel_turn"], denominator["turn_barrel_opportunity"]),
        "barrel_river": _metric(counters["barrel_river"], denominator["river_barrel_opportunity"]),
        "fold_river": _metric(counters["fold_river"], denominator["river_seen"]),
        "hero_call_river": _metric(counters["hero_call_river"], denominator["river_seen"]),
    }
    result: dict[str, Any] = {
        "hands": hands_count,
        "metrics": metrics,
        "chip_result": counters["chip_result"],
        "chip_result_per_hand": round(counters["chip_result"] / hands_count, 2) if hands_count else None,
        "negative_result_rate": round(counters["losing_hands"] / hands_count * 100, 2) if hands_count else None,
    }
    result.update({name: value["value"] for name, value in metrics.items()})

    if include_slices:
        positions: dict[str, list[Hand]] = defaultdict(list)
        depths: dict[str, list[Hand]] = defaultdict(list)
        formats: dict[str, list[Hand]] = defaultdict(list)
        for hand in hands:
            hero = _hero_entry(hand)
            if hero is None:
                continue
            positions[hero.position or "inconnue"].append(hand)
            # In heads-up the button posts the small blind: expose both useful views.
            if hand.active_players == 2 and hand.button_seat == hero.seat:
                positions["BTN"].append(hand)
            opponent_stacks = [
                entry.starting_stack for entry in hand.player_entries if entry.player_id != hero.player_id
            ]
            effective_stack = min(hero.starting_stack, max(opponent_stacks)) if opponent_stacks else hero.starting_stack
            bb = effective_stack / hand.big_blind if hand.big_blind else 0
            if bb <= 5:
                bucket = "0–5 BB"
            elif bb <= 10:
                bucket = "5–10 BB"
            elif bb <= 15:
                bucket = "10–15 BB"
            elif bb <= 25:
                bucket = "15–25 BB"
            else:
                bucket = ">25 BB"
            depths[bucket].append(hand)
            formats["heads-up" if hand.active_players == 2 else "3-handed"].append(hand)
        result["by_position"] = {
            key: calculate_hero_stats(value, include_slices=False) for key, value in positions.items()
        }
        result["by_depth"] = {
            key: calculate_hero_stats(value, include_slices=False) for key, value in depths.items()
        }
        result["by_players"] = {
            key: calculate_hero_stats(value, include_slices=False) for key, value in formats.items()
        }
    return result
