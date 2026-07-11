"""chipEV/game calculation with explicit completeness safeguards."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .common import boolean, has_value, integer, item_id, optional_number, value


CHIP_DELTA_FIELDS = (
    "hero_chip_delta",
    "hero_delta",
    "hero_net",
    "chip_delta",
    "net_chips",
    "chips_won_lost",
)


def _explicit_tournament_delta(tournament: Any) -> float | None:
    return optional_number(value(tournament, *CHIP_DELTA_FIELDS, default=None))


def calculate_chip_ev(
    tournaments: Iterable[Any] | None = None,
    hands: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Return mean hero chip delta for tournaments with complete chip data.

    A tournament is usable when it either contains an explicit hero chip delta,
    or every supplied hand for that tournament contains one.  Monetary results,
    finishing position and starting/ending stacks are never substituted: those
    values do not describe decision EV.  Despite the historic ``chipEV`` label,
    this is observed chip result, not all-in-adjusted EV unless upstream data
    explicitly supplies adjusted per-hand deltas.
    """

    tournament_rows = list(tournaments or [])
    hand_rows = list(hands or [])
    grouped_hands: dict[Any, list[Any]] = defaultdict(list)
    for hand in hand_rows:
        tournament_id = value(hand, "tournament_id", "tournament_external_id", default=None)
        if tournament_id is not None:
            grouped_hands[tournament_id].append(hand)

    candidates: list[tuple[Any, Any | None]] = []
    seen_ids: set[Any] = set()
    for index, tournament in enumerate(tournament_rows):
        tournament_id = item_id(tournament, f"row-{index + 1}")
        candidates.append((tournament_id, tournament))
        seen_ids.add(tournament_id)
    for tournament_id in grouped_hands:
        if tournament_id not in seen_ids:
            candidates.append((tournament_id, None))

    per_tournament: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for tournament_id, tournament in candidates:
        if tournament is not None and has_value(tournament, "is_complete", "complete", "completed"):
            if not boolean(value(tournament, "is_complete", "complete", "completed")):
                excluded.append({"tournament_id": tournament_id, "reason": "tournament_incomplete"})
                continue
        explicit = _explicit_tournament_delta(tournament) if tournament is not None else None
        if explicit is not None:
            per_tournament.append({"tournament_id": tournament_id, "chip_delta": round(explicit, 2), "source": "tournament"})
            continue

        tournament_hands = grouped_hands.get(tournament_id, [])
        if not tournament_hands:
            excluded.append({"tournament_id": tournament_id, "reason": "missing_chip_deltas"})
            continue
        if any(
            has_value(hand, "is_complete", "complete", "completed")
            and not boolean(value(hand, "is_complete", "complete", "completed"))
            for hand in tournament_hands
        ):
            excluded.append({"tournament_id": tournament_id, "reason": "hand_data_incomplete"})
            continue
        expected = integer(value(tournament, "hands_count", "total_hands", default=0)) if tournament is not None else 0
        if expected and len(tournament_hands) < expected:
            excluded.append({"tournament_id": tournament_id, "reason": "missing_hands"})
            continue
        deltas = [optional_number(value(hand, *CHIP_DELTA_FIELDS, default=None)) for hand in tournament_hands]
        if any(delta is None for delta in deltas):
            excluded.append({"tournament_id": tournament_id, "reason": "missing_hand_chip_delta"})
            continue
        total = sum(delta for delta in deltas if delta is not None)
        per_tournament.append({"tournament_id": tournament_id, "chip_delta": round(total, 2), "source": "hands"})

    total_delta = sum(row["chip_delta"] for row in per_tournament)
    games_count = len(per_tournament)
    return {
        "available": games_count > 0,
        "chip_ev_per_game": round(total_delta / games_count, 2) if games_count else None,
        "total_chip_delta": round(total_delta, 2) if games_count else None,
        "games_count": games_count,
        "per_tournament": per_tournament,
        "excluded_tournaments": excluded,
        "formula": "sum(hero chip delta per complete tournament) / number of tournaments with complete chip data",
        "note": (
            "Aucune valeur n'est déduite des gains monétaires, du classement ou des cartes inconnues."
            if not games_count
            else "Valeur calculée uniquement à partir des deltas de jetons disponibles."
        ),
    }


calculate_chipev = calculate_chip_ev
