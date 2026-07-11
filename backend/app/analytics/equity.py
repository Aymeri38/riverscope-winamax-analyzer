"""Post-session Texas Hold'em equity for fully revealed opponent cards."""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from typing import Any, Iterable


UNKNOWN_OPPONENT_MESSAGE = "Équité non calculable : cartes adverses inconnues."
RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VALUE = {rank: index + 2 for index, rank in enumerate(RANKS)}
DECK = tuple(f"{rank}{suit}" for rank in RANKS for suit in SUITS)

try:  # Optional fast path.  The internal evaluator remains available offline.
    from treys import Card as _TreysCard
    from treys import Evaluator as _TreysEvaluator
except ImportError:  # pragma: no cover - environment dependent
    _TreysCard = None
    _TreysEvaluator = None


def normalize_card(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = f"{raw.get('rank', '')}{raw.get('suit', '')}"
    elif not isinstance(raw, str) and hasattr(raw, "rank") and hasattr(raw, "suit"):
        raw = f"{raw.rank}{raw.suit}"
    text = str(raw or "").strip().strip("[](){}").replace("10", "T")
    text = text.replace("♣", "c").replace("♦", "d").replace("♥", "h").replace("♠", "s")
    if len(text) != 2:
        raise ValueError(f"Invalid poker card: {raw!r}")
    rank = text[0].upper()
    suit = text[1].lower()
    suit = {"t": "c", "c": "c", "k": "d", "d": "d", "h": "h", "p": "s", "s": "s"}.get(suit, suit)
    if rank not in RANKS or suit not in SUITS:
        raise ValueError(f"Invalid poker card: {raw!r}")
    return f"{rank}{suit}"


def _rank_five(cards: Iterable[str]) -> tuple[int, ...]:
    cards_list = list(cards)
    ranks = sorted((RANK_VALUE[card[0]] for card in cards_list), reverse=True)
    suits = [card[1] for card in cards_list]
    counts = Counter(ranks)
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
    straight_high = next(
        (high for high in range(14, 4, -1) if all(rank in unique for rank in range(high, high - 5, -1))),
        None,
    )
    flush = len(set(suits)) == 1
    if flush and straight_high:
        return (8, straight_high)
    if groups[0][0] == 4:
        quad = groups[0][1]
        kicker = max(rank for rank in ranks if rank != quad)
        return (7, quad, kicker)
    triples = sorted((rank for rank, count in counts.items() if count == 3), reverse=True)
    pairs = sorted((rank for rank, count in counts.items() if count >= 2), reverse=True)
    if triples:
        pair_candidates = [rank for rank in pairs if rank != triples[0]] + triples[1:]
        if pair_candidates:
            return (6, triples[0], max(pair_candidates))
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if triples:
        kickers = sorted((rank for rank in ranks if rank != triples[0]), reverse=True)[:2]
        return (3, triples[0], *kickers)
    exact_pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(exact_pairs) >= 2:
        high, low = exact_pairs[:2]
        kicker = max(rank for rank in ranks if rank not in {high, low})
        return (2, high, low, kicker)
    if exact_pairs:
        pair = exact_pairs[0]
        kickers = sorted((rank for rank in ranks if rank != pair), reverse=True)[:3]
        return (1, pair, *kickers)
    return (0, *ranks)


def _internal_rank(cards: list[str]) -> tuple[int, ...]:
    if len(cards) < 5 or len(cards) > 7:
        raise ValueError("A Hold'em hand evaluator needs between five and seven cards")
    return max(_rank_five(combination) for combination in itertools.combinations(cards, 5))


def _ranker() -> tuple[Any, str]:
    if _TreysEvaluator is not None and _TreysCard is not None:
        evaluator = _TreysEvaluator()

        def rank(cards: list[str]) -> int:
            hole = [_TreysCard.new(card) for card in cards[:2]]
            board = [_TreysCard.new(card) for card in cards[2:]]
            # Treys uses a lower-is-better score; negate it for common max logic.
            return -evaluator.evaluate(board, hole)

        return rank, "treys"
    return _internal_rank, "internal"


def _opponents(raw: Any) -> list[list[str]] | None:
    if raw is None:
        return None
    rows = list(raw)
    if not rows or any(card is None or str(card).strip() in {"", "?", "??", "XX", "xx"} for card in rows if not isinstance(card, (list, tuple))):
        return None
    if len(rows) == 2 and all(isinstance(card, (str, dict)) for card in rows):
        rows = [rows]
    normalized: list[list[str]] = []
    for opponent in rows:
        if opponent is None:
            return None
        cards = list(opponent)
        if len(cards) != 2 or any(card is None or str(card).strip() in {"", "?", "??", "XX", "xx"} for card in cards):
            return None
        normalized.append([normalize_card(card) for card in cards])
    return normalized or None


def calculate_equity(
    hero_cards: Iterable[Any],
    opponent_cards: Any,
    board_cards: Iterable[Any] | None = None,
    *,
    final_pot: float | None = None,
    hero_investment: float | None = None,
    pot_before_call: float | None = None,
    amount_to_call: float | None = None,
    actual_result: float | None = None,
    max_exact_runouts: int = 250_000,
    simulations: int = 75_000,
    random_seed: int = 0,
) -> dict[str, Any]:
    """Calculate hero win/tie/loss probability once opponent cards are known.

    Flop, turn and river situations are enumerated exactly.  Very large spaces
    (normally preflop) use deterministic Monte Carlo and report that method.
    For EV, either pass ``final_pot`` and ``hero_investment`` or pass
    ``pot_before_call`` and ``amount_to_call``.  Side pots are intentionally not
    reconstructed.
    """

    opponents = _opponents(opponent_cards)
    if opponents is None:
        return {
            "available": False,
            "message": UNKNOWN_OPPONENT_MESSAGE,
            "win_probability": None,
            "tie_probability": None,
            "loss_probability": None,
            "equity_percent": None,
            "ev_chips": None,
        }

    hero = [normalize_card(card) for card in hero_cards]
    board = [normalize_card(card) for card in (board_cards or [])]
    if len(hero) != 2:
        raise ValueError("Hero must have exactly two cards")
    if len(board) > 5:
        raise ValueError("The board cannot contain more than five cards")
    known = hero + board + [card for opponent in opponents for card in opponent]
    if len(set(known)) != len(known):
        raise ValueError("Duplicate cards make equity calculation impossible")
    missing_board = 5 - len(board)
    remaining = [card for card in DECK if card not in set(known)]
    runout_count = math.comb(len(remaining), missing_board)
    rank, evaluator_name = _ranker()

    if runout_count <= max_exact_runouts:
        runouts: Iterable[tuple[str, ...]] = itertools.combinations(remaining, missing_board)
        method = "exact"
        evaluated = runout_count
    else:
        if simulations <= 0:
            raise ValueError("simulations must be positive for Monte Carlo equity")
        rng = random.Random(random_seed)
        runouts = (tuple(rng.sample(remaining, missing_board)) for _ in range(simulations))
        method = "monte_carlo"
        evaluated = simulations

    wins = ties = losses = 0
    equity_share_sum = 0.0
    for runout in runouts:
        completed_board = board + list(runout)
        hero_rank = rank(hero + completed_board)
        opponent_ranks = [rank(opponent + completed_board) for opponent in opponents]
        best = max([hero_rank, *opponent_ranks])
        if hero_rank < best:
            losses += 1
            continue
        tied_opponents = sum(opponent_rank == hero_rank for opponent_rank in opponent_ranks)
        if tied_opponents:
            ties += 1
            equity_share_sum += 1.0 / (tied_opponents + 1)
        else:
            wins += 1
            equity_share_sum += 1.0

    total = wins + ties + losses
    win_probability = wins / total * 100
    tie_probability = ties / total * 100
    loss_probability = losses / total * 100
    equity_fraction = equity_share_sum / total

    effective_final_pot = final_pot
    effective_investment = hero_investment
    if effective_final_pot is None and pot_before_call is not None and amount_to_call is not None:
        effective_final_pot = float(pot_before_call) + float(amount_to_call)
        effective_investment = float(amount_to_call)
    ev_chips = None
    if effective_final_pot is not None and effective_investment is not None:
        ev_chips = equity_fraction * float(effective_final_pot) - float(effective_investment)

    result = {
        "available": True,
        "message": None,
        "method": method,
        "evaluator": evaluator_name,
        "possible_runouts": runout_count,
        "evaluated_runouts": evaluated,
        "win_probability": round(win_probability, 4),
        "tie_probability": round(tie_probability, 4),
        "loss_probability": round(loss_probability, 4),
        "equity_percent": round(equity_fraction * 100, 4),
        "ev_chips": round(ev_chips, 2) if ev_chips is not None else None,
        "actual_result_chips": round(float(actual_result), 2) if actual_result is not None else None,
        "actual_minus_ev_chips": (
            round(float(actual_result) - ev_chips, 2) if actual_result is not None and ev_chips is not None else None
        ),
        "opponents": len(opponents),
        "note": (
            "Énumération exacte des runouts possibles."
            if method == "exact"
            else "Estimation Monte Carlo déterministe; le nombre de simulations est indiqué."
        ),
    }
    return result


calculate_all_in_equity = calculate_equity
