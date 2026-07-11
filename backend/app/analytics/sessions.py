"""Deterministic grouping of completed tournaments into local sessions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from .common import as_datetime, item_id, round_money, value
from .results import (
    tournament_buy_in,
    tournament_duration_seconds,
    tournament_net,
    tournament_start,
    tournament_is_complete,
    tournament_winnings,
)


def tournament_end(tournament: Any) -> datetime | None:
    explicit = as_datetime(value(tournament, "ended_at", "end_time", "completed_at"))
    if explicit is not None:
        return explicit
    started = tournament_start(tournament)
    if started is None:
        return None
    return started + timedelta(seconds=tournament_duration_seconds(tournament))


def _summarize_session(index: int, tournaments: list[Any]) -> dict[str, Any]:
    starts = [moment for game in tournaments if (moment := tournament_start(game)) is not None]
    ends = [moment for game in tournaments if (moment := tournament_end(game)) is not None]
    started_at = min(starts) if starts else None
    ended_at = max(ends) if ends else (max(starts) if starts else None)
    duration_seconds = (
        max((ended_at - started_at).total_seconds(), 0.0) if started_at is not None and ended_at is not None else None
    )
    buy_ins = sum(tournament_buy_in(game) for game in tournaments)
    winnings = sum(tournament_winnings(game) for game in tournaments)
    net = sum(tournament_net(game) for game in tournaments)

    progression = []
    cumulative = 0.0
    for game in tournaments:
        result = tournament_net(game)
        cumulative += result
        moment = tournament_start(game)
        progression.append(
            {
                "tournament_id": item_id(game),
                "date": moment.isoformat() if moment else None,
                "net_result": round_money(result),
                "cumulative": round_money(cumulative),
            }
        )

    best = max(tournaments, key=tournament_net) if tournaments else None
    worst = min(tournaments, key=tournament_net) if tournaments else None
    return {
        "session_id": f"session-{index:04d}",
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "duration_seconds": round(duration_seconds, 2) if duration_seconds is not None else None,
        "games_count": len(tournaments),
        "buy_ins": round_money(buy_ins),
        "winnings": round_money(winnings),
        "net_result": round_money(net),
        "roi_percent": round(net / buy_ins * 100, 2) if buy_ins > 0 else None,
        "best_game": (
            {"tournament_id": item_id(best), "net_result": round_money(tournament_net(best))} if best is not None else None
        ),
        "worst_game": (
            {"tournament_id": item_id(worst), "net_result": round_money(tournament_net(worst))}
            if worst is not None
            else None
        ),
        "progression": progression,
        "tournament_ids": [item_id(game) for game in tournaments],
    }


def group_sessions(tournaments: Iterable[Any], gap_minutes: float = 30.0) -> list[dict[str, Any]]:
    """Start a new session after a strictly greater inactivity gap.

    The inactivity interval is measured from the previous tournament's end to
    the next one's start.  If an end timestamp is absent, parsed duration is
    used; if both are absent, the start timestamp is the conservative fallback.
    Undated records are isolated because grouping them would invent chronology.
    """

    if gap_minutes < 0:
        raise ValueError("gap_minutes must be non-negative")
    rows = [row for row in tournaments if tournament_is_complete(row)]
    rows.sort(key=lambda game: (tournament_start(game) is None, tournament_start(game) or datetime.max))
    max_gap = timedelta(minutes=gap_minutes)
    groups: list[list[Any]] = []
    current: list[Any] = []
    previous_end: datetime | None = None

    for game in rows:
        started = tournament_start(game)
        # Missing dates cannot safely be associated with another tournament.
        starts_new = bool(current) and (
            started is None or previous_end is None or started - previous_end > max_gap
        )
        if starts_new:
            groups.append(current)
            current = []
        current.append(game)
        ended = tournament_end(game)
        if ended is not None:
            previous_end = max(previous_end, ended) if previous_end is not None and not starts_new else ended
        else:
            previous_end = started
    if current:
        groups.append(current)

    return [_summarize_session(index, group) for index, group in enumerate(groups, start=1)]


# Friendly alias used by API/service callers.
calculate_sessions = group_sessions
