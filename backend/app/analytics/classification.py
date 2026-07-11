"""Conservative hand-review labels that separate process from outcome."""

from __future__ import annotations

from typing import Any, Iterable

from .common import boolean, item_id, optional_number, sequence, value


LABELS = {
    "standard": "standard",
    "review": "à revoir",
    "passive": "potentiellement trop passif",
    "aggressive": "potentiellement trop agressif",
    "sizing": "sizing inhabituel",
    "variance": "décision à forte variance",
    "insufficient": "données insuffisantes",
}


def _financial_result(hand: Any) -> dict[str, Any]:
    result = optional_number(value(hand, "hero_net", "net_result", "hero_chip_delta", "chip_delta", "amount_won_lost"))
    return {
        "known": result is not None,
        "amount": round(result, 2) if result is not None else None,
        "outcome": "win" if result is not None and result > 0 else ("loss" if result is not None and result < 0 else "neutral"),
    }


def classify_hand(hand: Any) -> dict[str, Any]:
    """Assign one review label using only observable line characteristics.

    Losing is intentionally absent from all classification rules.  It is
    reported in ``financial_result`` alongside, but independent from, the
    tentative decision-quality label.
    """

    financial = _financial_result(hand)
    hand_identifier = item_id(hand)
    completion = value(hand, "is_complete", "complete", "completed", default=None)
    if completion is None:
        completion = value(value(hand, "tournament", default=None), "completed", "complete", default=None)
    if boolean(value(hand, "is_active", default=False)) or (completion is not None and not boolean(completion)):
        return {
            "hand_id": hand_identifier,
            "classification": LABELS["insufficient"],
            "code": "insufficient",
            "decision_quality": "not_assessed",
            "reasons": ["La main ou le tournoi n'est pas confirmé comme terminé."],
            "financial_result": financial,
        }

    actions = sequence(value(hand, "actions", "hero_actions", default=[]))
    raw_hole_cards = value(hand, "hero_hole_cards", "hero_cards", "hole_cards", default=[])
    if isinstance(raw_hole_cards, str):
        compact = raw_hole_cards.replace("[", "").replace("]", "").replace(" ", "").replace(",", "")
        # Normalized database summaries store two cards as e.g. ``AsKd``.
        hole_cards = [compact[:2], compact[2:]] if len(compact) == 4 else sequence(raw_hole_cards)
    else:
        hole_cards = sequence(raw_hole_cards)
    if not actions and not any(
        value(hand, flag, default=None) is not None
        for flag in ("missed_aggression_opportunity", "excessive_aggression", "unusual_sizing", "high_variance")
    ):
        return {
            "hand_id": hand_identifier,
            "classification": LABELS["insufficient"],
            "code": "insufficient",
            "decision_quality": "not_assessed",
            "reasons": ["Aucune séquence d'actions exploitable n'est disponible."],
            "financial_result": financial,
        }

    reasons: list[str] = []
    unusual_sizing = boolean(value(hand, "unusual_sizing", default=False))
    for action in actions:
        amount = optional_number(value(action, "amount", "bet_amount", "raise_to", default=None))
        pot_before = optional_number(value(action, "pot_before", "pot_size_before", default=None))
        if amount is not None and pot_before is not None and pot_before > 0 and amount / pot_before > 1.5:
            unusual_sizing = True
            reasons.append(f"Mise de {amount:g} pour un pot de {pot_before:g} (>150 % du pot).")
            break
    action_all_in = any(
        boolean(value(action, "is_all_in", "all_in", default=False))
        or "all-in" in str(value(action, "action_type", "action", default="")).casefold()
        for action in actions
    )
    if unusual_sizing:
        reasons = reasons or ["Un sizing sort de la plage exploratoire configurée ou fournie par le parseur."]
        code = "sizing"
    elif boolean(value(hand, "missed_aggression_opportunity", "passive_line", default=False)):
        code = "passive"
        reasons.append("Le parseur a identifié une opportunité d'agression non utilisée; une revue contextuelle reste nécessaire.")
    elif boolean(value(hand, "excessive_aggression", "aggressive_line", default=False)):
        code = "aggressive"
        reasons.append("La ligne comporte une fréquence ou une taille d'agression inhabituelle à revoir en contexte.")
    elif boolean(value(hand, "is_all_in", "all_in", "high_variance", default=False)) or action_all_in:
        code = "variance"
        reasons.append("La décision engage une forte part du stack; sa variance ne préjuge pas de sa qualité.")
    elif boolean(value(hand, "needs_review", "review", default=False)):
        code = "review"
        reasons.append("La main a été marquée pour revue sans conclusion automatique.")
    elif len(hole_cards) != 2:
        code = "insufficient"
        reasons.append("Les cartes du héros sont incomplètes.")
    else:
        code = "standard"
        reasons.append("Aucun signal exploratoire n'a été déclenché; cela ne prouve pas que la ligne est optimale.")

    return {
        "hand_id": hand_identifier,
        "classification": LABELS[code],
        "code": code,
        "decision_quality": "tentative" if code not in {"standard", "insufficient"} else ("not_assessed" if code == "insufficient" else "no_signal"),
        "reasons": reasons,
        "financial_result": financial,
    }


def classify_hands(hands: Iterable[Any]) -> list[dict[str, Any]]:
    return [classify_hand(hand) for hand in hands]
