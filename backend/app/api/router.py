from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app import __version__
from app.analytics import UNKNOWN_OPPONENT_MESSAGE, calculate_equity
from app.core.process_guard import AnalysisForbiddenError, analysis_interlock
from app.database import get_db
from app.models import Hand, HandPlayer, ImportFile, Tournament, TournamentPlayer
from app.schemas.api import (
    AiAnalysisRequest,
    AnalyzerSettings,
    DeleteRequest,
    RestoreRequest,
    SettingsPatch,
)
from app.schemas.contribution import ContributionPreviewResponse
from app.services.activity_guard import detect_active_tournaments
from app.services.data_management import (
    create_backup,
    delete_analyzed_data,
    export_tournaments_csv,
    list_backups,
    restore_backup,
)
from app.services.contribution import build_contribution_preview
from app.services.importer import rescan_all
from app.services.leak_engine import detect_leaks
from app.services.poker_stats import calculate_hero_stats
from app.services.queries import (
    build_sessions,
    calculate_dashboard,
    hand_to_dict,
    tournament_query,
    tournament_to_dict,
)
from app.services.settings import load_settings, save_settings


router = APIRouter(prefix="/api")


def _process_guard_status() -> dict[str, Any]:
    try:
        analysis_interlock.ensure_allowed()
    except AnalysisForbiddenError:
        pass
    return {
        "enabled": True,
        "blocked": analysis_interlock.blocked,
        "reason": analysis_interlock.reason if analysis_interlock.blocked else None,
    }


class NotesPatch(BaseModel):
    notes: str | None = Field(default=None, max_length=10_000)
    tags: list[str] | None = Field(default=None, max_length=30)


def _load_hands(db: Session, tournament_ids: list[int] | None = None) -> list[Hand]:
    statement = select(Hand).options(
        joinedload(Hand.tournament),
        selectinload(Hand.player_entries).joinedload(HandPlayer.player),
        selectinload(Hand.actions),
        selectinload(Hand.board_cards),
        selectinload(Hand.hero_hole_cards),
        selectinload(Hand.leak_flags),
        joinedload(Hand.analysis),
    )
    if tournament_ids is not None:
        if not tournament_ids:
            return []
        statement = statement.where(Hand.tournament_id.in_(tournament_ids))
    return list(db.scalars(statement.order_by(Hand.played_at)).unique().all())


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    activity = detect_active_tournaments(settings)
    return {
        "status": "ok",
        "version": __version__,
        "host_policy": "loopback-only",
        "telemetry": False,
        "process_guard": _process_guard_status(),
        "active_guard": activity,
        "database": "ready",
    }


@router.get("/dashboard")
def dashboard(
    start: datetime | None = None,
    end: datetime | None = None,
    buyin: float | None = None,
    multiplier: float | None = None,
    rank: int | None = None,
    players: int | None = None,
    result: str | None = Query(default=None, pattern="^(positive|negative)?$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    tournaments = list(
        db.scalars(
            tournament_query(
                start=start,
                end=end,
                buyin=buyin,
                multiplier=multiplier,
                rank=rank,
                players=players,
                result=result,
            )
        ).all()
    )
    data = calculate_dashboard(tournaments)
    hands = _load_hands(db, [tournament.id for tournament in tournaments])
    data["hero_stats"] = calculate_hero_stats(hands)
    data["active_guard"] = detect_active_tournaments(load_settings(db))
    return data


@router.get("/tournaments")
def tournaments(
    start: datetime | None = None,
    end: datetime | None = None,
    buyin: float | None = None,
    multiplier: float | None = None,
    rank: int | None = None,
    players: int | None = None,
    result: str | None = None,
    search: str | None = None,
    analysis_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    values = list(
        db.scalars(
            tournament_query(
                start=start,
                end=end,
                buyin=buyin,
                multiplier=multiplier,
                rank=rank,
                players=players,
                result=result,
            )
        ).all()
    )
    values.reverse()
    if search:
        needle = search.casefold()
        values = [item for item in values if needle in item.external_id.casefold() or needle in item.name.casefold()]
    if analysis_status:
        wanted = analysis_status.casefold()
        values = [
            item
            for item in values
            if ("analysé" if item.analyzed_at else "importé").casefold() == wanted
        ]
    return {"items": [tournament_to_dict(item) for item in values[offset : offset + limit]], "total": len(values)}


@router.get("/tournaments/{tournament_id}")
def tournament_detail(tournament_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(
            selectinload(Tournament.players).joinedload(TournamentPlayer.player),
            selectinload(Tournament.hands),
        )
    )
    if tournament is None:
        raise HTTPException(status_code=404, detail="Partie introuvable")
    data = tournament_to_dict(tournament)
    sorted_players = sorted(tournament.players, key=lambda entry: entry.id)
    data["players_detail"] = [
        {
            "seat": entry.id,
            "name": "HERO" if entry.player.is_hero else (entry.display_alias or f"VILLAIN_{index}"),
            "is_hero": entry.player.is_hero,
            "rank": entry.final_rank,
            "starting_stack": entry.starting_stack,
            "final_stack": entry.final_stack,
        }
        for index, entry in enumerate(sorted_players, 1)
    ]
    detailed_hands = _load_hands(db, [tournament.id])
    data["hands_detail"] = [hand_to_dict(hand) for hand in detailed_hands]
    return data


@router.patch("/tournaments/{tournament_id}")
def update_tournament(tournament_id: int, patch: NotesPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Partie introuvable")
    if patch.notes is not None:
        tournament.notes = patch.notes
    if patch.tags is not None:
        tournament.tags_json = json.dumps(list(dict.fromkeys(patch.tags)), ensure_ascii=False)
    db.commit()
    return tournament_to_dict(tournament)


@router.get("/hands")
def hands(
    cards: str | None = None,
    position: str | None = None,
    max_stack_bb: float | None = None,
    all_in: bool | None = None,
    showdown: bool | None = None,
    min_pot_bb: float | None = None,
    lost: bool | None = None,
    leak: bool | None = None,
    text: str | None = None,
    preflop_action: str | None = None,
    postflop_action: str | None = None,
    call_shove: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    values = [hand_to_dict(hand) for hand in reversed(_load_hands(db))]
    if cards:
        ranks = "".join(character for character in cards.upper() if character in "23456789TJQKA")
        values = [item for item in values if _cards_match(item["cards"], ranks)]
    if position:
        values = [item for item in values if (item["position"] or "").casefold() == position.casefold()]
    if max_stack_bb is not None:
        values = [item for item in values if item["stack_bb"] is not None and item["stack_bb"] <= max_stack_bb]
    if all_in is not None:
        values = [item for item in values if item["all_in"] is all_in]
    if showdown is not None:
        values = [item for item in values if item["showdown"] is showdown]
    if min_pot_bb is not None:
        values = [
            item
            for item in values
            if item["pot"] is not None and item["big_blind"] and item["pot"] / item["big_blind"] >= min_pot_bb
        ]
    if lost is not None:
        values = [item for item in values if ((item["net"] or 0) < 0) is lost]
    if leak is not None:
        values = [item for item in values if item["leak_detected"] is leak]
    if text:
        needle = text.casefold()
        values = [item for item in values if needle in json.dumps(item, ensure_ascii=False).casefold()]
    if preflop_action:
        needle = preflop_action.casefold()
        values = [item for item in values if needle in item["preflop_action"].casefold()]
    if postflop_action:
        needle = postflop_action.casefold()
        values = [item for item in values if needle in item["postflop_action"].casefold()]
    if call_shove is not None:
        values = [item for item in values if item["call_shove"] is call_shove]
    return {"items": values[offset : offset + limit], "total": len(values)}


def _cards_match(cards: str, query: str) -> bool:
    ranks = "".join(character for character in cards.upper() if character in "23456789TJQKA")
    return not query or query == ranks or query == ranks[::-1]


def _get_hand_or_404(db: Session, hand_id: int) -> Hand:
    hand = db.scalar(
        select(Hand)
        .where(Hand.id == hand_id)
        .options(
            joinedload(Hand.tournament),
            selectinload(Hand.player_entries).joinedload(HandPlayer.player),
            selectinload(Hand.actions),
            selectinload(Hand.board_cards),
            selectinload(Hand.hero_hole_cards),
            selectinload(Hand.leak_flags),
            joinedload(Hand.analysis),
        )
    )
    if hand is None:
        raise HTTPException(status_code=404, detail="Main introuvable")
    return hand


def _calculate_hand_equity(hand: Hand) -> dict[str, Any]:
    hero_entry = next((entry for entry in hand.player_entries if entry.player.is_hero), None)
    if hero_entry is None or not hand.is_all_in:
        return {"available": False, "message": "Équité non calculable : aucun all-in complet dans cette main."}
    all_in_player_ids = {action.player_id for action in hand.actions if action.is_all_in}
    opponent_entries = [
        entry
        for entry in hand.player_entries
        if entry.player_id != hero_entry.player_id and entry.player_id in all_in_player_ids
    ]
    if not opponent_entries or any(not entry.hole_cards for entry in opponent_entries):
        return {"available": False, "message": "Équité non calculable : cartes adverses inconnues."}
    hero_cards = [
        f"{card.rank}{card.suit}" for card in sorted(hand.hero_hole_cards, key=lambda item: item.position)
    ]
    opponents = [entry.hole_cards.split() for entry in opponent_entries if entry.hole_cards]
    first_all_in = min((action for action in hand.actions if action.is_all_in), key=lambda item: item.sequence)
    street_card_count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}.get(first_all_in.street, 5)
    board = [
        f"{card.rank}{card.suit}"
        for card in sorted(hand.board_cards, key=lambda item: item.position)[:street_card_count]
    ]
    return calculate_equity(
        hero_cards,
        opponents,
        board,
        final_pot=hand.total_pot,
        hero_investment=hero_entry.invested,
        actual_result=hand.hero_net,
    )


@router.get("/hands/{hand_id}")
def hand_detail(hand_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    hand = _get_hand_or_404(db, hand_id)
    data = hand_to_dict(hand)
    data["actions"] = [
        {
            "sequence": action.sequence,
            "street": action.street,
            "type": action.action_type,
            "amount": action.amount,
            "to_amount": action.to_amount,
            "all_in": action.is_all_in,
        }
        for action in sorted(hand.actions, key=lambda item: item.sequence)
    ]
    data["analysis"] = (
        {
            "classification": hand.analysis.classification,
            "decision_quality": hand.analysis.decision_quality,
            "financial_result": hand.analysis.financial_result,
            "explanation": hand.analysis.explanation,
            "data_quality": hand.analysis.data_quality,
        }
        if hand.analysis
        else {
            "classification": "données insuffisantes",
            "decision_quality": None,
            "financial_result": hand.hero_net,
            "explanation": "Le résultat financier est séparé de la qualité supposée de la décision.",
            "data_quality": "insufficient",
        }
    )
    return data


@router.patch("/hands/{hand_id}")
def update_hand(hand_id: int, patch: NotesPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    hand = db.get(Hand, hand_id)
    if hand is None:
        raise HTTPException(status_code=404, detail="Main introuvable")
    if patch.notes is not None:
        hand.notes = patch.notes
    if patch.tags is not None:
        hand.tags_json = json.dumps(list(dict.fromkeys(patch.tags)), ensure_ascii=False)
    db.commit()
    return {"id": hand.id, "notes": hand.notes, "tags": json.loads(hand.tags_json)}


@router.get("/hands/{hand_id}/replay")
def replay(hand_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    activity = detect_active_tournaments(settings)
    if activity["active"]:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Replayer bloqué : une partie est potentiellement active. Attendre le résumé final.",
        )
    hand = _get_hand_or_404(db, hand_id)
    entries = sorted(hand.player_entries, key=lambda entry: entry.seat)
    labels: dict[int, str] = {}
    villain = 1
    for entry in entries:
        if entry.player.is_hero:
            labels[entry.player_id] = "HERO"
        else:
            labels[entry.player_id] = f"VILLAIN_{villain}"
            villain += 1
    board = [f"{card.rank}{card.suit}" for card in sorted(hand.board_cards, key=lambda card: card.position)]
    hero_cards = [
        f"{card.rank}{card.suit}" for card in sorted(hand.hero_hole_cards, key=lambda card: card.position)
    ]
    equity_result = _calculate_hand_equity(hand)
    equity = (
        {
            "win": equity_result.get("win_probability"),
            "tie": equity_result.get("tie_probability"),
            "lose": equity_result.get("loss_probability"),
            "ev_chips": equity_result.get("ev_chips"),
            "actual_chips": equity_result.get("actual_result_chips"),
            "message": equity_result.get("message"),
            "method": equity_result.get("method"),
        }
        if equity_result.get("available")
        else None
    )
    return {
        "id": hand.id,
        "hand_id": hand.external_id,
        "tournament_id": hand.tournament.external_id,
        "blinds": {"small": hand.small_blind, "big": hand.big_blind, "ante": hand.ante},
        "button_seat": hand.button_seat,
        "pot": hand.total_pot,
        "hero_cards": hero_cards,
        "board": board,
        "players": [
            {
                "seat": entry.seat,
                "name": labels[entry.player_id],
                "position": entry.position,
                "stack": entry.starting_stack,
                "final_stack": entry.ending_stack,
                "hole_cards": entry.hole_cards.split() if entry.showed and entry.hole_cards else [],
                "is_hero": entry.player.is_hero,
                "winner": entry.is_winner,
            }
            for entry in entries
        ],
        "actions": [
            {
                "step": index,
                "sequence": action.sequence,
                "street": action.street,
                "actor": labels.get(action.player_id, "JOUEUR"),
                "type": action.action_type,
                "amount": action.amount,
                "to_amount": action.to_amount,
                "pot_after": action.pot_after,
                "all_in": action.is_all_in,
            }
            for index, action in enumerate(sorted(hand.actions, key=lambda item: item.sequence), 1)
        ],
        "result": {"hero_net": hand.hero_net, "showdown": hand.reached_showdown},
        "equity": equity,
        "notes": hand.notes,
        "tags": json.loads(hand.tags_json),
        "post_session_only": True,
    }


@router.get("/hands/{hand_id}/equity")
def hand_equity(hand_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    if detect_active_tournaments(settings)["active"]:
        raise HTTPException(status_code=423, detail="Calcul d’équité bloqué pendant une activité potentielle")
    hand = _get_hand_or_404(db, hand_id)
    result = _calculate_hand_equity(hand)
    if result.get("available") and hand.analysis is not None:
        hand.analysis.win_probability = result.get("win_probability")
        hand.analysis.tie_probability = result.get("tie_probability")
        hand.analysis.loss_probability = result.get("loss_probability")
        hand.analysis.theoretical_ev_chips = result.get("ev_chips")
        hand.analysis.data_quality = "complete_known_showdown"
        db.commit()
    return result


@router.get("/sessions")
def sessions(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    values = list(db.scalars(tournament_query()).all())
    items = build_sessions(values, settings.session_gap_minutes)
    return {"items": items, "total": len(items), "gap_minutes": settings.session_gap_minutes}


@router.get("/leaks")
def leaks(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    tournaments = list(db.scalars(tournament_query()).all())
    dashboard_data = calculate_dashboard(tournaments)
    hands_data = _load_hands(db, [item.id for item in tournaments])
    hero_stats = calculate_hero_stats(hands_data)
    items = detect_leaks(hero_stats, dashboard_data, settings, hands_data)
    return {
        "items": items,
        "total": len(items),
        "thresholds": settings.leak_thresholds,
        "disclaimer": "Seuils configurables et heuristiques pédagogiques; ils ne constituent pas une stratégie GTO absolue.",
    }


@router.get("/settings", response_model=AnalyzerSettings)
def get_settings(db: Session = Depends(get_db)) -> AnalyzerSettings:
    return load_settings(db)


@router.put("/settings", response_model=AnalyzerSettings)
def put_settings(patch: SettingsPatch, db: Session = Depends(get_db)) -> AnalyzerSettings:
    current = load_settings(db)
    updates = patch.model_dump(exclude_unset=True, exclude_none=True)
    value = current.model_copy(update=updates)
    value = AnalyzerSettings.model_validate(value.model_dump())
    return save_settings(db, value)


@router.get("/import/status")
def import_status(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    counts = dict(db.execute(select(ImportFile.state, func.count()).group_by(ImportFile.state)).all())
    last_import = db.scalar(select(func.max(ImportFile.imported_at)))
    watcher = getattr(request.app.state, "history_watcher", None)
    watcher_state = getattr(watcher, "is_running", False) if watcher is not None else False
    watcher_running = bool(watcher_state() if callable(watcher_state) else watcher_state)
    return {
        "states": {
            "detected": counts.get("detected", 0),
            "waiting_for_completion": counts.get("waiting_for_completion", 0),
            "imported": counts.get("imported", 0),
            "failed": counts.get("failed", 0),
        },
        "last_import": last_import.isoformat() if last_import else None,
        "history_paths": settings.history_paths,
        "watcher_running": watcher_running,
        "process_guard": _process_guard_status(),
        "active_guard": detect_active_tournaments(settings),
    }


@router.post("/import/rescan")
def rescan(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        analysis_interlock.ensure_allowed()
        settings = load_settings(db)
        return rescan_all(db, settings).to_dict()
    except AnalysisForbiddenError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rescannage interdit par le verrou de sécurité.",
        ) from exc


@router.post("/database/backup")
def backup() -> dict[str, Any]:
    path = create_backup()
    return {"message": "Sauvegarde créée", "name": path.name, "size_bytes": path.stat().st_size}


@router.get("/database/backups")
def backups() -> dict[str, Any]:
    return {"items": list_backups()}


@router.post("/database/restore")
def restore(request: RestoreRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise")
    try:
        restore_backup(request.backup_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Sauvegarde introuvable") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Base restaurée; redémarrez l’application."}


@router.delete("/database/data")
def delete_data(request: DeleteRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if request.confirmation != "SUPPRIMER":
        raise HTTPException(status_code=400, detail="Saisir SUPPRIMER pour confirmer")
    delete_analyzed_data(db)
    return {"message": "Données d’analyse supprimées; paramètres conservés."}


@router.get("/export/tournaments.csv", response_class=PlainTextResponse)
def export_csv(
    anonymize: bool | None = None,
    db: Session = Depends(get_db),
) -> Response:
    settings = load_settings(db)
    content = export_tournaments_csv(db, settings.anonymize_exports if anonymize is None else anonymize)
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=winamax-expresso.csv"},
    )


@router.get("/contributions/preview", response_model=ContributionPreviewResponse)
def contribution_preview(
    request: Request,
    db: Session = Depends(get_db),
) -> ContributionPreviewResponse:
    """Build an explicit local preview; this endpoint never uploads or writes it."""
    interlock = getattr(request.app.state, "analysis_interlock", analysis_interlock)
    try:
        interlock.ensure_allowed()
        settings = load_settings(db)
        if detect_active_tournaments(settings)["active"]:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Contribution bloquée pendant une activité potentielle.",
            )
        preview = build_contribution_preview(db, interlock=interlock)
        if detect_active_tournaments(settings)["active"]:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Contribution bloquée pendant une activité potentielle.",
            )
        interlock.ensure_allowed()
        return preview
    except AnalysisForbiddenError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contribution interdite par le verrou de sécurité.",
        ) from exc


@router.get("/ai/preview/{hand_id}")
def ai_preview(hand_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    hand = _get_hand_or_404(db, hand_id)
    payload = replay_payload_without_guard(hand)
    return {
        "enabled": load_settings(db).ai_enabled,
        "will_send": False,
        "requires_confirmation": True,
        "payload": payload,
        "privacy": "Noms adverses pseudonymisés; main terminée uniquement.",
    }


@router.post("/ai/analyze")
def ai_analyze(request: AiAnalysisRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = load_settings(db)
    activity = detect_active_tournaments(settings)
    if activity["active"]:
        raise HTTPException(status_code=423, detail="Analyse IA bloquée pendant une activité potentielle")
    if not settings.ai_enabled or not request.confirmed:
        raise HTTPException(status_code=400, detail="Option désactivée ou confirmation absente")
    raise HTTPException(
        status_code=501,
        detail="Connecteur préparé mais aucun fournisseur externe n’est configuré; aucune donnée n’a été envoyée.",
    )


def replay_payload_without_guard(hand: Hand) -> dict[str, Any]:
    entries = sorted(hand.player_entries, key=lambda entry: entry.seat)
    labels: dict[int, str] = {}
    count = 1
    for entry in entries:
        if entry.player.is_hero:
            labels[entry.player_id] = "HERO"
        else:
            labels[entry.player_id] = f"VILLAIN_{count}"
            count += 1
    return {
        "hand_id": hand.external_id,
        "completed": hand.tournament.completed,
        "blinds": [hand.small_blind, hand.big_blind, hand.ante],
        "hero_cards": [f"{card.rank}{card.suit}" for card in hand.hero_hole_cards],
        "board": [f"{card.rank}{card.suit}" for card in hand.board_cards],
        "actions": [
            {
                "street": action.street,
                "actor": labels.get(action.player_id, "PLAYER"),
                "type": action.action_type,
                "amount": action.amount,
                "all_in": action.is_all_in,
            }
            for action in sorted(hand.actions, key=lambda item: item.sequence)
        ],
    }
