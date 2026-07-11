from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.core.process_guard import AnalysisInterlock, analysis_interlock
from app.models import Action, Hand, ImportError, ImportFile, Tournament
from app.schemas.contribution import ContributionPreviewResponse


PRIVACY_SCHEMA_VERSION = "1"
CONTRIBUTION_FILENAME = "winamax-analyzer-contribution.json"

COUNT_BUCKETS = (
    (0, 0, "0"),
    (1, 4, "1-4"),
    (5, 9, "5-9"),
    (10, 24, "10-24"),
    (25, 49, "25-49"),
    (50, 99, "50-99"),
    (100, 249, "100-249"),
    (250, 499, "250-499"),
    (500, 999, "500-999"),
)

ALLOWED_STREETS = frozenset({"preflop", "flop", "turn", "river", "showdown"})
ALLOWED_ACTION_TYPES = frozenset(
    {
        "post_small_blind",
        "post_big_blind",
        "post_ante",
        "fold",
        "check",
        "call",
        "bet",
        "raise",
        "show",
        "muck",
        "collect",
        "uncalled_return",
    }
)
ALLOWED_ERROR_CODES = frozenset(
    {
        "unknown_document_line",
        "no_hands",
        "duplicate_hand",
        "invalid_buy_in",
        "invalid_player_count",
        "invalid_prize_pool",
        "invalid_start_date",
        "invalid_duration",
        "invalid_final_rank",
        "unknown_summary_line",
        "missing_summary_header",
        "missing_final_rank",
        "malformed_header",
        "dealt_unknown_player",
        "unknown_hand_line",
        "missing_hand_summary",
        "missing_total_pot",
        "invalid_hand_date",
    }
)

REDACTIONS = [
    "Tous les volumes sont remplacés par des tranches fixes.",
    "Les pourcentages sont arrondis au multiple de 5 points le plus proche.",
    "Toute rue, action ou erreur hors liste blanche est fusionnée dans 'other'.",
]
EXCLUSIONS = [
    "Pseudos du héros et des adversaires.",
    "Chemins, noms de fichiers et identifiants externes ou internes.",
    "Empreintes de fichiers ou de lignes et identifiants d'installation.",
    "Dates et heures exactes.",
    "Cartes, boards, textes de mains et lignes de diagnostic.",
    "Notes, tags, tickets et autres textes libres.",
    "Montants, mises, gains, stacks et numéros de séquence.",
]
WARNINGS = [
    "Cet aperçu est généré localement et aucune donnée n'est envoyée vers un service externe.",
    "Les statistiques agrégées peuvent rester sensibles; inspectez le payload avant de le partager.",
    "La contribution ne contient pas de fixture textuelle et ne suffit pas à reproduire une nouvelle variante de format.",
]


def count_bucket(value: int) -> str:
    """Return the only count representation permitted in a contribution."""
    safe_value = max(0, int(value))
    for minimum, maximum, label in COUNT_BUCKETS:
        if minimum <= safe_value <= maximum:
            return label
    return "1000+"


def rounded_percentage(part: int, total: int) -> int:
    if total <= 0:
        return 0
    raw = (part / total) * 100
    return min(100, max(0, math.floor((raw / 5) + 0.5) * 5))


def _category_rows(counts: Counter[str], total: int) -> list[dict[str, Any]]:
    return [
        {
            "category": category,
            "count_bucket": count_bucket(count),
            "percentage": rounded_percentage(count, total),
        }
        for category, count in sorted(counts.items())
    ]


def _field_coverage(
    fields: tuple[str, ...],
    rows: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    total = len(rows)
    return [
        {
            "field": field,
            "present_bucket": count_bucket(sum(bool(row[index]) for row in rows)),
            "percentage": rounded_percentage(sum(bool(row[index]) for row in rows), total),
        }
        for index, field in enumerate(fields)
    ]


def _characteristic_frequencies(
    characteristics: tuple[str, ...],
    rows: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    total = len(rows)
    return [
        {
            "characteristic": characteristic,
            "count_bucket": count_bucket(sum(bool(row[index]) for row in rows)),
            "percentage": rounded_percentage(sum(bool(row[index]) for row in rows), total),
        }
        for index, characteristic in enumerate(characteristics)
    ]


def build_contribution_payload(db: Session) -> dict[str, Any]:
    """Build an allowlisted aggregate payload from completed tournaments only.

    ORM entities are never serialized. Every selected value is either a boolean,
    a fixed categorical value, or an internal count immediately transformed into
    a published bucket/percentage.
    """
    tournament_rows = list(
        db.execute(
            select(
                Tournament.is_expresso,
                Tournament.is_nitro,
                Tournament.registered_players,
                Tournament.final_rank.is_not(None),
                Tournament.duration_seconds.is_not(None),
                Tournament.multiplier.is_not(None),
                Tournament.chip_delta.is_not(None),
            ).where(Tournament.completed.is_(True))
        ).all()
    )
    tournament_total = len(tournament_rows)

    tournament_formats: Counter[str] = Counter()
    tournament_players: Counter[str] = Counter()
    for is_expresso, is_nitro, players, *_coverage in tournament_rows:
        if bool(is_expresso) and bool(is_nitro):
            tournament_formats["expresso_nitro"] += 1
        elif bool(is_expresso):
            tournament_formats["expresso"] += 1
        else:
            tournament_formats["other"] += 1
        tournament_players[str(players) if players in {2, 3} else "other"] += 1

    tournament_coverage_rows = [tuple(row[3:]) for row in tournament_rows]
    tournament_coverage = _field_coverage(
        ("final_rank", "duration", "multiplier", "chip_delta"),
        tournament_coverage_rows,
    )

    hand_rows = list(
        db.execute(
            select(
                Hand.active_players,
                Hand.is_all_in,
                Hand.reached_showdown,
                Hand.total_pot.is_not(None),
                Hand.hero_net.is_not(None),
            )
            .select_from(Hand)
            .join(Tournament, Hand.tournament_id == Tournament.id)
            .where(Tournament.completed.is_(True))
        ).all()
    )
    hand_total = len(hand_rows)
    hand_players: Counter[str] = Counter(
        str(row[0]) if row[0] in {2, 3} else "other" for row in hand_rows
    )
    hand_characteristics = _characteristic_frequencies(
        ("all_in", "showdown", "pot_present", "hero_result_present"),
        [tuple(row[1:]) for row in hand_rows],
    )

    raw_action_rows = db.execute(
        select(Action.street, Action.action_type)
        .select_from(Action)
        .join(Hand, Action.hand_id == Hand.id)
        .join(Tournament, Hand.tournament_id == Tournament.id)
        .where(Tournament.completed.is_(True))
    ).all()
    action_counts: Counter[tuple[str, str]] = Counter()
    for raw_street, raw_type in raw_action_rows:
        street = raw_street if raw_street in ALLOWED_STREETS else "other"
        action_type = raw_type if raw_type in ALLOWED_ACTION_TYPES else "other"
        action_counts[(street, action_type)] += 1
    action_total = sum(action_counts.values())
    actions = [
        {
            "street": street,
            "type": action_type,
            "count_bucket": count_bucket(count),
            "percentage": rounded_percentage(count, action_total),
        }
        for (street, action_type), count in sorted(action_counts.items())
    ]

    raw_diagnostics = db.execute(
        select(ImportError.error_code)
        .select_from(ImportError)
        .join(ImportFile, ImportError.import_file_id == ImportFile.id)
        .join(Tournament, ImportFile.tournament_id == Tournament.id)
        .where(Tournament.completed.is_(True))
    ).scalars()
    diagnostic_counts: Counter[str] = Counter(
        code if code in ALLOWED_ERROR_CODES else "other" for code in raw_diagnostics
    )
    diagnostic_total = sum(diagnostic_counts.values())
    diagnostics = [
        {
            "error_code": code,
            "count_bucket": count_bucket(count),
            "percentage": rounded_percentage(count, diagnostic_total),
        }
        for code, count in sorted(diagnostic_counts.items())
    ]

    return {
        "privacy_schema_version": PRIVACY_SCHEMA_VERSION,
        "app_version": __version__,
        "scope": {
            "completed_tournaments": count_bucket(tournament_total),
            "hands": count_bucket(hand_total),
            "actions": count_bucket(action_total),
            "parser_diagnostics": count_bucket(diagnostic_total),
        },
        "tournaments": {
            "formats": _category_rows(tournament_formats, tournament_total),
            "player_counts": _category_rows(tournament_players, tournament_total),
            "field_coverage": tournament_coverage,
        },
        "hands": {
            "player_counts": _category_rows(hand_players, hand_total),
            "characteristics": hand_characteristics,
        },
        "actions": actions,
        "parser_diagnostics": diagnostics,
    }


def build_contribution_preview(
    db: Session,
    *,
    interlock: AnalysisInterlock | None = None,
) -> ContributionPreviewResponse:
    """Return the exact canonical bytes a user may later choose to share."""
    guard = interlock or analysis_interlock
    guard.ensure_allowed()
    data = build_contribution_payload(db)
    guard.ensure_allowed()

    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    payload_bytes = payload.encode("utf-8")
    return ContributionPreviewResponse(
        filename=CONTRIBUTION_FILENAME,
        media_type="application/json",
        encoding="utf-8",
        payload=payload,
        byte_size=len(payload_bytes),
        sha256=hashlib.sha256(payload_bytes).hexdigest(),
        network_sent=False,
        redactions=REDACTIONS,
        exclusions=EXCLUSIONS,
        warnings=WARNINGS,
    )
