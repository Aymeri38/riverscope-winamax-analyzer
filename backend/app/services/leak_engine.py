from __future__ import annotations

from typing import Any

from app.schemas.api import AnalyzerSettings


def detect_leaks(
    hero_stats: dict[str, Any],
    dashboard: dict[str, Any],
    settings: AnalyzerSettings,
    hands: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Transparent heuristics, explicitly not presented as GTO truth."""
    metrics = hero_stats.get("metrics", {})
    thresholds = settings.leak_thresholds
    flags: list[dict[str, Any]] = []

    def add_high(
        key: str,
        threshold_key: str,
        name: str,
        explanation: str,
        recommendation: str,
        minimum: int = 12,
    ) -> None:
        metric = metrics.get(key, {})
        value = metric.get("value")
        occurrences = metric.get("numerator", 0)
        sample = metric.get("denominator", 0)
        threshold = thresholds.get(threshold_key)
        if value is None or threshold is None or sample < minimum or value <= threshold:
            return
        flags.append(_flag(name, value, threshold, occurrences, sample, explanation, recommendation))

    def add_low(
        key: str,
        threshold_key: str,
        name: str,
        explanation: str,
        recommendation: str,
        minimum: int = 20,
    ) -> None:
        metric = metrics.get(key, {})
        value = metric.get("value")
        occurrences = metric.get("numerator", 0)
        sample = metric.get("denominator", 0)
        threshold = thresholds.get(threshold_key)
        if value is None or threshold is None or sample < minimum or value >= threshold:
            return
        flags.append(_flag(name, value, threshold, occurrences, sample, explanation, recommendation, low=True))

    add_high(
        "limp_fold",
        "limp_fold_pct",
        "Trop de limp-fold",
        "La fréquence observée de fold après limp dépasse le seuil configuré.",
        "Revoir les mains limpées et la réaction aux relances, en tenant compte des stacks et positions.",
        8,
    )
    add_high(
        "vpip",
        "vpip_pct",
        "VPIP élevé",
        "Le héros investit volontairement préflop plus souvent que le seuil de surveillance.",
        "Comparer les ranges par position et profondeur; le seuil est indicatif, pas une norme GTO.",
    )
    add_high(
        "oop_call",
        "oop_call_pct",
        "Trop de calls hors position",
        "Les calls préflop depuis SB ou BB dépassent le seuil configuré parmi les décisions hors position.",
        "Revoir la défense selon position, sizing et stack effectif; le call n’est pas fautif par nature.",
        15,
    )
    add_low(
        "pfr",
        "pfr_min_pct",
        "PFR faible",
        "La fréquence de relance préflop est sous le seuil configuré.",
        "Examiner les opportunités d’open-raise et distinguer les situations de faible profondeur.",
    )
    vpip = metrics.get("vpip", {}).get("value")
    pfr = metrics.get("pfr", {}).get("value")
    gap_threshold = thresholds.get("vpip_pfr_gap_pct")
    hand_count = hero_stats.get("hands", 0)
    if vpip is not None and pfr is not None and gap_threshold is not None and hand_count >= 20 and vpip - pfr > gap_threshold:
        flags.append(
            _flag(
                "Écart VPIP/PFR important",
                vpip - pfr,
                gap_threshold,
                0,
                hand_count,
                "L’écart suggère beaucoup de calls ou limps par rapport aux relances.",
                "Ventiler par BTN, SB, BB et profondeur avant toute conclusion.",
            )
        )
    add_high(
        "fold_face_open",
        "bb_fold_pct",
        "Trop de folds face à un open",
        "Le fold face à une ouverture dépasse le seuil de contrôle; vérifier spécifiquement la grosse blinde.",
        "Réviser les défenses selon le sizing, la position et le stack effectif.",
    )
    add_high(
        "call_shove",
        "short_call_shove_pct",
        "Calls de shove fréquents",
        "La fréquence de call face à un all-in dépasse le seuil configuré.",
        "Revoir les calls avec leurs cotes, positions et cartes révélées; une perte seule ne prouve aucune erreur.",
        8,
    )
    add_high(
        "invested_stack_fold",
        "invested_fold_pct",
        "Folds après forte portion investie",
        "Une part élevée des folds survient après avoir engagé au moins 25 % du stack de début de main.",
        "Vérifier les séquences et les cotes restantes; investir puis fold peut rester correct selon l’action.",
        8,
    )
    add_high(
        "cbet_flop",
        "cbet_pct",
        "Continuation bet très automatique",
        "La fréquence de c-bet flop dépasse le seuil configuré.",
        "Distinguer textures, nombre de joueurs, avantage de range et profondeur.",
    )
    add_high(
        "fold_face_cbet",
        "fold_to_cbet_pct",
        "Abandon fréquent face aux c-bets",
        "Le fold face à un c-bet dépasse le seuil de surveillance.",
        "Revoir les boards, sizings et équités disponibles plutôt que défendre mécaniquement.",
        10,
    )
    add_low(
        "barrel_turn",
        "turn_aggression_min_pct",
        "Passivité turn",
        "La poursuite de l’agression à la turn est sous le seuil indicatif.",
        "Étudier les turns favorables à la range; ne pas augmenter l’agression sans contexte.",
        10,
    )
    add_high(
        "hero_call_river",
        "river_hero_call_pct",
        "Hero calls river fréquents",
        "La fréquence de call river dépasse le seuil configuré.",
        "Revoir bloqueurs, sizing et distributions adverses uniquement hors session.",
        8,
    )

    by_position = hero_stats.get("by_position", {})
    button = by_position.get("BTN", {})
    button_vpip = button.get("metrics", {}).get("vpip", {})
    button_threshold = thresholds.get("button_vpip_min_pct")
    if (
        button_vpip.get("value") is not None
        and button_threshold is not None
        and button_vpip.get("denominator", 0) >= 20
        and button_vpip["value"] < button_threshold
    ):
        flags.append(
            _flag(
                "Sous-utilisation du bouton",
                button_vpip["value"],
                button_threshold,
                button_vpip.get("numerator", 0),
                button_vpip.get("denominator", 0),
                "Le VPIP du bouton est sous le seuil indicatif configuré.",
                "Étudier séparément 3-handed et heads-up, ainsi que les profondeurs; ne pas élargir mécaniquement.",
                low=True,
            )
        )

    big_blind = by_position.get("BB", {})
    bb_fold = big_blind.get("metrics", {}).get("fold_face_open", {})
    bb_threshold = thresholds.get("bb_fold_pct")
    if (
        bb_fold.get("value") is not None
        and bb_threshold is not None
        and bb_fold.get("denominator", 0) >= 15
        and bb_fold["value"] > bb_threshold
    ):
        flags.append(
            _flag(
                "Trop de folds en grosse blinde",
                bb_fold["value"],
                bb_threshold,
                bb_fold.get("numerator", 0),
                bb_fold.get("denominator", 0),
                "La grosse blinde est abandonnée face aux opens au-delà du seuil configuré.",
                "Revoir les défenses selon position adverse, sizing et stack effectif.",
            )
        )

    short_numerator = short_denominator = 0
    for bucket in ("0–5 BB", "5–10 BB"):
        metric = hero_stats.get("by_depth", {}).get(bucket, {}).get("metrics", {}).get("call_shove", {})
        short_numerator += metric.get("numerator", 0) or 0
        short_denominator += metric.get("denominator", 0) or 0
    short_threshold = thresholds.get("short_call_shove_pct")
    short_value = short_numerator / short_denominator * 100 if short_denominator else None
    if short_value is not None and short_threshold is not None and short_denominator >= 8 and short_value > short_threshold:
        flags.append(
            _flag(
                "Calls de shove fréquents à faible profondeur",
                short_value,
                short_threshold,
                short_numerator,
                short_denominator,
                "Les calls de shove sous 10 BB dépassent le seuil de surveillance.",
                "Revoir chaque spot avec positions, cotes et cartes réellement connues.",
            )
        )

    river_metric = metrics.get("barrel_river", {})
    river_threshold = thresholds.get("river_aggression_min_pct")
    if (
        river_metric.get("value") is not None
        and river_threshold is not None
        and river_metric.get("denominator", 0) >= 10
        and river_metric["value"] < river_threshold
    ):
        flags.append(
            _flag(
                "Passivité river",
                river_metric["value"],
                river_threshold,
                river_metric.get("numerator", 0),
                river_metric.get("denominator", 0),
                "La poursuite de l’agression river est sous le seuil indicatif.",
                "Identifier les runouts favorables et les sizings avant de modifier la fréquence.",
                low=True,
            )
        )

    depth_threshold = thresholds.get("depth_result_min_chips_per_hand")
    if depth_threshold is not None:
        for bucket, segment in hero_stats.get("by_depth", {}).items():
            observed = segment.get("chip_result_per_hand")
            sample = segment.get("hands", 0)
            if observed is not None and sample >= 30 and observed < depth_threshold:
                flags.append(
                    _flag(
                        f"Résultats faibles à {bucket}",
                        observed,
                        depth_threshold,
                        0,
                        sample,
                        "Le résultat moyen en jetons dans cette profondeur est sous le seuil configuré.",
                        "La variance et la sélection des multiplicateurs doivent être séparées de la qualité des décisions.",
                        low=True,
                    )
                )

    expresso = dashboard.get("expresso", {})
    hu = expresso.get("heads_up_win_rate")
    hu_threshold = thresholds.get("heads_up_win_min_pct")
    games = dashboard.get("summary", {}).get("games", 0)
    if hu is not None and hu_threshold is not None and games >= 30 and hu < hu_threshold:
        flags.append(
            _flag(
                "Résultats heads-up faibles",
                hu,
                hu_threshold,
                0,
                games,
                "Le taux de victoire lors des fins de tournoi heads-up est sous le seuil configuré.",
                "Séparer qualité de décision, distribution des multiplicateurs et variance avant de conclure.",
                low=True,
            )
        )
    third = dashboard.get("summary", {}).get("third_place_rate")
    third_threshold = thresholds.get("third_place_pct")
    if third is not None and third_threshold is not None and games >= 30 and third > third_threshold:
        flags.append(
            _flag(
                "Éliminations fréquentes en troisième position",
                third,
                third_threshold,
                int(games * third / 100),
                games,
                "La part de troisièmes places dépasse le seuil configuré.",
                "Analyser les stacks effectifs et les décisions d’élimination, sans attribuer la variance à une faute.",
            )
        )
    if hands:
        for flag in flags:
            flag["hands"] = _affected_hand_ids(flag["name"], hands)
    return sorted(flags, key=lambda item: (item["severity_rank"], item["confidence"]), reverse=True)


def _flag(
    name: str,
    observed: float,
    threshold: float,
    occurrences: int,
    sample: int,
    explanation: str,
    recommendation: str,
    low: bool = False,
) -> dict[str, Any]:
    distance = (threshold - observed) if low else (observed - threshold)
    severity = "élevée" if distance >= 15 else "modérée" if distance >= 7 else "faible"
    confidence = min(0.95, 0.35 + sample / 150)
    return {
        "id": name.casefold().replace(" ", "-"),
        "name": name,
        "severity": severity,
        "severity_rank": {"faible": 1, "modérée": 2, "élevée": 3}[severity],
        "observed": round(observed, 2),
        "threshold": round(threshold, 2),
        "occurrences": occurrences,
        "sample_size": sample,
        "hands": [],
        "explanation": explanation,
        "recommendation": recommendation,
        "confidence": round(confidence, 2),
        "disclaimer": "Heuristique configurable, pas une vérité GTO.",
    }


def _affected_hand_ids(name: str, hands: list[Any]) -> list[int]:
    needle = name.casefold()
    selected: list[int] = []
    for hand in hands:
        hero = next((entry for entry in hand.player_entries if entry.player.is_hero), None)
        if hero is None:
            continue
        actions = sorted(hand.actions, key=lambda action: action.sequence)
        hero_actions = [action for action in actions if action.player_id == hero.player_id]
        pre = [action for action in hero_actions if action.street == "preflop" and not action.action_type.startswith("post_")]
        kinds = [action.action_type for action in pre]
        include = False
        if "limp-fold" in needle:
            include = "call" in kinds and "fold" in kinds
        elif "hors position" in needle:
            include = hero.position in {"SB", "BB"} and "call" in kinds
        elif "vpip" in needle:
            include = any(kind in {"call", "bet", "raise"} for kind in kinds)
        elif "pfr" in needle or "vpip/pfr" in needle:
            include = "call" in kinds and "raise" not in kinds
        elif "bouton" in needle:
            include = hand.button_seat == hero.seat and not any(kind in {"call", "bet", "raise"} for kind in kinds)
        elif "grosse blinde" in needle:
            include = hero.position == "BB" and "fold" in kinds
        elif "shove" in needle:
            opponent_all_in = False
            for action in actions:
                if action.player_id != hero.player_id and action.is_all_in:
                    opponent_all_in = True
                elif opponent_all_in and action.player_id == hero.player_id and action.action_type in {"call", "raise"}:
                    include = True
                    break
            if "faible profondeur" in needle and hand.big_blind:
                opponents = [entry.starting_stack for entry in hand.player_entries if entry.player_id != hero.player_id]
                effective = min(hero.starting_stack, max(opponents)) if opponents else hero.starting_stack
                include = include and effective / hand.big_blind < 10
        elif "forte portion" in needle:
            include = hero.starting_stack > 0 and hero.invested / hero.starting_stack >= 0.25 and any(
                action.action_type == "fold" for action in hero_actions
            )
        elif "continuation" in needle:
            include = any(action.street == "flop" and action.action_type in {"bet", "raise"} for action in hero_actions)
        elif "c-bet" in needle:
            include = any(action.street == "flop" and action.action_type == "fold" for action in hero_actions)
        elif "turn" in needle:
            include = bool(hand.board_text and len(hand.board_text.split()) >= 4) and not any(
                action.street == "turn" and action.action_type in {"bet", "raise"} for action in hero_actions
            )
        elif "river" in needle and "calls" not in needle:
            include = bool(hand.board_text and len(hand.board_text.split()) == 5) and not any(
                action.street == "river" and action.action_type in {"bet", "raise"} for action in hero_actions
            )
        elif "hero calls river" in needle:
            include = any(action.street == "river" and action.action_type == "call" for action in hero_actions)
        elif "heads-up" in needle:
            include = hand.active_players == 2
        elif "troisième" in needle:
            include = hand.tournament.final_rank == 3
        elif "résultats faibles" in needle:
            include = (hero.net or 0) < 0
        if include:
            selected.append(hand.id)
            if len(selected) >= 50:
                break
    return selected
