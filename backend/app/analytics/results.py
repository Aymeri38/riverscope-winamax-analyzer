"""Tournament result, dashboard and Expresso grouping formulas."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from .common import as_datetime, boolean, has_value, integer, item_id, number, optional_number, round_money, value


def tournament_buy_in(tournament: Any) -> float:
    direct = value(
        tournament,
        "total_buyin",
        "total_buy_in",
        "buy_in",
        "buyin",
        "entry_fee",
        default=None,
    )
    if direct is not None:
        return number(direct)
    # Parser summaries retain amount and fee separately.
    return number(value(tournament, "buy_in_amount", "buyin_amount", default=0)) + number(
        value(tournament, "fee_amount", default=0)
    )


def tournament_winnings(tournament: Any) -> float:
    return number(value(tournament, "winnings", "reward", "prize_won", "gain", default=0))


def tournament_net(tournament: Any) -> float:
    explicit = optional_number(value(tournament, "net_result", "net", "profit", default=None))
    return explicit if explicit is not None else tournament_winnings(tournament) - tournament_buy_in(tournament)


def tournament_start(tournament: Any) -> datetime | None:
    return as_datetime(value(tournament, "started_at", "start_time", "played_at", "date", "datetime"))


def tournament_duration_seconds(tournament: Any) -> float:
    seconds = optional_number(value(tournament, "duration_seconds", default=None))
    if seconds is not None:
        return max(seconds, 0.0)
    minutes = optional_number(value(tournament, "duration_minutes", "duration", default=None))
    return max((minutes or 0.0) * 60.0, 0.0)


def tournament_is_itm(tournament: Any) -> bool:
    explicit = value(tournament, "is_itm", "itm", default=None)
    if explicit is not None:
        return boolean(explicit)
    # Expresso is usually winner-take-all.  Using an actual positive reward is
    # safer than inferring a payout structure which is absent from the file.
    return tournament_winnings(tournament) > 0 or bool(value(tournament, "ticket", default=None))


def tournament_rank(tournament: Any) -> int | None:
    rank = optional_number(value(tournament, "rank", "final_rank", "final_position", "place", default=None))
    return int(rank) if rank is not None and rank > 0 else None


def tournament_is_complete(tournament: Any) -> bool:
    completion = value(tournament, "is_complete", "completed", "complete", default=None)
    return True if completion is None else boolean(completion)


def max_drawdown(values: Iterable[float]) -> float:
    """Largest peak-to-trough fall of a cumulative result sequence."""

    peak = 0.0
    cumulative = 0.0
    worst = 0.0
    for result in values:
        cumulative += number(result)
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return round_money(worst)


def calculate_roi(tournaments: Iterable[Any]) -> float | None:
    rows = [row for row in tournaments if tournament_is_complete(row)]
    buy_ins = sum(tournament_buy_in(row) for row in rows)
    return round(sum(tournament_net(row) for row in rows) / buy_ins * 100, 2) if buy_ins > 0 else None


def calculate_itm(tournaments: Iterable[Any]) -> float | None:
    rows = [row for row in tournaments if tournament_is_complete(row)]
    return round(sum(tournament_is_itm(row) for row in rows) / len(rows) * 100, 2) if rows else None


def calculate_place_rates(tournaments: Iterable[Any]) -> dict[int, float | None]:
    rows = [row for row in tournaments if tournament_is_complete(row)]
    if not rows:
        return {1: None, 2: None, 3: None}
    return {rank: round(sum(tournament_rank(row) == rank for row in rows) / len(rows) * 100, 2) for rank in (1, 2, 3)}


def calculate_hourly_gain(tournaments: Iterable[Any]) -> float | None:
    rows = [row for row in tournaments if tournament_is_complete(row)]
    duration = sum(tournament_duration_seconds(row) for row in rows)
    return round_money(sum(tournament_net(row) for row in rows) / (duration / 3600)) if duration > 0 else None


def calculate_results_by_stack(hands: Iterable[Any]) -> list[dict[str, Any]]:
    """Group known hero chip results by effective-stack band in big blinds."""

    # Local import keeps the low-level result helpers usable without loading the
    # more detailed action classifier at module import time.
    from .hero_stats import depth_bucket, stack_depth_bb

    groups: dict[str, list[float]] = defaultdict(list)
    for hand in hands:
        depth = stack_depth_bb(hand)
        net_bb = optional_number(value(hand, "hero_net_bb", "net_bb", default=None))
        if net_bb is None:
            net_chips = optional_number(value(hand, "hero_net", "net_chips", "chip_delta", default=None))
            big_blind = optional_number(value(hand, "big_blind", default=None))
            if net_chips is not None and big_blind is not None and big_blind > 0:
                net_bb = net_chips / big_blind
        if depth is not None and net_bb is not None:
            groups[depth_bucket(depth)].append(net_bb)
    order = {label: index for index, label in enumerate(("0-5 BB", "5-10 BB", "10-15 BB", "15-25 BB", "25+ BB", "unknown"))}
    return [
        {
            "stack_depth": label,
            "hands": len(values),
            "total_result_bb": round(sum(values), 2),
            "average_result_bb": round(sum(values) / len(values), 3),
        }
        for label, values in sorted(groups.items(), key=lambda pair: order.get(pair[0], 999))
    ]


def _period_key(moment: datetime | None, period: str) -> str:
    if moment is None:
        return "unknown"
    if period == "day":
        return moment.date().isoformat()
    if period == "week":
        year, week, _ = moment.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return f"{moment.year:04d}-{moment.month:02d}"
    raise ValueError("period must be 'day', 'week' or 'month'")


def group_results(tournaments: Iterable[Any], period: str) -> list[dict[str, Any]]:
    """Aggregate tournament economics by calendar day, ISO week or month."""

    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"games": 0, "buy_ins": 0.0, "winnings": 0.0, "net_result": 0.0}
    )
    for tournament in tournaments:
        if not tournament_is_complete(tournament):
            continue
        key = _period_key(tournament_start(tournament), period)
        bucket = buckets[key]
        bucket["games"] += 1
        bucket["buy_ins"] += tournament_buy_in(tournament)
        bucket["winnings"] += tournament_winnings(tournament)
        bucket["net_result"] += tournament_net(tournament)

    output: list[dict[str, Any]] = []
    for key in sorted(buckets, key=lambda candidate: (candidate == "unknown", candidate)):
        bucket = buckets[key]
        buy_ins = bucket["buy_ins"]
        output.append(
            {
                "period": key,
                "games": int(bucket["games"]),
                "buy_ins": round_money(buy_ins),
                "winnings": round_money(bucket["winnings"]),
                "net_result": round_money(bucket["net_result"]),
                "roi_percent": round(bucket["net_result"] / buy_ins * 100, 2) if buy_ins > 0 else None,
            }
        )
    return output


def calculate_dashboard(tournaments: Iterable[Any], hands: Iterable[Any] | None = None) -> dict[str, Any]:
    """Calculate dashboard figures without fabricating unavailable values.

    ROI = ``sum(net result) / sum(buy-ins) * 100``.
    ITM and place rates use the number of completed tournaments as denominator.
    Hourly gain uses the sum of known tournament durations; it is ``None`` if
    no positive duration was parsed.
    """

    games = [game for game in tournaments if tournament_is_complete(game)]
    games.sort(key=lambda row: (tournament_start(row) is None, tournament_start(row) or datetime.max))
    hands_list = list(hands or [])

    total_buy_ins = sum(tournament_buy_in(game) for game in games)
    total_winnings = sum(tournament_winnings(game) for game in games)
    nets = [tournament_net(game) for game in games]
    net_result = sum(nets)
    total_duration_seconds = sum(tournament_duration_seconds(game) for game in games)
    game_count = len(games)
    parsed_hand_count = sum(
        integer(value(game, "hands_count", "total_hands", "number_of_hands", default=0)) for game in games
    )
    hands_count = len(hands_list) if hands is not None else parsed_hand_count
    rank_counts = {rank: sum(tournament_rank(game) == rank for game in games) for rank in (1, 2, 3)}
    itm_count = sum(tournament_is_itm(game) for game in games)

    cumulative = 0.0
    bankroll_curve = []
    ev_curve = []
    cumulative_ev = 0.0
    for index, game in enumerate(games, start=1):
        cumulative += tournament_net(game)
        moment = tournament_start(game)
        point = {
            "game": index,
            "tournament_id": item_id(game, index),
            "date": moment.isoformat() if moment else None,
            "net_result": round_money(tournament_net(game)),
            "cumulative": round_money(cumulative),
        }
        bankroll_curve.append(point)
        ev = optional_number(value(game, "ev_result", "all_in_ev", "chip_ev", default=None))
        if ev is not None:
            cumulative_ev += ev
            ev_curve.append(
                {
                    "game": index,
                    "tournament_id": item_id(game, index),
                    "date": point["date"],
                    "ev": round(ev, 2),
                    "cumulative_ev": round(cumulative_ev, 2),
                }
            )

    def rate(count: int) -> float | None:
        return round(count / game_count * 100, 2) if game_count else None

    return {
        "games_count": game_count,
        "hands_count": hands_count,
        "total_buy_ins": round_money(total_buy_ins),
        "total_winnings": round_money(total_winnings),
        "net_result": round_money(net_result),
        "roi_percent": round(net_result / total_buy_ins * 100, 2) if total_buy_ins > 0 else None,
        "win_rate_percent": rate(rank_counts[1]),
        "second_place_rate_percent": rate(rank_counts[2]),
        "third_place_rate_percent": rate(rank_counts[3]),
        "itm_percent": rate(itm_count),
        "average_gain_per_game": round_money(net_result / game_count) if game_count else None,
        "hourly_gain": round_money(net_result / (total_duration_seconds / 3600)) if total_duration_seconds else None,
        "average_duration_seconds": round(total_duration_seconds / game_count, 2) if game_count else None,
        "average_hands_per_game": round(hands_count / game_count, 2) if game_count else None,
        "average_buy_in": round_money(total_buy_ins / game_count) if game_count else None,
        "biggest_gain": round_money(max(nets)) if nets else None,
        "biggest_downswing": max_drawdown(nets),
        "bankroll_curve": bankroll_curve,
        # An empty curve explicitly means that no trustworthy EV source exists.
        "ev_curve": ev_curve,
        "ev_available_games": len(ev_curve),
        "results_by_day": group_results(games, "day"),
        "results_by_week": group_results(games, "week"),
        "results_by_month": group_results(games, "month"),
    }


def _group_summary(groups: dict[str, list[Any]]) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(groups, key=lambda raw: (raw == "unknown", optional_number(raw) is None, optional_number(raw) or 0)):
        dashboard = calculate_dashboard(groups[key])
        rows.append(
            {
                "key": key,
                "games_count": dashboard["games_count"],
                "net_result": dashboard["net_result"],
                "roi_percent": dashboard["roi_percent"],
                "itm_percent": dashboard["itm_percent"],
                "win_rate_percent": dashboard["win_rate_percent"],
                "average_gain_per_game": dashboard["average_gain_per_game"],
            }
        )
    return rows


def calculate_expresso_breakdown(tournaments: Iterable[Any]) -> dict[str, Any]:
    """Group key Expresso results by limit and multiplier."""

    games = [game for game in tournaments if tournament_is_complete(game)]
    by_limit: dict[str, list[Any]] = defaultdict(list)
    by_multiplier: dict[str, list[Any]] = defaultdict(list)
    multipliers: list[float] = []
    for game in games:
        buy_in = (
            tournament_buy_in(game)
            if has_value(
                game,
                "total_buyin",
                "total_buy_in",
                "buy_in",
                "buyin",
                "entry_fee",
                "buy_in_amount",
                "buyin_amount",
                "fee_amount",
            )
            else None
        )
        multiplier = optional_number(value(game, "multiplier", default=None))
        by_limit[f"{buy_in:g}" if buy_in is not None else "unknown"].append(game)
        by_multiplier[f"{multiplier:g}" if multiplier is not None else "unknown"].append(game)
        if multiplier is not None:
            multipliers.append(multiplier)

    # In a normal three-player Expresso, rank 1 or 2 confirms that heads-up was
    # reached even when no dedicated flag was persisted.
    hu_games = [
        game
        for game in games
        if boolean(value(game, "reached_heads_up", "played_heads_up", default=False))
        or tournament_rank(game) in {1, 2}
    ]
    three_handed = [
        game
        for game in games
        if integer(value(game, "player_count", "players_count", "registered_players", default=3)) == 3
    ]
    comeback_opportunities = [
        game
        for game in games
        if boolean(value(game, "fell_below_10bb", "was_under_10bb", default=False))
    ]
    comeback_count = sum(
        boolean(value(game, "recovered_above_10bb", "comeback_after_under_10bb", default=False))
        for game in comeback_opportunities
    )
    return {
        "by_limit": _group_summary(by_limit),
        "by_multiplier": _group_summary(by_multiplier),
        "average_multiplier": round(sum(multipliers) / len(multipliers), 2) if multipliers else None,
        "heads_up_win_rate_percent": calculate_dashboard(hu_games)["win_rate_percent"],
        "three_handed_win_rate_percent": calculate_dashboard(three_handed)["win_rate_percent"],
        "first_elimination_rate_percent": (
            round(sum(tournament_rank(game) == 3 for game in three_handed) / len(three_handed) * 100, 2)
            if three_handed
            else None
        ),
        "average_duration_before_elimination_seconds": (
            round(
                sum(tournament_duration_seconds(game) for game in games if tournament_rank(game) not in {None, 1})
                / sum(tournament_rank(game) not in {None, 1} for game in games),
                2,
            )
            if any(tournament_rank(game) not in {None, 1} for game in games)
            else None
        ),
        "comeback_after_under_10bb_percent": (
            round(comeback_count / len(comeback_opportunities) * 100, 2) if comeback_opportunities else None
        ),
        "comeback_observations": len(comeback_opportunities),
    }


def filter_tournaments(
    tournaments: Iterable[Any],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    buy_in: float | None = None,
    multiplier: float | None = None,
    rank: int | None = None,
    player_count: int | None = None,
    positive: bool | None = None,
    session_id: Any | None = None,
) -> list[Any]:
    """Apply dashboard filters with exact numeric matching for stored values."""

    output = []
    for game in tournaments:
        if not tournament_is_complete(game):
            continue
        moment = tournament_start(game)
        if start is not None and (moment is None or moment < start):
            continue
        if end is not None and (moment is None or moment > end):
            continue
        if buy_in is not None and tournament_buy_in(game) != float(buy_in):
            continue
        if multiplier is not None and optional_number(value(game, "multiplier")) != float(multiplier):
            continue
        if rank is not None and tournament_rank(game) != rank:
            continue
        if player_count is not None and integer(
            value(game, "player_count", "players_count", "registered_players")
        ) != player_count:
            continue
        if positive is not None and (tournament_net(game) > 0) is not positive:
            continue
        if session_id is not None and value(game, "session_id") != session_id:
            continue
        output.append(game)
    return output
