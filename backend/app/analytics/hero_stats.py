"""Auditable hero statistics derived from normalized hand/action dictionaries.

Every frequency is returned with a numerator and an opportunity denominator.
The module accepts parser objects as well as dictionaries and never looks at a
running poker client.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from .common import boolean, has_value, item_id, metric, number, optional_number, sequence, value


FORCED_ACTIONS = {"ante", "small_blind", "big_blind", "blind", "post", "bring_in"}
AGGRESSIVE_ACTIONS = {"bet", "raise"}


def _text(raw: Any) -> str:
    if hasattr(raw, "value"):
        raw = raw.value
    normalized = unicodedata.normalize("NFKD", str(raw or ""))
    return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).casefold().split())


def _street(action: Any) -> str:
    raw = _text(value(action, "street", "round", default="preflop"))
    if raw in {"pre-flop", "pre flop", "preflop", "predeal", "pre-deal"}:
        return "preflop"
    if "flop" in raw:
        return "flop"
    if "turn" in raw or "tournant" in raw:
        return "turn"
    if "river" in raw or "riviere" in raw:
        return "river"
    return raw


def _kind(action: Any) -> str:
    explicit = _text(value(action, "action_type", "type", "action", "verb", default=""))
    raw = explicit.replace("-", " ").replace("_", " ")
    if any(token in raw for token in ("small blind", "big blind", "ante", "posts", "poste")):
        return "blind"
    if "fold" in raw or "couche" in raw or "passe" == raw:
        return "fold"
    if "check" in raw or "parole" in raw:
        return "check"
    if "call" in raw or "suit" in raw or "complete" in raw:
        return "call"
    if "raise" in raw or "relance" in raw:
        return "raise"
    if "bet" in raw or "mise" in raw:
        return "bet"
    if "all in" in raw or "allin" in raw or "tapis" in raw:
        # A bare all-in is normally aggressive.  Parsers should retain a
        # ``called``/``aggressive`` hint for the exceptional all-in call.
        if boolean(value(action, "is_call", "called", default=False)):
            return "call"
        if has_value(action, "aggressive") and not boolean(value(action, "aggressive")):
            return "call"
        return "raise"
    return explicit


def _actor(action: Any) -> str:
    direct = value(action, "player_name", "actor", "nickname", default=None)
    if direct is not None:
        return _text(direct)
    player = value(action, "player", default=None)
    return _text(value(player, "display_name", "name", "nickname", default=""))


def _is_all_in(action: Any) -> bool:
    return boolean(value(action, "is_all_in", "all_in", default=False)) or any(
        token in _text(value(action, "action_type", "type", "action", "verb", default=""))
        for token in ("all-in", "all in", "allin", "tapis")
    )


def _actions(hand: Any) -> list[Any]:
    raw = value(hand, "actions", "action_history", default=[])
    actions = sequence(raw)
    # Stable sort only when an explicit sequence number exists.
    return [
        action
        for _, action in sorted(
            enumerate(actions),
            key=lambda pair: (
                number(value(pair[1], "sequence", "sequence_no", "order", "index", default=pair[0])),
                pair[0],
            ),
        )
    ]


def _hero_name(hand: Any, supplied: str | None) -> str:
    direct = supplied or value(hand, "hero_name", "hero_player", default=None)
    if direct is None:
        direct = value(value(hand, "tournament", default=None), "hero_name", default="")
    if not isinstance(direct, (str, int, float)):
        direct = value(direct, "display_name", "name", default="")
    return _text(direct)


def _hero_action(action: Any, hero: str, direct_hero_actions: bool = False) -> bool:
    if has_value(action, "is_hero"):
        return boolean(value(action, "is_hero"))
    player = value(action, "player", default=None)
    if player is not None and has_value(player, "is_hero"):
        return boolean(value(player, "is_hero"))
    if direct_hero_actions:
        return True
    actor = _actor(action)
    return bool(hero and actor == hero)


def _explicit_flag(hand: Any, *names: str) -> bool | None:
    if not has_value(hand, *names):
        return None
    return boolean(value(hand, *names))


def _entry_is_hero(entry: Any, hero_name: str) -> bool:
    player = value(entry, "player", default=None)
    if player is not None and has_value(player, "is_hero"):
        return boolean(value(player, "is_hero"))
    candidate = value(player, "display_name", "name", default=value(entry, "name", default=""))
    return bool(hero_name and _text(candidate) == hero_name)


def _position(hand: Any) -> str:
    raw_value = value(hand, "hero_position", "position", default=None)
    hero_name = _hero_name(hand, None)
    button_seat = optional_number(value(hand, "button_seat", default=None))
    for entry in sequence(value(hand, "player_entries", "players", default=[])):
        if _entry_is_hero(entry, hero_name):
            is_button = boolean(value(entry, "is_button", default=False))
            seat = optional_number(value(entry, "seat", default=None))
            if is_button or (button_seat is not None and seat == button_seat):
                raw_value = "BTN"
            elif raw_value is None:
                raw_value = value(entry, "position", default=None)
            break
    raw = _text(raw_value or "")
    if raw in {"button", "dealer", "btn", "bu"}:
        return "BTN"
    if raw in {"small blind", "small_blind", "sb", "petite blind", "petite blinde"}:
        return "SB"
    if raw in {"big blind", "big_blind", "bb", "grosse blind", "grosse blinde"}:
        return "BB"
    return raw.upper() if raw else "UNKNOWN"


def stack_depth_bb(hand: Any) -> float | None:
    explicit = optional_number(value(hand, "effective_stack_bb", default=None))
    if explicit is not None:
        return explicit
    big_blind = optional_number(value(hand, "big_blind", "bb", default=None))
    entries = sequence(value(hand, "player_entries", "players", default=[]))
    hero_name = _hero_name(hand, None)
    hero_chips: float | None = None
    opponent_chips: list[float] = []
    for entry in entries:
        stack = optional_number(value(entry, "starting_stack", default=None))
        if stack is None:
            continue
        if _entry_is_hero(entry, hero_name):
            hero_chips = stack
        else:
            opponent_chips.append(stack)
    if hero_chips is not None:
        # Without a specific heads-up confrontation/side-pot target, use the
        # conservative table-effective stack: the minimum stack among players
        # present at the start of the hand.
        effective_chips = min([hero_chips, *opponent_chips]) if opponent_chips else hero_chips
        return effective_chips / big_blind if big_blind and big_blind > 0 else None

    # Serialized API rows may only retain a hero-stack depth.  It is a useful
    # fallback, but never overrides an actually computable effective stack.
    fallback_bb = optional_number(value(hand, "hero_stack_bb", "stack_bb", default=None))
    if fallback_bb is not None:
        return fallback_bb
    chips = optional_number(value(hand, "effective_stack", "hero_starting_stack", "hero_stack", default=None))
    return chips / big_blind if chips is not None and big_blind and big_blind > 0 else None


def depth_bucket(depth: float | None) -> str:
    if depth is None:
        return "unknown"
    if depth < 5:
        return "0-5 BB"
    if depth < 10:
        return "5-10 BB"
    if depth < 15:
        return "10-15 BB"
    if depth < 25:
        return "15-25 BB"
    return "25+ BB"


def _hand_flags(hand: Any, hero_name: str | None = None) -> dict[str, Any] | None:
    complete = _explicit_flag(hand, "is_complete", "complete", "completed", "tournament_complete")
    if complete is None:
        tournament = value(hand, "tournament", default=None)
        if tournament is not None:
            complete = _explicit_flag(tournament, "completed", "complete")
    if complete is False:
        return None

    hero = _hero_name(hand, hero_name)
    direct = has_value(hand, "hero_actions")
    actions = sequence(value(hand, "hero_actions", default=[])) if direct else _actions(hand)
    preflop = [action for action in actions if _street(action) == "preflop"]
    postflop = [action for action in actions if _street(action) in {"flop", "turn", "river"}]
    hero_pre = [action for action in preflop if _hero_action(action, hero, direct)]
    hero_post = [action for action in postflop if _hero_action(action, hero, direct)]

    # A hand can still contribute from parser-provided booleans even when the
    # action relation has not been eagerly loaded.
    has_explicit_core = any(has_value(hand, key) for key in ("vpip", "pfr", "three_bet", "faced_open_raise"))
    if not actions and not has_explicit_core and not value(
        hand, "hero_hole_cards", "hero_cards", "hole_cards", default=None
    ):
        return None

    raise_count = 0
    voluntary_before = False
    hero_limped = False
    hero_open_raised = False
    hero_pfr = False
    hero_vpip = False
    hero_3bet = False
    hero_shove = False
    faced_open = False
    fold_vs_open = False
    call_vs_open = False
    faced_3bet = False
    fold_vs_3bet = False
    limp_faced_raise = False
    limp_fold = False
    limp_call = False
    limp_raise = False
    faced_shove = False
    call_shove = False
    bb_fold_vs_raise = False
    hero_raised_already = False
    opponent_all_in = False
    first_hero_voluntary_seen = False
    last_raiser = ""

    for action in preflop:
        kind = _kind(action)
        if kind in FORCED_ACTIONS or kind == "blind" or kind not in {"fold", "check", "call", "bet", "raise"}:
            continue
        is_hero = _hero_action(action, hero, direct)
        aggressive = kind in AGGRESSIVE_ACTIONS
        if is_hero:
            hero_shove = hero_shove or (_is_all_in(action) and aggressive)
            if opponent_all_in and kind in {"fold", "call", "raise"}:
                faced_shove = True
                call_shove = call_shove or kind == "call"
            if raise_count == 1 and not hero_raised_already:
                faced_open = True
                fold_vs_open = fold_vs_open or kind == "fold"
                call_vs_open = call_vs_open or kind == "call"
            if hero_open_raised and raise_count == 2:
                faced_3bet = True
                fold_vs_3bet = fold_vs_3bet or kind == "fold"
            if hero_limped and raise_count:
                limp_faced_raise = True
                limp_fold = limp_fold or kind == "fold"
                limp_call = limp_call or kind == "call"
                limp_raise = limp_raise or aggressive
            if kind in {"call", "bet", "raise"}:
                hero_vpip = True
            if aggressive:
                hero_pfr = True
                if raise_count == 1 and last_raiser != hero:
                    hero_3bet = True
                if not voluntary_before:
                    hero_open_raised = True
                hero_raised_already = True
            if not first_hero_voluntary_seen and kind in {"call", "bet", "raise"}:
                hero_limped = kind == "call" and raise_count == 0
                first_hero_voluntary_seen = True
        else:
            if _is_all_in(action):
                opponent_all_in = True
            if aggressive and hero_limped:
                limp_faced_raise = True
            if aggressive and hero_open_raised and raise_count == 1:
                faced_3bet = True
            if kind in {"call", "bet", "raise"}:
                voluntary_before = True
        if aggressive:
            raise_count += 1
            last_raiser = hero if is_hero else _actor(action) or "opponent"

    # Explicit parser flags are authoritative when present.
    def override(current: bool, *names: str) -> bool:
        explicit = _explicit_flag(hand, *names)
        return current if explicit is None else explicit

    hero_vpip = override(hero_vpip, "vpip")
    hero_pfr = override(hero_pfr, "pfr")
    hero_3bet = override(hero_3bet, "three_bet", "threebet", "3bet")
    faced_open = override(faced_open, "faced_open_raise", "faced_open")
    fold_vs_open = override(fold_vs_open, "fold_vs_open")
    call_vs_open = override(call_vs_open, "call_vs_open")
    faced_3bet = override(faced_3bet, "faced_three_bet", "faced_3bet")
    fold_vs_3bet = override(fold_vs_3bet, "fold_vs_three_bet", "fold_vs_3bet")
    hero_limped = override(hero_limped, "limped", "limp")
    limp_faced_raise = override(limp_faced_raise, "limp_faced_raise")
    limp_fold = override(limp_fold, "limp_fold")
    limp_call = override(limp_call, "limp_call")
    limp_raise = override(limp_raise, "limp_raise")
    hero_open_raised = override(hero_open_raised, "open_raise", "open_raised")
    hero_shove = override(hero_shove, "shove", "hero_shove")
    faced_shove = override(faced_shove, "faced_shove")
    call_shove = override(call_shove, "call_shove", "called_shove")

    position = _position(hand)
    preflop_aggressor = _text(value(hand, "preflop_aggressor", default=""))
    hero_preflop_aggressor = override(last_raiser == hero and bool(hero), "hero_preflop_aggressor", "was_preflop_aggressor")
    if preflop_aggressor:
        hero_preflop_aggressor = preflop_aggressor == hero

    board = sequence(value(hand, "board_cards", "board", default=[]))
    hero_folded_preflop = any(_kind(action) == "fold" for action in hero_pre)
    hero_flop_actions = [action for action in hero_post if _street(action) == "flop"]
    hero_turn_actions = [action for action in hero_post if _street(action) == "turn"]
    hero_river_actions = [action for action in hero_post if _street(action) == "river"]
    hero_folded_flop = any(_kind(action) == "fold" for action in hero_flop_actions)
    hero_folded_turn = any(_kind(action) == "fold" for action in hero_turn_actions)
    hero_folded_river = any(_kind(action) == "fold" for action in hero_river_actions)
    saw_flop = override(
        not hero_folded_preflop and (bool(hero_flop_actions) or len(board) >= 3),
        "hero_saw_flop",
        "saw_flop",
    )
    saw_turn = override(
        saw_flop and not hero_folded_flop and (bool(hero_turn_actions) or len(board) >= 4),
        "hero_saw_turn",
        "saw_turn",
    )
    saw_river = override(
        saw_turn and not hero_folded_turn and (bool(hero_river_actions) or len(board) >= 5),
        "hero_saw_river",
        "saw_river",
    )

    streets = {street: [action for action in postflop if _street(action) == street] for street in ("flop", "turn", "river")}
    cbet_opportunity = hero_preflop_aggressor and saw_flop
    cbet = False
    faced_cbet = False
    fold_vs_cbet = False
    check_raise = False
    check_raise_opportunity = False
    turn_barrel_opportunity = False
    turn_barrel = False
    river_barrel_opportunity = False
    river_barrel = False
    faced_river_bet = False
    fold_river = False
    hero_call_river = False
    aggressive_actions = 0
    calls = 0
    folds = 0

    opponent_flop_aggressor = False
    flop_donk_before_hero = False
    for street, street_actions in streets.items():
        hero_checked = False
        hero_acted = False
        opponent_bet_after_check = False
        opponent_aggression_seen = False
        for action in street_actions:
            kind = _kind(action)
            is_hero = _hero_action(action, hero, direct)
            aggressive = kind in AGGRESSIVE_ACTIONS
            if is_hero:
                hero_acted = True
                if aggressive:
                    aggressive_actions += 1
                    if hero_checked and opponent_bet_after_check:
                        check_raise = True
                    if street == "flop" and cbet_opportunity and not opponent_aggression_seen:
                        cbet = True
                    if street == "turn" and not opponent_aggression_seen:
                        turn_barrel = True
                    if street == "river" and not opponent_aggression_seen:
                        river_barrel = True
                elif kind == "call":
                    calls += 1
                    if street == "river" and opponent_aggression_seen:
                        hero_call_river = True
                elif kind == "fold":
                    folds += 1
                    if street == "flop" and opponent_flop_aggressor:
                        fold_vs_cbet = True
                    if street == "river" and opponent_aggression_seen:
                        fold_river = True
                elif kind == "check":
                    hero_checked = True
            elif aggressive:
                opponent_aggression_seen = True
                if street == "flop" and hero_preflop_aggressor and not hero_acted:
                    flop_donk_before_hero = True
                if hero_checked:
                    opponent_bet_after_check = True
                    check_raise_opportunity = True
                if street == "flop" and not hero_preflop_aggressor and _actor(action) == last_raiser:
                    opponent_flop_aggressor = True
                    faced_cbet = True
                if street == "river":
                    faced_river_bet = True

    cbet_opportunity = cbet_opportunity and not flop_donk_before_hero
    cbet_opportunity = override(cbet_opportunity, "cbet_flop_opportunity", "cbet_opportunity")
    cbet = override(cbet, "cbet_flop", "cbet")
    faced_cbet = override(faced_cbet, "faced_cbet_flop", "faced_cbet")
    fold_vs_cbet = override(fold_vs_cbet, "fold_vs_cbet_flop", "fold_vs_cbet")
    check_raise = override(check_raise, "check_raise")
    check_raise_opportunity = override(check_raise_opportunity, "check_raise_opportunity")
    turn_barrel_opportunity = override(cbet and saw_turn, "turn_barrel_opportunity")
    turn_barrel = override(turn_barrel and turn_barrel_opportunity, "turn_barrel")
    river_barrel_opportunity = override(turn_barrel and saw_river, "river_barrel_opportunity")
    river_barrel = override(river_barrel and river_barrel_opportunity, "river_barrel")
    faced_river_bet = override(faced_river_bet, "faced_river_bet")
    fold_river = override(fold_river, "fold_river")
    hero_call_river = override(hero_call_river, "hero_call_river")

    hero_entry_won = False
    hero_showed = False
    for entry in sequence(value(hand, "player_entries", "players", default=[])):
        if _entry_is_hero(entry, hero):
            hero_entry_won = boolean(value(entry, "is_winner", default=False)) or number(value(entry, "won", default=0)) > 0
            hero_showed = boolean(value(entry, "showed", default=False))
            break
    global_showdown = boolean(value(hand, "reached_showdown", "showdown", default=False))
    hero_folded = hero_folded_preflop or hero_folded_flop or hero_folded_turn or hero_folded_river
    showdown = override(
        hero_showed or (global_showdown and saw_river and not hero_folded),
        "hero_went_to_showdown",
        "went_to_showdown",
    )
    won = override(
        boolean(value(hand, "hero_won", "won", default=False))
        or (_text(value(hand, "winner", default="")) == hero and bool(hero))
        or hero_entry_won,
        "hero_won",
        "won",
    )

    opponent_voluntary = any(
        not _hero_action(action, hero, direct) and _kind(action) in {"call", "bet", "raise"} for action in preflop
    )
    bb_walk = position == "BB" and not opponent_voluntary and not hero_vpip
    bb_walk = override(bb_walk, "bb_walk", "walk_big_blind")
    if position == "BB" and faced_open and fold_vs_open:
        bb_fold_vs_raise = True
    bb_fold_vs_raise = override(bb_fold_vs_raise, "bb_fold_vs_raise")

    player_count_for_position = int(
        number(value(hand, "player_count", "players_count", "players_remaining", "active_players", "max_players", default=0))
    )
    explicitly_oop = _explicit_flag(hand, "hero_out_of_position", "out_of_position")
    out_of_position = (
        explicitly_oop
        if explicitly_oop is not None
        else position == "BB" or (position == "SB" and player_count_for_position != 2)
    )
    oop_faced_open = out_of_position and faced_open
    oop_call = override(oop_faced_open and call_vs_open, "oop_call")
    button_vpip = position == "BTN" and hero_vpip
    player_count = player_count_for_position
    return {
        "hand_id": item_id(hand),
        "position": position,
        "player_count": player_count,
        "depth": stack_depth_bb(hand),
        "vpip": hero_vpip,
        "pfr": hero_pfr,
        "three_bet": hero_3bet,
        "faced_open": faced_open,
        "fold_vs_open": fold_vs_open,
        "call_vs_open": call_vs_open,
        "faced_three_bet": faced_3bet,
        "fold_vs_three_bet": fold_vs_3bet,
        "limp": hero_limped,
        "limp_faced_raise": limp_faced_raise,
        "limp_fold": limp_fold,
        "limp_call": limp_call,
        "limp_raise": limp_raise,
        "open_raise": hero_open_raised,
        "shove": hero_shove,
        "faced_shove": faced_shove,
        "call_shove": call_shove,
        "bb_walk": bb_walk,
        "bb_hand": position == "BB",
        "bb_faced_raise": position == "BB" and faced_open,
        "bb_fold_vs_raise": bb_fold_vs_raise,
        "oop_faced_open": oop_faced_open,
        "oop_call": oop_call,
        "button_hand": position == "BTN",
        "button_vpip": button_vpip,
        "saw_flop": saw_flop,
        "saw_turn": saw_turn,
        "saw_river": saw_river,
        "cbet_opportunity": cbet_opportunity,
        "cbet": cbet,
        "faced_cbet": faced_cbet,
        "fold_vs_cbet": fold_vs_cbet,
        "check_raise": check_raise,
        "check_raise_opportunity": check_raise_opportunity,
        "postflop_aggressive_actions": aggressive_actions,
        "postflop_calls": calls,
        "postflop_folds": folds,
        "showdown": showdown,
        "won_showdown": showdown and won,
        "won_saw_flop": saw_flop and won,
        "turn_barrel_opportunity": turn_barrel_opportunity,
        "turn_barrel": turn_barrel,
        "river_barrel_opportunity": river_barrel_opportunity,
        "river_barrel": river_barrel,
        "faced_river_bet": faced_river_bet,
        "fold_river": fold_river,
        "hero_call_river": hero_call_river,
    }


def _summarize(flags: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(flags)

    def frequency(numerator: str, denominator: str | None = None) -> dict[str, Any]:
        eligible = flags if denominator is None else [row for row in flags if row[denominator]]
        return metric(sum(bool(row[numerator]) for row in eligible), len(eligible))

    aggressive = sum(row["postflop_aggressive_actions"] for row in flags)
    calls = sum(row["postflop_calls"] for row in flags)
    folds = sum(row["postflop_folds"] for row in flags)
    af_denominator = calls
    aggression_factor = round(aggressive / af_denominator, 2) if af_denominator else None
    aggression_frequency = metric(aggressive, aggressive + calls + folds)
    output = {
        "hands": count,
        "vpip": frequency("vpip"),
        "pfr": frequency("pfr"),
        "limp": frequency("limp"),
        "limp_fold": frequency("limp_fold", "limp_faced_raise"),
        "limp_call": frequency("limp_call", "limp_faced_raise"),
        "limp_raise": frequency("limp_raise", "limp_faced_raise"),
        "open_raise": frequency("open_raise"),
        "fold_vs_open": frequency("fold_vs_open", "faced_open"),
        "call_vs_open": frequency("call_vs_open", "faced_open"),
        "three_bet": frequency("three_bet", "faced_open"),
        "fold_vs_three_bet": frequency("fold_vs_three_bet", "faced_three_bet"),
        "shove": frequency("shove"),
        "call_shove": frequency("call_shove", "faced_shove"),
        "bb_walk": frequency("bb_walk", "bb_hand"),
        "bb_fold_vs_raise": frequency("bb_fold_vs_raise", "bb_faced_raise"),
        "oop_call": frequency("oop_call", "oop_faced_open"),
        "button_vpip": frequency("button_vpip", "button_hand"),
        "cbet_flop": frequency("cbet", "cbet_opportunity"),
        "fold_vs_cbet": frequency("fold_vs_cbet", "faced_cbet"),
        "check_raise": frequency("check_raise", "check_raise_opportunity"),
        "aggression_frequency": aggression_frequency,
        "aggression_factor": {
            "aggressive_actions": aggressive,
            "calls": calls,
            "value": aggression_factor,
        },
        "went_to_showdown": frequency("showdown", "saw_flop"),
        "won_at_showdown": frequency("won_showdown", "showdown"),
        "won_when_saw_flop": frequency("won_saw_flop", "saw_flop"),
        "turn_barrel": frequency("turn_barrel", "turn_barrel_opportunity"),
        "river_barrel": frequency("river_barrel", "river_barrel_opportunity"),
        "fold_river": frequency("fold_river", "faced_river_bet"),
        "hero_call_river": frequency("hero_call_river", "faced_river_bet"),
    }
    # Convenient scalar aliases for charts while preserving denominators above.
    for name, data in list(output.items()):
        if isinstance(data, dict) and "percentage" in data:
            output[f"{name}_percent"] = data["percentage"]
    return output


def calculate_hero_stats(hands: Iterable[Any], hero_name: str | None = None) -> dict[str, Any]:
    flags = [parsed for hand in hands if (parsed := _hand_flags(hand, hero_name)) is not None]
    return _summarize(flags)


def calculate_segmented_stats(hands: Iterable[Any], hero_name: str | None = None) -> dict[str, Any]:
    """Ventilate the same audited metrics by position, table size and stack."""

    flags = [parsed for hand in hands if (parsed := _hand_flags(hand, hero_name)) is not None]

    def grouped(key_function: Any) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in flags:
            groups[str(key_function(row))].append(row)
        return {key: _summarize(rows) for key, rows in sorted(groups.items())}

    return {
        "overall": _summarize(flags),
        "by_position": grouped(lambda row: row["position"]),
        "by_table_size": grouped(
            lambda row: "heads-up" if row["player_count"] == 2 else ("3-handed" if row["player_count"] == 3 else "unknown")
        ),
        "by_stack_depth": grouped(lambda row: depth_bucket(row["depth"])),
    }


# Common aliases used in poker reporting code.
calculate_player_stats = calculate_hero_stats
hero_statistics = calculate_hero_stats


def calculate_vpip(hands: Iterable[Any], hero_name: str | None = None) -> dict[str, Any]:
    return calculate_hero_stats(hands, hero_name)["vpip"]


def calculate_pfr(hands: Iterable[Any], hero_name: str | None = None) -> dict[str, Any]:
    return calculate_hero_stats(hands, hero_name)["pfr"]


def calculate_three_bet(hands: Iterable[Any], hero_name: str | None = None) -> dict[str, Any]:
    return calculate_hero_stats(hands, hero_name)["three_bet"]
