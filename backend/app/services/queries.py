from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Action, Hand, HandPlayer, HeroHoleCard, LeakFlag, Player, Tournament


def money(value: Decimal | float | int | None) -> float:
    return round(float(value or 0), 2)


def tournament_query(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    buyin: float | None = None,
    multiplier: float | None = None,
    rank: int | None = None,
    players: int | None = None,
    result: str | None = None,
) -> Select[tuple[Tournament]]:
    conditions = [Tournament.is_expresso.is_(True), Tournament.completed.is_(True)]
    if start:
        conditions.append(Tournament.started_at >= start)
    if end:
        conditions.append(Tournament.started_at <= end)
    if buyin is not None:
        conditions.append(Tournament.total_buyin == Decimal(str(buyin)))
    if multiplier is not None:
        conditions.append(Tournament.multiplier == multiplier)
    if rank is not None:
        conditions.append(Tournament.final_rank == rank)
    if players is not None:
        conditions.append(Tournament.registered_players == players)
    if result == "positive":
        conditions.append(Tournament.reward > Tournament.total_buyin)
    elif result == "negative":
        conditions.append(Tournament.reward < Tournament.total_buyin)
    return select(Tournament).where(and_(*conditions)).order_by(Tournament.started_at)


def tournament_to_dict(t: Tournament) -> dict[str, Any]:
    net = money(t.reward) - money(t.total_buyin)
    return {
        "id": t.id,
        "tournament_id": t.external_id,
        "external_id": t.external_id,
        "date": t.started_at.isoformat(),
        "started_at": t.started_at.isoformat(),
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "name": t.name,
        "format": "Expresso Nitro" if t.is_nitro else "Expresso",
        "currency": t.currency,
        "buy_in": money(t.total_buyin),
        "buyin": money(t.total_buyin),
        "multiplier": float(t.multiplier) if t.multiplier is not None else None,
        "prize_pool": money(t.prize_pool),
        "rank": t.final_rank,
        "final_rank": t.final_rank,
        "gain": money(t.reward),
        "reward": money(t.reward),
        "net": round(net, 2),
        "duration_seconds": t.duration_seconds,
        "duration": t.duration_seconds,
        "hands": t.total_hands,
        "hand_count": t.total_hands,
        "players": t.registered_players,
        "player_count": t.registered_players,
        "initial_stack": t.initial_stack,
        "final_stack": t.final_stack,
        "chipev": t.chip_delta,
        "chip_ev": t.chip_delta,
        "ticket": t.ticket,
        "ticket_won": t.ticket,
        "tags": _json_list(t.tags_json),
        "notes": t.notes,
        "analysis_status": "analysé" if t.analyzed_at else "importé",
    }


def _json_list(value: str | None) -> list[Any]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


def calculate_dashboard(tournaments: list[Tournament]) -> dict[str, Any]:
    games = len(tournaments)
    buyins = sum(money(t.total_buyin) for t in tournaments)
    winnings = sum(money(t.reward) for t in tournaments)
    net = winnings - buyins
    durations = [t.duration_seconds or 0 for t in tournaments]
    hours = sum(durations) / 3600
    wins = sum(t.final_rank == 1 for t in tournaments)
    seconds = sum(t.final_rank == 2 for t in tournaments)
    thirds = sum(t.final_rank == 3 for t in tournaments)
    itm = sum((t.reward or 0) > 0 for t in tournaments)
    hands = sum(t.total_hands for t in tournaments)

    cumulative = 0.0
    peak = 0.0
    max_downswing = 0.0
    bankroll: list[dict[str, Any]] = []
    for index, tournament in enumerate(sorted(tournaments, key=lambda item: item.started_at), 1):
        cumulative += money(tournament.reward) - money(tournament.total_buyin)
        peak = max(peak, cumulative)
        max_downswing = max(max_downswing, peak - cumulative)
        bankroll.append(
            {
                "index": index,
                "date": tournament.started_at.isoformat(),
                "net": round(cumulative, 2),
                "result": round(money(tournament.reward) - money(tournament.total_buyin), 2),
                "tournament_id": tournament.external_id,
            }
        )

    grouped = {
        "day": _group_results(tournaments, "day"),
        "week": _group_results(tournaments, "week"),
        "month": _group_results(tournaments, "month"),
    }
    by_limit = _group_dimension(tournaments, lambda t: f"{money(t.total_buyin):g} €")
    by_multiplier = _group_dimension(
        tournaments, lambda t: f"x{float(t.multiplier):g}" if t.multiplier is not None else "inconnu"
    )
    chip_values = [t.chip_delta for t in tournaments if t.chip_delta is not None]

    summary = {
        "games": games,
        "tournaments": games,
        "hands": hands,
        "total_buyins": round(buyins, 2),
        "total_winnings": round(winnings, 2),
        "net": round(net, 2),
        "roi": round((net / buyins * 100), 2) if buyins else None,
        "win_rate": round(wins / games * 100, 2) if games else None,
        "second_place_rate": round(seconds / games * 100, 2) if games else None,
        "third_place_rate": round(thirds / games * 100, 2) if games else None,
        "itm": round(itm / games * 100, 2) if games else None,
        "average_gain": round(net / games, 2) if games else None,
        "hourly_gain": round(net / hours, 2) if hours else None,
        "average_duration_seconds": round(sum(durations) / games) if games else None,
        "average_hands": round(hands / games, 2) if games else None,
        "average_buyin": round(buyins / games, 2) if games else None,
        "biggest_win": max((money(t.reward) - money(t.total_buyin) for t in tournaments), default=0),
        "max_downswing": round(max_downswing, 2),
        "chipev_per_game": round(sum(chip_values) / len(chip_values), 2) if chip_values else None,
        "chipev_coverage": round(len(chip_values) / games * 100, 2) if games else 0,
    }

    reached_heads_up = wins + seconds
    expresso = {
        "by_limit": by_limit,
        "by_multiplier": by_multiplier,
        "average_multiplier": round(
            sum(float(t.multiplier) for t in tournaments if t.multiplier is not None)
            / max(1, sum(t.multiplier is not None for t in tournaments)),
            2,
        )
        if tournaments
        else None,
        "heads_up_win_rate": round(wins / reached_heads_up * 100, 2) if reached_heads_up else None,
        "three_handed_win_rate": round(wins / games * 100, 2) if games else None,
        "first_elimination_rate": round(thirds / games * 100, 2) if games else None,
        "average_elimination_seconds": round(
            sum(t.duration_seconds or 0 for t in tournaments if t.final_rank != 1)
            / max(1, sum(t.final_rank != 1 for t in tournaments))
        )
        if tournaments
        else None,
        "comeback_under_10bb_rate": None,
        "comeback_note": "Calculé uniquement si une séquence complète de stacks est disponible.",
    }

    return {
        "summary": summary,
        "bankroll": bankroll,
        "profit_curve": bankroll,
        "ev_curve": [],
        "ev_curve_available": False,
        "ev_note": "Courbe EV non affichée tant que les équités all-in connues ne couvrent pas suffisamment de mains.",
        "grouped_results": grouped,
        "daily": grouped["day"],
        "weekly": grouped["week"],
        "monthly": grouped["month"],
        "expresso": expresso,
        "by_limit": by_limit,
        "by_multiplier": by_multiplier,
    }


def _group_results(tournaments: list[Tournament], period: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[Tournament]] = defaultdict(list)
    for tournament in tournaments:
        when = tournament.started_at
        if period == "month":
            key = when.strftime("%Y-%m")
        elif period == "week":
            year, week, _ = when.isocalendar()
            key = f"{year}-S{week:02d}"
        else:
            key = when.strftime("%Y-%m-%d")
        buckets[key].append(tournament)
    result: list[dict[str, Any]] = []
    for key in sorted(buckets):
        values = buckets[key]
        buyins = sum(money(t.total_buyin) for t in values)
        net = sum(money(t.reward) - money(t.total_buyin) for t in values)
        result.append(
            {
                "period": key,
                "date": key,
                "games": len(values),
                "net": round(net, 2),
                "roi": round(net / buyins * 100, 2) if buyins else None,
            }
        )
    return result


def _group_dimension(tournaments: list[Tournament], key_fn) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    buckets: dict[str, list[Tournament]] = defaultdict(list)
    for tournament in tournaments:
        buckets[key_fn(tournament)].append(tournament)
    output: list[dict[str, Any]] = []
    for label, values in sorted(buckets.items()):
        buyins = sum(money(t.total_buyin) for t in values)
        net = sum(money(t.reward) - money(t.total_buyin) for t in values)
        wins = sum(t.final_rank == 1 for t in values)
        itm = sum(money(t.reward) > 0 for t in values)
        output.append(
            {
                "label": label,
                "games": len(values),
                "net": round(net, 2),
                "roi": round(net / buyins * 100, 2) if buyins else None,
                "itm": round(itm / len(values) * 100, 2),
                "win_rate": round(wins / len(values) * 100, 2),
                "average_gain": round(net / len(values), 2),
            }
        )
    return output


def build_sessions(tournaments: list[Tournament], gap_minutes: int = 30) -> list[dict[str, Any]]:
    ordered = sorted(tournaments, key=lambda item: item.started_at)
    groups: list[list[Tournament]] = []
    for tournament in ordered:
        if not groups:
            groups.append([tournament])
            continue
        previous = groups[-1][-1]
        previous_end = previous.ended_at or (
            previous.started_at + timedelta(seconds=previous.duration_seconds or 0)
        )
        if tournament.started_at - previous_end > timedelta(minutes=gap_minutes):
            groups.append([tournament])
        else:
            groups[-1].append(tournament)

    result: list[dict[str, Any]] = []
    for index, group in enumerate(groups, 1):
        start = group[0].started_at
        last = group[-1]
        end = last.ended_at or last.started_at + timedelta(seconds=last.duration_seconds or 0)
        buyins = sum(money(t.total_buyin) for t in group)
        game_results = [money(t.reward) - money(t.total_buyin) for t in group]
        cumulative = 0.0
        curve: list[dict[str, Any]] = []
        for tournament, value in zip(group, game_results, strict=True):
            cumulative += value
            curve.append({"date": tournament.started_at.isoformat(), "net": round(cumulative, 2)})
        result.append(
            {
                "id": index,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_seconds": max(0, int((end - start).total_seconds())),
                "games": len(group),
                "net": round(sum(game_results), 2),
                "roi": round(sum(game_results) / buyins * 100, 2) if buyins else None,
                "best_game": round(max(game_results), 2),
                "worst_game": round(min(game_results), 2),
                "curve": curve,
            }
        )
    return list(reversed(result))


def hand_to_dict(hand: Hand, hero_player_id: int | None = None) -> dict[str, Any]:
    hero_entry = next((entry for entry in hand.player_entries if entry.player_id == hero_player_id), None)
    if hero_entry is None:
        hero_entry = next((entry for entry in hand.player_entries if entry.player.is_hero), None)
    cards = "".join(f"{card.rank}{card.suit}" for card in sorted(hand.hero_hole_cards, key=lambda c: c.position))
    stack_bb = None
    if hero_entry and hand.big_blind:
        opponent_stacks = [
            entry.starting_stack for entry in hand.player_entries if entry.player_id != hero_entry.player_id
        ]
        effective_stack = min(hero_entry.starting_stack, max(opponent_stacks)) if opponent_stacks else hero_entry.starting_stack
        stack_bb = round(effective_stack / hand.big_blind, 1)
    ordered_actions = sorted(hand.actions, key=lambda action: action.sequence)
    hero_preflop = [
        action.action_type
        for action in ordered_actions
        if hero_entry and action.player_id == hero_entry.player_id and action.street == "preflop"
        and not action.action_type.startswith("post_")
    ]
    hero_postflop = [
        f"{action.street}:{action.action_type}"
        for action in ordered_actions
        if hero_entry and action.player_id == hero_entry.player_id and action.street in {"flop", "turn", "river"}
    ]
    call_shove = False
    if hero_entry:
        opponent_shove_seen = False
        for action in ordered_actions:
            if action.player_id != hero_entry.player_id and action.is_all_in:
                opponent_shove_seen = True
            elif action.player_id == hero_entry.player_id and opponent_shove_seen and action.action_type in {"call", "raise"}:
                call_shove = True
                break
    return {
        "id": hand.id,
        "hand_id": hand.external_id,
        "external_id": hand.external_id,
        "tournament_id": hand.tournament_id,
        "tournament_external_id": hand.tournament.external_id if hand.tournament else None,
        "date": hand.played_at.isoformat(),
        "played_at": hand.played_at.isoformat(),
        "cards": cards,
        "hero_cards": cards,
        "position": hero_entry.position if hero_entry else None,
        "stack_bb": stack_bb,
        "small_blind": hand.small_blind,
        "big_blind": hand.big_blind,
        "players": hand.active_players,
        "pot": hand.total_pot,
        "net": hand.hero_net,
        "all_in": hand.is_all_in,
        "showdown": hand.reached_showdown,
        "board": hand.board_text or "",
        "tags": _json_list(hand.tags_json),
        "notes": hand.notes,
        "leak_detected": bool(hand.leak_flags),
        "classification": hand.analysis.classification if hand.analysis else "données insuffisantes",
        "preflop_action": ", ".join(hero_preflop),
        "postflop_action": ", ".join(hero_postflop),
        "call_shove": call_shove,
        "action_text": hand.action_text or "",
    }
