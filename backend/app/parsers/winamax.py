from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.core.privacy import sanitize_log_line

from .encoding import ParserSource, load_text
from .models import (
    HandHistoryParseResult,
    ParseIssue,
    ParsedAction,
    ParsedHand,
    ParsedPlayer,
    PotAward,
    TournamentSummary,
)


SUMMARY_HEADER_RE = re.compile(
    r"^Winamax Poker\s*-\s*(?:Tournament summary|R[ée]sum[ée] du tournoi)\s*:\s*"
    r"(?P<name>.*?)(?:\((?P<id>\d+)\))?\s*$",
    re.IGNORECASE,
)
HAND_HEADER_RE = re.compile(
    r'^Winamax Poker\s*-\s*(?:Tournament|Tournoi)\s+"(?P<name>[^"]+)"\s+'
    r"(?:buyIn|buy-in|droit d['’]entr[ée]e)\s*:\s*(?P<buyin>.*?)\s+"
    r"(?:level|niveau)\s*:\s*(?P<level>\d+)\s*-\s*"
    r"(?:HandId|MainId|Main)\s*:\s*#(?P<hand_id>\S+)\s*-\s*"
    r"(?P<game>.*?)\s+\((?P<blinds>[^)]+)\)\s*-\s*(?P<date>.+?)\s*$",
    re.IGNORECASE,
)
TABLE_RE = re.compile(
    r"^Table\s*:\s*'(?P<table>.*?)'\s+(?P<max>\d+)-max.*?Seat\s*#(?P<button>\d+)\s+is\s+the\s+button\s*$",
    re.IGNORECASE,
)
TABLE_FR_RE = re.compile(
    r"^Table\s*:\s*'(?P<table>.*?)'\s+(?P<max>\d+)-max.*?Si[èe]ge\s*#(?P<button>\d+).*?bouton\s*$",
    re.IGNORECASE,
)
TOURNAMENT_ID_RE = re.compile(r"\((?P<id>\d+)\)#\d+$")
SEAT_RE = re.compile(
    r"^Seat\s+(?P<seat>\d+)\s*:\s*(?P<name>.+?)\s+\(\s*(?P<stack>[\d\s.,]+)\s*\)\s*$",
    re.IGNORECASE,
)
DEALT_RE = re.compile(r"^(?:Dealt to|Distribu[ée] [àa])\s+(?P<name>.+?)\s+(?P<cards>\[[^]]+])\s*$", re.IGNORECASE)
CARD_RE = re.compile(r"(?<![A-Za-z0-9])(?:[2-9TJQKA][cdhs])(?![A-Za-z0-9])", re.IGNORECASE)
TOTAL_POT_RE = re.compile(r"^Total pot\s+(?P<pot>[\d\s.,]+)(?:\s*\|\s*(?P<rake>.+))?$", re.IGNORECASE)
BOARD_RE = re.compile(r"^(?:Board|Tableau)\s*:\s*(?P<cards>.+)$", re.IGNORECASE)
SUMMARY_SEAT_RE = re.compile(r"^Seat\s+\d+\s*:\s*.+$", re.IGNORECASE)
UNCALLED_RE = re.compile(
    r"^Uncalled bet\s*\((?P<amount>[\d\s.,]+)\)\s+returned to\s+(?P<name>.+)$",
    re.IGNORECASE,
)

SECTION_NAMES = {
    "ANTE/BLINDS": "preflop",
    "BLINDS/ANTES": "preflop",
    "PRE-FLOP": "preflop",
    "PREFLOP": "preflop",
    "FLOP": "flop",
    "TURN": "turn",
    "RIVER": "river",
    "SHOW DOWN": "showdown",
    "SHOWDOWN": "showdown",
    "SUMMARY": "summary",
    "RÉSUMÉ": "summary",
}


def parse_hand_history(source: ParserSource, hero_name: str | None = None) -> HandHistoryParseResult:
    """Parse a Winamax hand-history file, bytes buffer, or text string.

    Parsing is deliberately tolerant: malformed and unknown lines become
    :class:`ParseIssue` objects instead of being silently discarded.
    """

    loaded = load_text(source)
    result = HandHistoryParseResult(encoding=loaded.encoding, source_hash=loaded.source_hash)
    chunks, outside_lines = _split_hand_chunks(loaded.text)
    for number, line in outside_lines:
        if line.strip() and not SUMMARY_HEADER_RE.match(line.strip()):
            result.issues.append(
                _issue("unknown_document_line", "Line outside a hand was not recognized", number, line, hero_name, ())
            )

    if not chunks:
        result.issues.append(ParseIssue("no_hands", "No Winamax hand header was found", severity="error"))
        return result

    seen_ids: set[str] = set()
    for start_line, lines in chunks:
        hand = _parse_hand(lines, start_line, hero_name)
        if hand.external_id in seen_ids:
            result.issues.append(
                ParseIssue(
                    "duplicate_hand",
                    "Duplicate hand identifier ignored",
                    start_line,
                    severity="warning",
                )
            )
            continue
        seen_ids.add(hand.external_id)
        result.hands.append(hand)
        result.issues.extend(hand.issues)
    return result


def parse_tournament_summary(source: ParserSource) -> TournamentSummary:
    """Parse a Winamax tournament summary in English or French."""

    loaded = load_text(source)
    summary = TournamentSummary(encoding=loaded.encoding, source_hash=loaded.source_hash)
    lines = loaded.text.splitlines()
    hero_names: list[str] = []
    saw_header = False

    for line_number, original in enumerate(lines, 1):
        line = original.strip().lstrip("\ufeff")
        if not line:
            continue
        header = SUMMARY_HEADER_RE.match(line)
        if header:
            saw_header = True
            summary.name = header.group("name").strip()
            summary.tournament_id = header.group("id")
            continue

        key, separator, value = line.partition(":")
        normalized_key = _normalize_label(key)
        value = value.strip() if separator else ""
        if normalized_key in {"player", "joueur"} and separator:
            summary.hero_name = value
            hero_names[:] = [value]
        elif normalized_key in {"buy-in", "buyin", "droit d'entree", "droits d'entree"} and separator:
            amount, fee, currency = _parse_buyin(value)
            summary.buy_in_amount, summary.fee_amount, summary.currency = amount, fee, currency
            if amount is None:
                summary.issues.append(
                    _issue("invalid_buy_in", "Tournament buy-in could not be parsed", line_number, original, summary.hero_name, hero_names)
                )
        elif normalized_key in {"registered players", "joueurs inscrits"} and separator:
            summary.registered_players = _first_int(value)
            if summary.registered_players is None:
                summary.issues.append(
                    _issue("invalid_player_count", "Registered-player count could not be parsed", line_number, original, summary.hero_name, hero_names)
                )
        elif normalized_key == "mode" and separator:
            summary.mode = value
        elif normalized_key in {"type", "tournament type", "type de tournoi"} and separator:
            summary.tournament_type = value
        elif normalized_key in {"speed", "vitesse"} and separator:
            summary.speed = value
        elif normalized_key in {"flight id", "id de flight"} and separator:
            summary.flight_id = value
        elif normalized_key in {"levels", "niveaux"} and separator:
            summary.levels = value
        elif normalized_key in {"prizepool", "prize pool", "cagnotte"} and separator:
            summary.prize_pool = _parse_decimal(value)
            summary.currency = summary.currency or _currency(value)
            if summary.prize_pool is None:
                summary.issues.append(
                    _issue("invalid_prize_pool", "Prize pool could not be parsed", line_number, original, summary.hero_name, hero_names)
                )
        elif re.match(r"^(?:Tournament started|Tournoi commenc[ée])\s+", line, re.IGNORECASE):
            date_value = re.sub(r"^(?:Tournament started|Tournoi commenc[ée])\s+", "", line, flags=re.IGNORECASE)
            summary.started_at = _parse_datetime(date_value)
            if summary.started_at is None:
                summary.issues.append(
                    _issue("invalid_start_date", "Tournament start date could not be parsed", line_number, original, summary.hero_name, hero_names)
                )
        elif re.match(r"^(?:You played|Vous avez jou[ée])\s+", line, re.IGNORECASE):
            duration = re.sub(r"^(?:You played|Vous avez jou[ée])\s+", "", line, flags=re.IGNORECASE)
            summary.duration_seconds = _parse_duration(duration)
            if summary.duration_seconds is None:
                summary.issues.append(
                    _issue("invalid_duration", "Tournament duration could not be parsed", line_number, original, summary.hero_name, hero_names)
                )
        elif re.match(r"^(?:You finished|Vous avez termin[ée])\s+", line, re.IGNORECASE):
            summary.final_rank = _first_int(line)
            if summary.final_rank is None:
                summary.issues.append(
                    _issue("invalid_final_rank", "Final tournament rank could not be parsed", line_number, original, summary.hero_name, hero_names)
                )
        elif re.match(r"^(?:You won|Vous avez gagn[ée])\s+", line, re.IGNORECASE):
            won_value = re.sub(r"^(?:You won|Vous avez gagn[ée])\s+", "", line, flags=re.IGNORECASE).strip()
            money = _parse_decimal(won_value)
            if money is not None and re.search(r"[€$£]|\bEUR\b|\bUSD\b|\bGBP\b", won_value, re.IGNORECASE):
                summary.reward = money
                summary.currency = summary.currency or _currency(won_value)
                ticket_text = re.sub(r"[\d\s.,]+\s*(?:€|\$|£|EUR|USD|GBP)?", "", won_value, count=1, flags=re.IGNORECASE).strip(" ,-+")
                if "ticket" in ticket_text.casefold():
                    summary.ticket = ticket_text
            elif won_value:
                summary.ticket = won_value
        else:
            summary.issues.append(
                _issue(
                    "unknown_summary_line",
                    "Tournament summary line was not recognized",
                    line_number,
                    original,
                    summary.hero_name,
                    hero_names,
                )
            )

    if not saw_header:
        summary.issues.append(ParseIssue("missing_summary_header", "Tournament summary header is missing", severity="error"))
    if summary.final_rank is None:
        summary.issues.append(ParseIssue("missing_final_rank", "Final tournament rank is missing", severity="warning"))
    summary.complete = saw_header and summary.final_rank is not None
    return summary


def is_complete(
    hand_history: ParserSource | HandHistoryParseResult | TournamentSummary,
    tournament_summary: ParserSource | TournamentSummary | None = None,
    *,
    now: datetime | None = None,
    quiet_period_seconds: int = 60,
) -> bool:
    """Conservatively confirm that a tournament is safe for post-session import.

    A hand-history alone is never sufficient: a final tournament summary with a
    rank is required.  When both are supplied, all hands must have their summary
    section and the last hand must be at least ``quiet_period_seconds`` old.
    """

    if tournament_summary is None:
        # A final summary alone confirms the rank but cannot enforce the mandatory
        # quiet period after the last hand. In doubt, wait.
        return False

    hands = hand_history if isinstance(hand_history, HandHistoryParseResult) else parse_hand_history(hand_history)
    summary = tournament_summary if isinstance(tournament_summary, TournamentSummary) else parse_tournament_summary(tournament_summary)
    if not summary.complete or not hands.complete:
        return False
    if summary.tournament_id and hands.tournament_ids and summary.tournament_id not in hands.tournament_ids:
        return False

    last_hand = hands.last_hand_at
    if last_hand is None:
        return False
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if last_hand.tzinfo is None:
        last_hand = last_hand.replace(tzinfo=UTC)
    required_quiet_period = max(60, int(quiet_period_seconds))
    return (current.astimezone(UTC) - last_hand.astimezone(UTC)).total_seconds() >= required_quiet_period


def _split_hand_chunks(text: str) -> tuple[list[tuple[int, list[str]]], list[tuple[int, str]]]:
    chunks: list[tuple[int, list[str]]] = []
    outside: list[tuple[int, str]] = []
    current: list[str] | None = None
    start_line = 1
    in_summary_document = False
    for line_number, original in enumerate(text.splitlines(), 1):
        line = original.lstrip("\ufeff")
        if SUMMARY_HEADER_RE.match(line.strip()):
            if current is not None:
                chunks.append((start_line, current))
                current = None
            in_summary_document = True
            outside.append((line_number, line))
            continue
        if HAND_HEADER_RE.match(line):
            if current is not None:
                chunks.append((start_line, current))
            current = [line]
            start_line = line_number
            in_summary_document = False
        elif current is not None and not in_summary_document:
            current.append(line)
        elif not in_summary_document:
            outside.append((line_number, line))
    if current is not None:
        chunks.append((start_line, current))
    return chunks, outside


def _parse_hand(lines: list[str], start_line: int, configured_hero: str | None) -> ParsedHand:
    header_match = HAND_HEADER_RE.match(lines[0].strip().lstrip("\ufeff"))
    if not header_match:  # defensive; chunking normally excludes this case
        issue = _issue("malformed_header", "Hand header could not be parsed", start_line, lines[0], configured_hero, ())
        return ParsedHand(
            external_id=f"malformed-{start_line}",
            tournament_id=None,
            tournament_name=None,
            hand_number=None,
            played_at=None,
            level=None,
            game_type=None,
            buy_in_amount=None,
            fee_amount=None,
            currency=None,
            small_blind=None,
            big_blind=None,
            issues=[issue],
        )

    buyin, fee, currency = _parse_buyin(header_match.group("buyin"))
    blind_values = [_parse_decimal(part) for part in re.split(r"\s*/\s*", header_match.group("blinds"))]
    small_blind = blind_values[0] if blind_values else None
    big_blind = blind_values[1] if len(blind_values) > 1 else None
    ante = blind_values[2] if len(blind_values) > 2 else None
    external_id = header_match.group("hand_id")
    hand_number_match = re.search(r"-(\d+)-\d+$", external_id)
    hand = ParsedHand(
        external_id=external_id,
        tournament_id=None,
        tournament_name=header_match.group("name").strip(),
        hand_number=int(hand_number_match.group(1)) if hand_number_match else None,
        played_at=_parse_datetime(header_match.group("date")),
        level=int(header_match.group("level")),
        game_type=header_match.group("game").strip(),
        buy_in_amount=buyin,
        fee_amount=fee,
        currency=currency,
        small_blind=small_blind,
        big_blind=big_blind,
        ante=ante,
    )

    # Seats are collected first so every issue can redact all known player names.
    for line in lines[1:]:
        seat_match = SEAT_RE.match(line.strip())
        if seat_match:
            hand.players.append(
                ParsedPlayer(
                    seat=int(seat_match.group("seat")),
                    name=seat_match.group("name").strip(),
                    starting_stack=_parse_decimal(seat_match.group("stack")) or Decimal("0"),
                )
            )
    known_names = [player.name for player in hand.players]
    hand.hero_name = configured_hero
    current_street = "preflop"
    sequence = 0
    summary_seen = False
    contributions: dict[str, Decimal] = {name: Decimal("0") for name in known_names}

    for offset, original in enumerate(lines[1:], 1):
        line_number = start_line + offset
        line = original.strip()
        if not line:
            continue

        table_match = TABLE_RE.match(line) or TABLE_FR_RE.match(line)
        if table_match:
            hand.table_name = table_match.group("table")
            hand.max_players = int(table_match.group("max"))
            hand.button_seat = int(table_match.group("button"))
            tournament_match = TOURNAMENT_ID_RE.search(hand.table_name)
            if tournament_match:
                hand.tournament_id = tournament_match.group("id")
            continue
        if SEAT_RE.match(line):
            continue

        section = _parse_section(line)
        if section:
            new_street, cards = section
            if new_street == "summary":
                summary_seen = True
            elif new_street in {"flop", "turn", "river"}:
                if new_street != current_street:
                    contributions = {name: Decimal("0") for name in known_names}
                if len(cards) >= len(hand.board):
                    hand.board = cards
            if new_street != "summary":
                current_street = new_street
            continue

        dealt = DEALT_RE.match(line)
        if dealt:
            name = dealt.group("name").strip()
            cards = _cards(dealt.group("cards"))
            hand.hero_name = configured_hero or name
            hand.hero_cards = cards
            player = _player(hand, name)
            if player:
                player.hole_cards = cards
            else:
                hand.issues.append(
                    _issue("dealt_unknown_player", "Cards were dealt to a player not found in seats", line_number, original, hand.hero_name, known_names)
                )
            continue

        total_match = TOTAL_POT_RE.match(line)
        if total_match:
            hand.total_pot = _parse_decimal(total_match.group("pot"))
            rake_text = total_match.group("rake") or ""
            if re.search(r"no rake|sans commission", rake_text, re.IGNORECASE):
                hand.rake = Decimal("0")
            else:
                hand.rake = _parse_decimal(rake_text)
            continue
        board_match = BOARD_RE.match(line)
        if board_match:
            cards = _cards(board_match.group("cards"))
            if cards:
                hand.board = cards
            continue
        if SUMMARY_SEAT_RE.match(line) and summary_seen:
            _apply_summary_seat(hand, line)
            continue

        uncalled = UNCALLED_RE.match(line)
        if uncalled:
            name = uncalled.group("name").strip()
            amount = _parse_decimal(uncalled.group("amount"))
            sequence += 1
            hand.actions.append(ParsedAction(sequence, current_street, name, "uncalled_return", amount=amount))
            player = _player(hand, name)
            if player and amount is not None:
                player.invested = max(Decimal("0"), player.invested - amount)
                contributions[name] = max(Decimal("0"), contributions.get(name, Decimal("0")) - amount)
            continue

        actor, body = _actor_and_body(line, known_names)
        if actor:
            parsed = _parse_action_body(body)
            if parsed:
                action_type, amount, to_amount, all_in, cards, description, pot_name = parsed
                sequence += 1
                action = ParsedAction(
                    sequence=sequence,
                    street=current_street,
                    actor=actor,
                    action_type=action_type,
                    amount=amount,
                    to_amount=to_amount,
                    all_in=all_in,
                    cards=cards,
                    description=description,
                    pot_name=pot_name,
                )
                hand.actions.append(action)
                _apply_action(hand, action, contributions)
                continue

        hand.issues.append(
            _issue("unknown_hand_line", "Hand-history line was not recognized", line_number, original, hand.hero_name, known_names)
        )

    _assign_positions_and_end_stacks(hand)
    hand.reached_showdown = any(action.action_type == "show" for action in hand.actions)
    hand.complete = summary_seen and hand.total_pot is not None
    if not summary_seen:
        hand.issues.append(ParseIssue("missing_hand_summary", "Hand summary section is missing", severity="warning"))
    elif hand.total_pot is None:
        hand.issues.append(ParseIssue("missing_total_pot", "Hand summary has no total pot", severity="warning"))
    if hand.played_at is None:
        hand.issues.append(ParseIssue("invalid_hand_date", "Hand date could not be parsed", start_line, severity="warning"))
    return hand


def _parse_action_body(
    body: str,
) -> tuple[str, Decimal | None, Decimal | None, bool, list[str], str | None, str | None] | None:
    all_in = bool(re.search(r"(?:and\s+)?is all-in|tapis", body, re.IGNORECASE))
    clean = re.sub(r"\s+(?:and\s+)?is all-in\s*$", "", body, flags=re.IGNORECASE).strip(" ,")
    clean = re.sub(r"\s+et\s+fait\s+tapis\s*$", "", clean, flags=re.IGNORECASE).strip(" ,")

    match = re.match(r"^posts small blind\s+([\d\s.,]+)$", clean, re.IGNORECASE)
    if match:
        return "post_small_blind", _parse_decimal(match.group(1)), None, all_in, [], None, None
    match = re.match(r"^posts big blind\s+([\d\s.,]+)$", clean, re.IGNORECASE)
    if match:
        return "post_big_blind", _parse_decimal(match.group(1)), None, all_in, [], None, None
    match = re.match(r"^posts (?:the )?ante\s+([\d\s.,]+)$", clean, re.IGNORECASE)
    if match:
        return "post_ante", _parse_decimal(match.group(1)), None, all_in, [], None, None
    if re.fullmatch(r"folds|se couche", clean, re.IGNORECASE):
        return "fold", None, None, all_in, [], None, None
    if re.fullmatch(r"checks|parole", clean, re.IGNORECASE):
        return "check", None, None, all_in, [], None, None
    match = re.match(r"^(?:calls|suit)\s+([\d\s.,]+)$", clean, re.IGNORECASE)
    if match:
        return "call", _parse_decimal(match.group(1)), None, all_in, [], None, None
    match = re.match(r"^(?:bets|mise)\s+([\d\s.,]+)$", clean, re.IGNORECASE)
    if match:
        return "bet", _parse_decimal(match.group(1)), None, all_in, [], None, None
    match = re.match(r"^(?:raises|relance(?: de)?)\s+([\d\s.,]+)\s+(?:to|[àa])\s+([\d\s.,]+)$", clean, re.IGNORECASE)
    if match:
        return "raise", _parse_decimal(match.group(1)), _parse_decimal(match.group(2)), all_in, [], None, None
    match = re.match(r"^(?:shows|montre)\s+(\[[^]]+])(?:\s+\((.*?)\))?$", clean, re.IGNORECASE)
    if match:
        return "show", None, None, all_in, _cards(match.group(1)), match.group(2), None
    if re.fullmatch(r"mucks|doesn't show hand|ne montre pas", clean, re.IGNORECASE):
        return "muck", None, None, all_in, [], None, None
    match = re.match(
        r"^(?:collected|remporte)\s+([\d\s.,]+)\s+from\s+(?:(main pot|side pot\s*\d+|pot))$",
        clean,
        re.IGNORECASE,
    )
    if not match:
        match = re.match(r"^(?:collected|remporte)\s+([\d\s.,]+)\s+from\s+(.+)$", clean, re.IGNORECASE)
    if match:
        return "collect", _parse_decimal(match.group(1)), None, all_in, [], None, match.group(2).strip()
    return None


def _apply_action(hand: ParsedHand, action: ParsedAction, contributions: dict[str, Decimal]) -> None:
    player = _player(hand, action.actor)
    if not player:
        return
    player.is_all_in = player.is_all_in or action.all_in
    if action.action_type in {"post_small_blind", "post_big_blind", "post_ante", "call", "bet"} and action.amount is not None:
        player.invested += action.amount
        contributions[action.actor] = contributions.get(action.actor, Decimal("0")) + action.amount
    elif action.action_type == "raise":
        previous = contributions.get(action.actor, Decimal("0"))
        paid = (action.to_amount - previous) if action.to_amount is not None else action.amount
        if paid is not None and paid >= 0:
            player.invested += paid
            contributions[action.actor] = previous + paid
    elif action.action_type == "show":
        player.showed = True
        player.hole_cards = action.cards
    elif action.action_type == "collect" and action.amount is not None:
        player.won += action.amount
        hand.awards.append(PotAward(action.actor, action.amount, action.pot_name or "pot"))


def _apply_summary_seat(hand: ParsedHand, line: str) -> None:
    # Collection lines are authoritative. Summary amounts are only a fallback.
    for player in sorted(hand.players, key=lambda item: len(item.name), reverse=True):
        if not re.match(rf"^Seat\s+\d+\s*:\s*{re.escape(player.name)}(?:\s|$)", line, re.IGNORECASE):
            continue
        if re.search(r"\bshowed\b|\bmontr[ée]\b", line, re.IGNORECASE):
            player.showed = True
            cards = _cards(line)
            if cards:
                player.hole_cards = cards[:2]
        won_match = re.search(r"\b(?:won|gagn[ée])\s+([\d\s.,]+)", line, re.IGNORECASE)
        if won_match and player.won == 0:
            amount = _parse_decimal(won_match.group(1)) or Decimal("0")
            player.won = amount
            hand.awards.append(PotAward(player.name, amount))
        return


def _assign_positions_and_end_stacks(hand: ParsedHand) -> None:
    for player in hand.players:
        player.is_button = hand.button_seat == player.seat
    for action in hand.actions:
        player = _player(hand, action.actor)
        if not player:
            continue
        if action.action_type == "post_small_blind":
            player.position = "SB"
        elif action.action_type == "post_big_blind":
            player.position = "BB"
    if len(hand.players) >= 3:
        button = next((player for player in hand.players if player.is_button), None)
        if button and not button.position:
            button.position = "BTN"
    elif len(hand.players) == 2:
        button = next((player for player in hand.players if player.is_button), None)
        if button and not button.position:
            button.position = "SB"
    for player in hand.players:
        player.ending_stack = player.starting_stack - player.invested + player.won


def _parse_section(line: str) -> tuple[str, list[str]] | None:
    match = re.match(r"^\*\*\*\s*(.*?)\s*\*\*\*(.*)$", line)
    if not match:
        return None
    label = re.sub(r"\s+", " ", match.group(1).strip()).upper()
    street = SECTION_NAMES.get(label)
    if street is None:
        return None
    return street, _cards(match.group(2))


def _actor_and_body(line: str, names: list[str]) -> tuple[str | None, str]:
    for name in sorted(names, key=len, reverse=True):
        if line.casefold().startswith((name + " ").casefold()):
            return name, line[len(name) :].strip()
    return None, line


def _player(hand: ParsedHand, name: str) -> ParsedPlayer | None:
    key = name.casefold()
    return next((player for player in hand.players if player.name.casefold() == key), None)


def _parse_buyin(value: str) -> tuple[Decimal | None, Decimal | None, str | None]:
    currency = _currency(value)
    numbers = re.findall(r"[-+]?\d[\d\s]*(?:[.,]\d+)?", value.replace("\u00a0", " "))
    parsed = [_parse_decimal(number) for number in numbers]
    amounts = [amount for amount in parsed if amount is not None]
    return (
        amounts[0] if amounts else None,
        amounts[1] if len(amounts) > 1 else Decimal("0") if amounts else None,
        currency,
    )


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d[\d\s]*(?:[.,]\d+)?", value.replace("\u00a0", " "))
    if not match:
        return None
    token = re.sub(r"\s+", "", match.group(0))
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        before, after = token.rsplit(",", 1)
        token = before + after if len(after) == 3 else before + "." + after
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _parse_datetime(value: str) -> datetime | None:
    cleaned = value.strip()
    cleaned = re.sub(r"\s+(?:UTC|GMT)$", "", cleaned, flags=re.IGNORECASE)
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or UTC)
    except ValueError:
        return None


def _parse_duration(value: str) -> int | None:
    hours = re.search(r"(\d+)\s*(?:h|hour|hours|heure|heures)\b", value, re.IGNORECASE)
    minutes = re.search(r"(\d+)\s*(?:m|min|mins|minute|minutes)\b", value, re.IGNORECASE)
    seconds = re.search(r"(\d+)\s*(?:s|sec|secs|second|seconds|seconde|secondes)\b", value, re.IGNORECASE)
    if not any((hours, minutes, seconds)):
        return None
    return (int(hours.group(1)) if hours else 0) * 3600 + (int(minutes.group(1)) if minutes else 0) * 60 + (int(seconds.group(1)) if seconds else 0)


def _first_int(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _currency(value: str) -> str | None:
    if "€" in value or re.search(r"\bEUR\b", value, re.IGNORECASE):
        return "EUR"
    if "$" in value or re.search(r"\bUSD\b", value, re.IGNORECASE):
        return "USD"
    if "£" in value or re.search(r"\bGBP\b", value, re.IGNORECASE):
        return "GBP"
    return None


def _cards(value: str) -> list[str]:
    return [card[0].upper() + card[1].lower() for card in CARD_RE.findall(value)]


def _normalize_label(value: str) -> str:
    replacements = str.maketrans("éèêëàâäîïôöùûüç’", "eeeeaaaiioouuuc'")
    return re.sub(r"\s+", " ", value.casefold().translate(replacements)).strip()


def _safe_excerpt(line: str, hero_name: str | None, names: list[str] | tuple[str, ...]) -> str:
    sanitized = sanitize_log_line(line, hero_name, names)
    sanitized = re.sub(r"\[[^]]*]", "[CARDS]", sanitized)
    sanitized = re.sub(r"^(Seat\s+\d+\s*:\s*)(.+?)(\s+\()", r"\1PLAYER\3", sanitized, flags=re.IGNORECASE)
    action_words = r"posts|folds|checks|calls|bets|raises|shows|mucks|collected|se couche|parole|suit|mise|relance|montre|remporte"
    sanitized = re.sub(rf"^(.+?)\s+({action_words})\b", rf"PLAYER \2", sanitized, flags=re.IGNORECASE)
    return sanitized[:500]


def _issue(
    code: str,
    message: str,
    line_number: int | None,
    line: str,
    hero_name: str | None,
    names: list[str] | tuple[str, ...],
) -> ParseIssue:
    return ParseIssue(code, message, line_number, _safe_excerpt(line, hero_name, names))
