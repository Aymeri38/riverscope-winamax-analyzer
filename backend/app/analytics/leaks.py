"""Transparent, configurable leak *signals* (never claims of GTO truth)."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Callable, Iterable

from .common import boolean, item_id, number, optional_number, value
from .hero_stats import _hand_flags, depth_bucket
from .results import tournament_rank


DEFAULT_THRESHOLDS: dict[str, Any] = {
    "minimum_observations": 10,
    "high_confidence_observations": 100,
    "medium_confidence_observations": 40,
    "limp_fold_max": 45.0,
    "oop_call_max": 40.0,
    "vpip_max": 50.0,
    "pfr_min": 25.0,
    "vpip_pfr_gap_max": 18.0,
    "button_vpip_min": 45.0,
    "bb_fold_max": 65.0,
    "short_stack_call_shove_max": 45.0,
    "large_investment_fraction": 0.35,
    "large_investment_fold_max": 20.0,
    "cbet_max": 82.0,
    "fold_vs_cbet_max": 68.0,
    "turn_barrel_min": 25.0,
    "river_barrel_min": 20.0,
    "river_hero_call_max": 45.0,
    "depth_average_bb_min": -0.20,
    "heads_up_win_rate_min": 38.0,
    "third_place_rate_max": 42.0,
}


RULE_COPY: dict[str, tuple[str, str]] = {
    "limp_fold": (
        "Trop de limp-fold",
        "Les limps suivis d'un fold semblent fréquents dans cet échantillon.",
    ),
    "oop_call": (
        "Trop de calls hors position",
        "La fréquence de call hors position face à une ouverture dépasse le seuil configuré.",
    ),
    "vpip_high": ("VPIP élevé", "Le héros investit volontairement des jetons dans beaucoup de mains."),
    "pfr_low": ("PFR faible", "Le taux de relance préflop est inférieur au seuil configuré."),
    "vpip_pfr_gap": (
        "Écart VPIP/PFR important",
        "L'écart suggère une part importante de calls ou de limps préflop à examiner.",
    ),
    "button_underuse": ("Sous-utilisation du bouton", "La participation au bouton est basse dans cet échantillon."),
    "bb_overfold": ("Trop de folds en grosse blinde", "La grosse blinde est souvent abandonnée face à une relance."),
    "short_stack_call_shove": (
        "Calls de shove fréquents à faible profondeur",
        "À moins de 10 BB, la fréquence de call face à un shove dépasse le seuil configuré.",
    ),
    "large_investment_fold": (
        "Folds après un investissement important",
        "Des folds surviennent après l'investissement d'une forte portion du stack.",
    ),
    "automatic_cbet": ("Continuation bet très fréquent", "Le c-bet flop est utilisé dans presque toutes les opportunités."),
    "fold_vs_cbet": (
        "Abandon fréquent face aux continuation bets",
        "Le fold face à un c-bet dépasse le seuil configuré.",
    ),
    "late_street_passivity": (
        "Passivité turn ou river",
        "Les barrels sur les rues tardives sont rares dans les opportunités observées.",
    ),
    "river_hero_call": ("Hero calls river fréquents", "La fréquence de call river face à une mise est élevée."),
    "depth_bad_result": (
        "Résultats faibles à une profondeur donnée",
        "Le résultat moyen en blindes est négatif dans cette tranche de profondeur.",
    ),
    "heads_up_bad_result": ("Résultats faibles en heads-up", "Le taux de victoire après avoir atteint le heads-up est bas."),
    "third_place_frequent": (
        "Éliminations fréquentes en troisième position",
        "La fréquence de troisième place dépasse le seuil configuré.",
    ),
}


RECOMMENDATIONS: dict[str, str] = {
    "limp_fold": "Revoir les ranges de limp et les plans préflop face à une relance, par position et profondeur.",
    "oop_call": "Étudier séparément les spots SB/BB et comparer call, 3-bet et fold selon la profondeur.",
    "vpip_high": "Ventiler le VPIP par position et profondeur avant d'ajuster les ranges.",
    "pfr_low": "Identifier les mains jouées passivement qui auraient pu avoir une option de relance.",
    "vpip_pfr_gap": "Revoir les calls et limps préflop en tenant compte de la position et du stack effectif.",
    "button_underuse": "Examiner les opportunités non ouvertes au bouton et les profondeurs concernées.",
    "bb_overfold": "Revoir les défenses de grosse blinde par sizing et profondeur, sans appliquer un seuil universel.",
    "short_stack_call_shove": "Revoir les calls un par un avec ranges et équité uniquement lorsque les cartes sont connues.",
    "large_investment_fold": "Étudier les sizings antérieurs et anticiper les décisions des rues suivantes.",
    "automatic_cbet": "Comparer les textures, le nombre de joueurs et les avantages de range avant de c-bet.",
    "fold_vs_cbet": "Revoir les textures et les options call/raise sans défendre mécaniquement.",
    "late_street_passivity": "Revoir les opportunités de value et de bluff turn/river, main par main.",
    "river_hero_call": "Contrôler les bloqueurs, le sizing et les tendances uniquement sur un échantillon suffisant.",
    "depth_bad_result": "Comparer décisions et résultats séparément dans cette tranche de profondeur.",
    "heads_up_bad_result": "Ventiler par profondeur et position; un résultat court terme ne prouve pas une erreur.",
    "third_place_frequent": "Examiner les éliminations sans déduire la qualité d'une décision de son résultat.",
}


def _metric(stats: dict[str, Any], name: str) -> tuple[float | None, int, int]:
    raw = stats.get(name, {})
    if isinstance(raw, dict):
        percentage = optional_number(raw.get("percentage"))
        numerator = int(number(raw.get("numerator")))
        denominator = int(number(raw.get("denominator")))
        return percentage, numerator, denominator
    percentage = optional_number(raw)
    denominator = int(number(stats.get(f"{name}_opportunities", stats.get("hands", 0))))
    numerator = round((percentage or 0) / 100 * denominator) if percentage is not None else 0
    return percentage, numerator, denominator


def _confidence(observations: int, config: dict[str, Any]) -> str:
    if observations >= int(config["high_confidence_observations"]):
        return "high"
    if observations >= int(config["medium_confidence_observations"]):
        return "medium"
    return "low"


def _severity(observed: float, threshold: float, direction: str) -> str:
    distance = observed - threshold if direction == "max" else threshold - observed
    if distance >= 20:
        return "high"
    if distance >= 8:
        return "medium"
    return "low"


def _concerned_ids(flags: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> list[Any]:
    return [row["hand_id"] for row in flags if row.get("hand_id") is not None and predicate(row)]


def _alert(
    code: str,
    observed: float,
    threshold: float,
    direction: str,
    occurrences: int,
    observations: int,
    config: dict[str, Any],
    hand_ids: list[Any] | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    title, explanation = RULE_COPY[code]
    if detail:
        explanation = f"{explanation} {detail}"
    return {
        "code": code,
        "name": title,
        "severity": _severity(observed, threshold, direction),
        "observed_statistic": round(observed, 2),
        "threshold_used": {"operator": ">" if direction == "max" else "<", "value": threshold},
        "occurrences": occurrences,
        "opportunities": observations,
        "hand_ids": hand_ids or [],
        "explanation": explanation,
        "general_recommendation": RECOMMENDATIONS[code],
        "confidence": _confidence(observations, config),
        "disclaimer": "Seuil configurable d'alerte exploratoire; il ne constitue pas une stratégie GTO absolue.",
    }


def detect_leaks(
    stats: dict[str, Any],
    hands: Iterable[Any] | None = None,
    tournaments: Iterable[Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    hero_name: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate recurring-pattern signals against user-configurable thresholds."""

    config = deepcopy(DEFAULT_THRESHOLDS)
    config.update(thresholds or {})
    minimum = int(config["minimum_observations"])
    hand_rows = list(hands or [])
    flags = [row for hand in hand_rows if (row := _hand_flags(hand, hero_name)) is not None]
    alerts: list[dict[str, Any]] = []

    rules = [
        ("limp_fold", "limp_fold", "limp_fold_max", "max", lambda row: row["limp_fold"]),
        ("oop_call", "oop_call", "oop_call_max", "max", lambda row: row["oop_call"]),
        ("vpip_high", "vpip", "vpip_max", "max", lambda row: row["vpip"]),
        ("pfr_low", "pfr", "pfr_min", "min", lambda row: not row["pfr"]),
        ("button_underuse", "button_vpip", "button_vpip_min", "min", lambda row: row["position"] == "BTN" and not row["vpip"]),
        ("bb_overfold", "bb_fold_vs_raise", "bb_fold_max", "max", lambda row: row["bb_fold_vs_raise"]),
        ("automatic_cbet", "cbet_flop", "cbet_max", "max", lambda row: row["cbet"]),
        ("fold_vs_cbet", "fold_vs_cbet", "fold_vs_cbet_max", "max", lambda row: row["fold_vs_cbet"]),
        ("river_hero_call", "hero_call_river", "river_hero_call_max", "max", lambda row: row["hero_call_river"]),
    ]
    for code, metric_name, threshold_name, direction, predicate in rules:
        observed, occurrences, observations = _metric(stats, metric_name)
        threshold = float(config[threshold_name])
        breached = observed is not None and (observed > threshold if direction == "max" else observed < threshold)
        if breached and observations >= minimum:
            signal_occurrences = occurrences if direction == "max" else observations - occurrences
            alerts.append(
                _alert(
                    code,
                    observed,
                    threshold,
                    direction,
                    signal_occurrences,
                    observations,
                    config,
                    _concerned_ids(flags, predicate),
                )
            )

    vpip, _, vpip_denominator = _metric(stats, "vpip")
    pfr, _, pfr_denominator = _metric(stats, "pfr")
    if vpip is not None and pfr is not None:
        gap = vpip - pfr
        threshold = float(config["vpip_pfr_gap_max"])
        observations = min(vpip_denominator, pfr_denominator)
        if gap > threshold and observations >= minimum:
            alerts.append(
                _alert(
                    "vpip_pfr_gap",
                    gap,
                    threshold,
                    "max",
                    sum(row["vpip"] and not row["pfr"] for row in flags),
                    observations,
                    config,
                    _concerned_ids(flags, lambda row: row["vpip"] and not row["pfr"]),
                    detail=f"VPIP {vpip:.2f}% contre PFR {pfr:.2f}%.",
                )
            )

    short_stack_opportunities = [row for row in flags if row["depth"] is not None and row["depth"] < 10 and row["faced_shove"]]
    if len(short_stack_opportunities) >= minimum:
        calls = [row for row in short_stack_opportunities if row["call_shove"]]
        observed = len(calls) / len(short_stack_opportunities) * 100
        threshold = float(config["short_stack_call_shove_max"])
        if observed > threshold:
            alerts.append(
                _alert(
                    "short_stack_call_shove",
                    observed,
                    threshold,
                    "max",
                    len(calls),
                    len(short_stack_opportunities),
                    config,
                    [row["hand_id"] for row in calls if row["hand_id"] is not None],
                )
            )

    invested_opportunities = []
    invested_folds = []
    fraction_threshold = float(config["large_investment_fraction"])
    for hand in hand_rows:
        fraction = optional_number(value(hand, "invested_stack_fraction", "stack_fraction_invested", default=None))
        explicit = value(hand, "fold_after_large_investment", default=None)
        if fraction is not None and fraction >= fraction_threshold:
            invested_opportunities.append(hand)
            if boolean(explicit) or boolean(value(hand, "hero_folded", default=False)):
                invested_folds.append(hand)
        elif explicit is not None:
            invested_opportunities.append(hand)
            if boolean(explicit):
                invested_folds.append(hand)
    if len(invested_opportunities) >= minimum:
        observed = len(invested_folds) / len(invested_opportunities) * 100
        threshold = float(config["large_investment_fold_max"])
        if observed > threshold:
            alerts.append(
                _alert(
                    "large_investment_fold",
                    observed,
                    threshold,
                    "max",
                    len(invested_folds),
                    len(invested_opportunities),
                    config,
                    [item_id(hand) for hand in invested_folds if item_id(hand) is not None],
                )
            )

    turn, turn_occurrences, turn_denominator = _metric(stats, "turn_barrel")
    river, river_occurrences, river_denominator = _metric(stats, "river_barrel")
    late_candidates = []
    if turn is not None and turn_denominator >= minimum and turn < float(config["turn_barrel_min"]):
        late_candidates.append(("turn", turn, float(config["turn_barrel_min"]), turn_occurrences, turn_denominator))
    if river is not None and river_denominator >= minimum and river < float(config["river_barrel_min"]):
        late_candidates.append(("river", river, float(config["river_barrel_min"]), river_occurrences, river_denominator))
    if late_candidates:
        street, observed, threshold, occurrences, observations = min(late_candidates, key=lambda row: row[1] - row[2])
        alerts.append(
            _alert(
                "late_street_passivity",
                observed,
                threshold,
                "min",
                observations - occurrences,
                observations,
                config,
                _concerned_ids(
                    flags,
                    lambda row: row[f"{street}_barrel_opportunity"] and not row[f"{street}_barrel"],
                ),
                detail=f"Signal principal sur la {street}.",
            )
        )

    # Result-only signals are labelled as such; no losing result is treated as
    # proof that an individual decision was bad.
    by_depth: dict[str, list[tuple[Any, float]]] = defaultdict(list)
    for hand in hand_rows:
        depth = optional_number(value(hand, "effective_stack_bb", "hero_stack_bb", "stack_bb", default=None))
        net_bb = optional_number(value(hand, "hero_net_bb", "net_bb", default=None))
        if depth is not None and net_bb is not None:
            by_depth[depth_bucket(depth)].append((hand, net_bb))
    for bucket, rows in by_depth.items():
        if len(rows) < minimum:
            continue
        observed = sum(net for _, net in rows) / len(rows)
        threshold = float(config["depth_average_bb_min"])
        if observed < threshold:
            alerts.append(
                _alert(
                    "depth_bad_result",
                    observed,
                    threshold,
                    "min",
                    sum(net < 0 for _, net in rows),
                    len(rows),
                    config,
                    [item_id(hand) for hand, net in rows if net < 0 and item_id(hand) is not None],
                    detail=f"Tranche {bucket}; il s'agit d'un signal de résultat, pas d'un jugement de décision.",
                )
            )

    tournament_rows = list(tournaments or [])
    heads_up = [
        game
        for game in tournament_rows
        if boolean(value(game, "reached_heads_up", "played_heads_up", default=False))
        or tournament_rank(game) in {1, 2}
    ]
    if len(heads_up) >= minimum:
        wins = sum(tournament_rank(game) == 1 for game in heads_up)
        observed = wins / len(heads_up) * 100
        threshold = float(config["heads_up_win_rate_min"])
        if observed < threshold:
            alerts.append(
                _alert(
                    "heads_up_bad_result",
                    observed,
                    threshold,
                    "min",
                    len(heads_up) - wins,
                    len(heads_up),
                    config,
                    detail="Signal fondé sur le classement, donc sensible à la variance.",
                )
            )
    three_player = [game for game in tournament_rows if int(number(value(game, "player_count", default=3))) == 3]
    if len(three_player) >= minimum:
        thirds = sum(tournament_rank(game) == 3 for game in three_player)
        observed = thirds / len(three_player) * 100
        threshold = float(config["third_place_rate_max"])
        if observed > threshold:
            alerts.append(
                _alert(
                    "third_place_frequent",
                    observed,
                    threshold,
                    "max",
                    thirds,
                    len(three_player),
                    config,
                    detail="Signal fondé sur le classement, donc sensible à la variance.",
                )
            )

    return alerts


find_leaks = detect_leaks
