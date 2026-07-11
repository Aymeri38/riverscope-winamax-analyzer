from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.process_guard import AnalysisForbiddenError, analysis_interlock
from app.core.privacy import stable_name_key
from app.models import (
    Action,
    AnalysisResult,
    BoardCard,
    Hand,
    HandPlayer,
    HeroHoleCard,
    ImportError,
    ImportFile,
    Player,
    Tournament,
    TournamentPlayer,
)
from app.parsers import (
    HandHistoryParseResult,
    ParseIssue,
    ParsedHand,
    TournamentSummary,
    is_complete,
    parse_hand_history,
    parse_tournament_summary,
)
from app.schemas.api import AnalyzerSettings


@dataclass(slots=True)
class ImportOutcome:
    scanned: int = 0
    imported: int = 0
    waiting: int = 0
    failed: int = 0
    skipped: int = 0

    def to_dict(self) -> dict[str, int | str]:
        return {
            "scanned": self.scanned,
            "imported": self.imported,
            "waiting": self.waiting,
            "failed": self.failed,
            "skipped": self.skipped,
            "message": "Rescannage post-session terminé.",
        }


def _ensure_analysis_allowed(db: Session | None = None) -> None:
    """Fail closed and discard the current unit of work when the safety latch trips."""
    try:
        analysis_interlock.ensure_allowed()
    except AnalysisForbiddenError:
        if db is not None:
            db.rollback()
        raise


def _commit_if_allowed(db: Session) -> None:
    """Keep the process guard as the final gate before every import commit."""
    _ensure_analysis_allowed(db)
    db.commit()


def rescan_all(db: Session, settings: AnalyzerSettings, now: datetime | None = None) -> ImportOutcome:
    _ensure_analysis_allowed(db)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    outcome = ImportOutcome()
    seen_paths: set[Path] = set()

    for configured in settings.history_paths:
        _ensure_analysis_allowed(db)
        root = Path(configured)
        if not root.is_dir():
            continue
        hand_files = sorted(
            path
            for path in root.glob("*Expresso*.txt")
            if not path.name.casefold().endswith("_summary.txt")
        )
        for hand_path in hand_files:
            _ensure_analysis_allowed(db)
            resolved = hand_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            outcome.scanned += 1
            summary_path = hand_path.with_name(f"{hand_path.stem}_summary.txt")
            if summary_path.is_file():
                outcome.scanned += 1
                seen_paths.add(summary_path.resolve())
                result = import_pair(db, hand_path, summary_path, settings, reference)
                setattr(outcome, result, getattr(outcome, result) + 1)
            else:
                row = _upsert_file(db, hand_path, "hand_history")
                _update_metadata(row, hand_path)
                row.state = "waiting_for_completion"
                row.error_message = "Résumé final absent; import différé."
                outcome.waiting += 1
                _commit_if_allowed(db)
    return outcome


def import_pair(
    db: Session,
    hand_path: Path,
    summary_path: Path,
    settings: AnalyzerSettings,
    now: datetime | None = None,
) -> str:
    _ensure_analysis_allowed(db)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    hand_file = _upsert_file(db, hand_path, "hand_history")
    summary_file = _upsert_file(db, summary_path, "tournament_summary")
    try:
        hand_stat = hand_path.stat()
        summary_stat = summary_path.stat()
        _update_metadata(hand_file, hand_path, hand_stat)
        _update_metadata(summary_file, summary_path, summary_stat)
    except OSError as exc:
        _mark_failed((hand_file, summary_file), f"Fichier inaccessible: {type(exc).__name__}")
        _commit_if_allowed(db)
        return "failed"

    stable_seconds = max(10, settings.stable_delay_seconds)
    if any(reference.timestamp() - stat.st_mtime < stable_seconds for stat in (hand_stat, summary_stat)):
        _mark_waiting((hand_file, summary_file), "Taille/date pas encore stables pendant le délai requis.")
        _commit_if_allowed(db)
        return "waiting"

    try:
        history = parse_hand_history(hand_path, hero_name=settings.hero_name or None)
        summary = parse_tournament_summary(summary_path)
    except Exception as exc:
        _mark_failed((hand_file, summary_file), f"Erreur de lecture/parsing: {type(exc).__name__}")
        _commit_if_allowed(db)
        return "failed"
    _ensure_analysis_allowed(db)

    hand_file.file_hash = history.source_hash
    summary_file.file_hash = summary.source_hash
    if not summary.is_expresso:
        _mark_failed((hand_file, summary_file), "Le résumé n’est pas un tournoi Expresso.")
        _commit_if_allowed(db)
        return "failed"
    if not is_complete(
        history,
        summary,
        now=reference,
        quiet_period_seconds=max(60, settings.active_grace_seconds),
    ):
        _mark_waiting(
            (hand_file, summary_file),
            "Tournoi incomplet, classement absent ou dernière main trop récente.",
        )
        _store_issues(db, hand_file, history.issues)
        _store_issues(db, summary_file, summary.issues)
        _commit_if_allowed(db)
        return "waiting"

    if not summary.tournament_id or not summary.started_at or not summary.hero_name:
        _mark_failed((hand_file, summary_file), "Identifiant, date ou héros absent du résumé final.")
        _store_issues(db, hand_file, history.issues)
        _store_issues(db, summary_file, summary.issues)
        _commit_if_allowed(db)
        return "failed"

    existing = db.scalar(select(Tournament).where(Tournament.external_id == summary.tournament_id))
    if existing is not None:
        _mark_imported((hand_file, summary_file), existing.id)
        _commit_if_allowed(db)
        return "skipped"

    try:
        tournament = _persist_tournament(db, history, summary, hand_path)
        db.flush()
        _store_issues(db, hand_file, history.issues)
        _store_issues(db, summary_file, summary.issues)
        _mark_imported((hand_file, summary_file), tournament.id)
        _commit_if_allowed(db)
        return "imported"
    except AnalysisForbiddenError:
        db.rollback()
        raise
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        db.rollback()
        _ensure_analysis_allowed(db)
        # Re-acquire rows because rollback expires previous state.
        hand_file = _upsert_file(db, hand_path, "hand_history")
        summary_file = _upsert_file(db, summary_path, "tournament_summary")
        _mark_failed((hand_file, summary_file), f"Import transactionnel annulé: {type(exc).__name__}")
        _commit_if_allowed(db)
        return "failed"


def _persist_tournament(
    db: Session,
    history: HandHistoryParseResult,
    summary: TournamentSummary,
    source_path: Path,
) -> Tournament:
    hero_name = summary.hero_name or next((hand.hero_name for hand in history.hands if hand.hero_name), None)
    if not hero_name or not summary.tournament_id or not summary.started_at:
        raise ValueError("Missing mandatory completed tournament fields")

    hero_nets = [hand.hero_net for hand in history.hands if hand.hero_net is not None]
    chip_delta = int(sum(hero_nets, Decimal("0"))) if hero_nets else None
    first_hero = next((hand.hero for hand in history.hands if hand.hero), None)
    initial_stack = int(first_hero.starting_stack) if first_hero else None
    final_stack = initial_stack + chip_delta if initial_stack is not None and chip_delta is not None else None
    started_at = _naive_utc(summary.started_at)
    ended_at = started_at + timedelta(seconds=summary.duration_seconds) if summary.duration_seconds is not None else None

    tournament = Tournament(
        external_id=summary.tournament_id,
        name=summary.name or "Expresso",
        started_at=started_at,
        ended_at=ended_at,
        is_expresso=True,
        is_nitro=summary.is_nitro,
        currency=summary.currency or "EUR",
        buyin_amount=summary.buy_in_amount or Decimal("0"),
        fee_amount=summary.fee_amount or Decimal("0"),
        total_buyin=summary.total_buy_in or Decimal("0"),
        multiplier=summary.multiplier,
        prize_pool=summary.prize_pool or Decimal("0"),
        reward=summary.reward or Decimal("0"),
        ticket=summary.ticket,
        final_rank=summary.final_rank,
        duration_seconds=summary.duration_seconds,
        total_hands=len(history.hands),
        registered_players=summary.registered_players or 3,
        hero_name=hero_name,
        initial_stack=initial_stack,
        final_stack=final_stack,
        chip_delta=chip_delta,
        source_path=str(source_path.resolve()),
        completed=True,
        analyzed_at=_utcnow_naive(),
    )
    db.add(tournament)
    db.flush()

    all_names: list[str] = []
    for hand in history.hands:
        for player in hand.players:
            if player.name not in all_names:
                all_names.append(player.name)
    players: dict[str, Player] = {}
    aliases: dict[str, str] = {}
    villain_number = 1
    for name in all_names:
        is_hero = name.casefold() == hero_name.casefold()
        player = _get_or_create_player(db, name, is_hero)
        players[name] = player
        alias = "HERO" if is_hero else f"VILLAIN_{villain_number}"
        if not is_hero:
            villain_number += 1
        aliases[name] = alias
        appearances = [
            parsed_player
            for hand in history.hands
            for parsed_player in hand.players
            if parsed_player.name == name
        ]
        first = appearances[0] if appearances else None
        last = appearances[-1] if appearances else None
        db.add(
            TournamentPlayer(
                tournament_id=tournament.id,
                player_id=player.id,
                final_rank=summary.final_rank if is_hero else None,
                reward=summary.reward or Decimal("0") if is_hero else Decimal("0"),
                starting_stack=int(first.starting_stack) if first else None,
                final_stack=(initial_stack + chip_delta) if is_hero and initial_stack is not None and chip_delta is not None else (
                    int(last.ending_stack) if last and last.ending_stack is not None else None
                ),
                display_alias=alias,
            )
        )

    for index, parsed_hand in enumerate(history.hands, 1):
        _persist_hand(db, tournament, parsed_hand, players, aliases, index)
    return tournament


def _persist_hand(
    db: Session,
    tournament: Tournament,
    parsed: ParsedHand,
    players: dict[str, Player],
    aliases: dict[str, str],
    fallback_number: int,
) -> Hand:
    if parsed.played_at is None:
        raise ValueError("Completed hand without timestamp")
    hero_net = int(parsed.hero_net) if parsed.hero_net is not None else None
    action_text = " | ".join(
        " ".join(
            part
            for part in (
                action.street,
                aliases.get(action.actor, "PLAYER"),
                action.action_type,
                str(int(action.amount)) if action.amount is not None else "",
            )
            if part
        )
        for action in parsed.actions
    )
    hand = Hand(
        external_id=parsed.external_id,
        tournament_id=tournament.id,
        hand_number=parsed.hand_number or fallback_number,
        played_at=_naive_utc(parsed.played_at),
        level=parsed.level,
        small_blind=int(parsed.small_blind or 0),
        big_blind=int(parsed.big_blind or 0),
        ante=int(parsed.ante or 0),
        button_seat=parsed.button_seat,
        max_players=parsed.max_players or tournament.registered_players,
        active_players=len(parsed.players),
        total_pot=int(parsed.total_pot) if parsed.total_pot is not None else None,
        hero_net=hero_net,
        is_all_in=parsed.is_all_in,
        reached_showdown=parsed.reached_showdown,
        board_text=" ".join(parsed.board),
        action_text=action_text,
    )
    db.add(hand)
    db.flush()

    for parsed_player in parsed.players:
        player = players.get(parsed_player.name)
        if player is None:
            player = _get_or_create_player(db, parsed_player.name, False)
            players[parsed_player.name] = player
        db.add(
            HandPlayer(
                hand_id=hand.id,
                player_id=player.id,
                seat=parsed_player.seat,
                position=parsed_player.position,
                starting_stack=int(parsed_player.starting_stack),
                ending_stack=int(parsed_player.ending_stack) if parsed_player.ending_stack is not None else None,
                invested=int(parsed_player.invested),
                won=int(parsed_player.won),
                net=int(parsed_player.net),
                hole_cards=" ".join(parsed_player.hole_cards) or None,
                showed=parsed_player.showed,
                is_winner=parsed_player.is_winner,
                is_all_in=parsed_player.is_all_in,
            )
        )

    for position, card in enumerate(parsed.hero_cards, 1):
        rank, suit = _split_card(card)
        db.add(HeroHoleCard(hand_id=hand.id, position=position, rank=rank, suit=suit))
    for position, card in enumerate(parsed.board, 1):
        rank, suit = _split_card(card)
        street = "flop" if position <= 3 else "turn" if position == 4 else "river"
        db.add(BoardCard(hand_id=hand.id, street=street, position=position, rank=rank, suit=suit))

    running_pot = 0
    street_contributions: dict[str, int] = {}
    current_street = ""
    for action in parsed.actions:
        player = players.get(action.actor)
        if player is None:
            continue
        if action.street != current_street and action.street in {"flop", "turn", "river"}:
            street_contributions = {}
            current_street = action.street
        amount = int(action.amount) if action.amount is not None else None
        to_amount = int(action.to_amount) if action.to_amount is not None else None
        paid = 0
        if action.action_type in {"post_small_blind", "post_big_blind", "post_ante", "call", "bet"}:
            paid = amount or 0
            street_contributions[action.actor] = street_contributions.get(action.actor, 0) + paid
        elif action.action_type == "raise":
            previous = street_contributions.get(action.actor, 0)
            paid = max(0, (to_amount - previous) if to_amount is not None else (amount or 0))
            street_contributions[action.actor] = previous + paid
        elif action.action_type == "uncalled_return":
            paid = -(amount or 0)
        if action.action_type != "collect":
            running_pot = max(0, running_pot + paid)
        db.add(
            Action(
                hand_id=hand.id,
                player_id=player.id,
                sequence=action.sequence,
                street=action.street,
                action_type=action.action_type,
                amount=amount,
                to_amount=to_amount,
                pot_after=running_pot,
                is_all_in=action.all_in,
            )
        )

    classification, quality, explanation, data_quality = _classify(parsed)
    db.add(
        AnalysisResult(
            hand_id=hand.id,
            classification=classification,
            decision_quality=quality,
            financial_result=hero_net,
            actual_result_chips=hero_net,
            explanation=explanation,
            data_quality=data_quality,
        )
    )
    return hand


def _classify(hand: ParsedHand) -> tuple[str, str, str, str]:
    hero = hand.hero
    if hero is None or not hand.hero_cards:
        return (
            "données insuffisantes",
            "non évaluée",
            "La qualité de décision n’est pas déduite du résultat financier.",
            "insufficient",
        )
    hero_actions = [action for action in hand.actions if action.actor.casefold() == hero.name.casefold()]
    if any(action.all_in for action in hero_actions):
        return (
            "décision à forte variance",
            "à revoir avec le contexte",
            "Un all-in mérite une revue séparée; gagner ou perdre ne suffit pas à qualifier la décision.",
            "partial",
        )
    preflop = [action for action in hero_actions if action.street == "preflop"]
    if any(action.action_type == "call" for action in preflop) and any(
        action.action_type == "fold" for action in preflop
    ):
        return (
            "potentiellement trop passif",
            "heuristique à confirmer",
            "Séquence limp/call puis fold détectée; position, profondeur et action adverse restent nécessaires.",
            "partial",
        )
    return (
        "standard",
        "aucune anomalie simple détectée",
        "Classification descriptive uniquement; le résultat financier reste séparé.",
        "partial",
    )


def _get_or_create_player(db: Session, name: str, is_hero: bool) -> Player:
    key = stable_name_key(name)
    player = db.scalar(select(Player).where(Player.name_key == key))
    if player is None:
        player = Player(
            name_key=key,
            display_name=name,
            is_hero=is_hero,
            anonymized_label="HERO" if is_hero else None,
        )
        db.add(player)
        db.flush()
    elif is_hero and not player.is_hero:
        player.is_hero = True
        player.anonymized_label = "HERO"
    return player


def _upsert_file(db: Session, path: Path, file_type: str) -> ImportFile:
    resolved = str(path.resolve())
    row = db.scalar(select(ImportFile).where(ImportFile.path == resolved))
    if row is None:
        row = ImportFile(path=resolved, file_type=file_type, state="detected")
        db.add(row)
        db.flush()
    return row


def _update_metadata(row: ImportFile, path: Path, stat=None) -> None:  # type: ignore[no-untyped-def]
    current = stat or path.stat()
    row.size_bytes = current.st_size
    row.modified_at = datetime.fromtimestamp(current.st_mtime, UTC).replace(tzinfo=None)
    row.last_checked_at = _utcnow_naive()


def _mark_waiting(rows: tuple[ImportFile, ImportFile], message: str) -> None:
    for row in rows:
        row.state = "waiting_for_completion"
        row.error_message = message
        row.last_checked_at = _utcnow_naive()


def _mark_failed(rows: tuple[ImportFile, ImportFile], message: str) -> None:
    for row in rows:
        row.state = "failed"
        row.error_message = message
        row.last_checked_at = _utcnow_naive()


def _mark_imported(rows: tuple[ImportFile, ImportFile], tournament_id: int) -> None:
    imported_at = _utcnow_naive()
    for row in rows:
        row.state = "imported"
        row.error_message = None
        row.imported_at = imported_at
        row.last_checked_at = imported_at
        row.tournament_id = tournament_id


def _store_issues(db: Session, import_file: ImportFile, issues: list[ParseIssue]) -> None:
    existing = {
        (row.line_number, row.error_code, row.line_hash)
        for row in import_file.errors
    }
    for issue in issues:
        excerpt = issue.line_excerpt
        line_hash = hashlib.sha256((excerpt or "").encode("utf-8")).hexdigest() if excerpt else None
        key = (issue.line_number, issue.code, line_hash)
        if key in existing:
            continue
        db.add(
            ImportError(
                import_file_id=import_file.id,
                line_number=issue.line_number,
                line_hash=line_hash,
                sanitized_line=excerpt,
                error_code=issue.code,
                message=issue.message,
            )
        )
        existing.add(key)


def _split_card(card: str) -> tuple[str, str]:
    value = card.strip()
    if len(value) < 2:
        raise ValueError("Invalid card")
    return value[:-1].upper(), value[-1].lower()


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
