import type {
  ActionResult,
  ApiPage,
  AppSettings,
  BreakdownRow,
  CommunityContributor,
  CommunityContributorProfile,
  CommunityDashboard,
  CommunityHand,
  CommunityJoinInput,
  CommunityLeaveResult,
  CommunityStatus,
  CommunityTournament,
  ContributionPreview,
  DashboardData,
  HandSummary,
  HealthStatus,
  HeroStats,
  ImportStatus,
  LeakFlag,
  ListFilters,
  PlayerSeat,
  ReplayAction,
  ReplayData,
  Session,
  ThemeMode,
  TimePoint,
  Tournament
} from "../types";

const API_ROOT = "/api";
type JsonRecord = Record<string, any>;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function queryString(filters?: ListFilters): string {
  if (!filters) return "";
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers
    }
  });

  if (!response.ok) {
    let details: unknown;
    try {
      details = await response.json();
    } catch {
      details = await response.text();
    }
    const message =
      typeof details === "object" && details && "detail" in details
        ? String((details as { detail: unknown }).detail)
        : `Requête impossible (${response.status})`;
    throw new ApiError(message, response.status, details);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function number(value: unknown, fallback = 0): number {
  const result = typeof value === "number" ? value : Number(value);
  return Number.isFinite(result) ? result : fallback;
}

function nullableNumber(value: unknown): number | null {
  if (value === undefined || value === null || value === "") return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function string(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : value === undefined || value === null ? fallback : String(value);
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => string(item)).filter(Boolean);
  if (typeof value !== "string" || !value.trim()) return [];
  return value.split(/[,;]+/).map((item) => item.trim()).filter(Boolean);
}

function splitCards(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((card) => string(card)).filter(Boolean);
  if (typeof value !== "string") return [];
  const cards = value.match(/(?:10|[2-9TJQKA])(?:[shdc]|[♠♥♦♣])/gi);
  if (cards?.length) return cards.map((card) => card.replace(/^10/i, "T"));
  return value.trim() ? value.trim().split(/\s+/) : [];
}

function booleanFilter(value: unknown): boolean | undefined {
  if (value === true || value === "true") return true;
  if (value === false || value === "false") return false;
  return undefined;
}

function normalizePage<T>(payload: JsonRecord | T[], items: T[], page: number, pageSize: number): ApiPage<T> {
  return {
    items,
    total: Array.isArray(payload) ? payload.length : number(payload.total, items.length),
    page,
    page_size: pageSize
  };
}

function normalizeTournament(raw: JsonRecord): Tournament {
  const playerDetails: JsonRecord[] = Array.isArray(raw.players_detail) ? raw.players_detail : Array.isArray(raw.players) ? raw.players : [];
  const handDetails: JsonRecord[] = Array.isArray(raw.hands_detail) ? raw.hands_detail : Array.isArray(raw.hands) ? raw.hands : [];
  return {
    id: raw.id ?? raw.tournament_id ?? raw.external_id,
    tournament_id: string(raw.tournament_id ?? raw.external_id) || undefined,
    started_at: string(raw.started_at ?? raw.date),
    ended_at: string(raw.ended_at) || null,
    buy_in: number(raw.buy_in ?? raw.buyin),
    currency: string(raw.currency, "EUR"),
    multiplier: nullableNumber(raw.multiplier),
    prize_pool: number(raw.prize_pool),
    rank: nullableNumber(raw.rank ?? raw.final_rank),
    reward: number(raw.reward ?? raw.gain),
    net_result: number(raw.net_result ?? raw.net),
    duration_minutes: raw.duration_minutes !== undefined ? nullableNumber(raw.duration_minutes) : nullableNumber(number(raw.duration_seconds ?? raw.duration) / 60),
    hands_count: number(raw.hands_count ?? raw.hand_count ?? (typeof raw.hands === "number" ? raw.hands : handDetails.length)),
    chipev: nullableNumber(raw.chipev ?? raw.chip_ev),
    tags: stringList(raw.tags),
    analysis_status: (() => {
      const value = string(raw.analysis_status).toLowerCase();
      if (value.includes("analys")) return "complete";
      if (value.includes("import")) return "imported";
      return value;
    })(),
    format: string(raw.format, "Expresso"),
    player_count: number(raw.player_count ?? (typeof raw.players === "number" ? raw.players : playerDetails.length)),
    initial_stack: nullableNumber(raw.initial_stack) ?? undefined,
    ticket_won: string(raw.ticket_won ?? raw.ticket) || null,
    players: playerDetails.map((player, index): PlayerSeat => ({
      id: player.id ?? player.seat ?? index,
      name: string(player.name, `Joueur ${index + 1}`),
      position: string(player.position) || undefined,
      starting_stack: nullableNumber(player.starting_stack ?? player.stack) ?? undefined,
      finishing_place: nullableNumber(player.finishing_place ?? player.rank),
      reward: number(player.reward),
      is_hero: Boolean(player.is_hero)
    })),
    hands: handDetails.map((hand) => normalizeHand(hand))
  };
}

function normalizeHand(raw: JsonRecord): HandSummary {
  const bigBlind = number(raw.big_blind);
  const pot = nullableNumber(raw.pot);
  const analysis = raw.analysis && typeof raw.analysis === "object" ? raw.analysis as JsonRecord : {};
  return {
    id: raw.id ?? raw.hand_id ?? raw.external_id,
    hand_id: string(raw.hand_id ?? raw.external_id) || undefined,
    tournament_id: raw.tournament_id,
    played_at: string(raw.played_at ?? raw.date),
    hero_cards: splitCards(raw.hero_cards ?? raw.cards),
    board: splitCards(raw.board),
    position: string(raw.position) || undefined,
    players_count: number(raw.players_count ?? raw.players) || undefined,
    effective_stack_bb: nullableNumber(raw.effective_stack_bb ?? raw.stack_bb),
    blinds: raw.small_blind !== undefined || raw.big_blind !== undefined ? `${number(raw.small_blind)}/${bigBlind}` : undefined,
    preflop_action: string(raw.preflop_action) || undefined,
    postflop_action: string(raw.postflop_action) || undefined,
    is_all_in: Boolean(raw.is_all_in ?? raw.all_in),
    showdown: Boolean(raw.showdown),
    pot_bb: nullableNumber(raw.pot_bb) ?? (pot !== null && bigBlind ? Math.round((pot / bigBlind) * 10) / 10 : null),
    net_result_chips: number(raw.net_result_chips ?? raw.net),
    leak_count: number(raw.leak_count, raw.leak_detected ? 1 : 0),
    leaks: stringList(raw.leaks),
    classification: string(raw.classification ?? analysis.classification) || undefined,
    notes: string(raw.notes) || null,
    tags: stringList(raw.tags)
  };
}

function normalizeTimePoints(values: unknown, cumulativeKey = "net"): TimePoint[] {
  if (!Array.isArray(values)) return [];
  let running = 0;
  return values.map((rawValue, index) => {
    const raw = rawValue as JsonRecord;
    const periodNet = number(raw.result ?? raw.net_result ?? raw.net);
    running += periodNet;
    return {
      date: string(raw.date ?? raw.period ?? index + 1),
      label: string(raw.label ?? raw.period ?? raw.index ?? raw.date ?? index + 1),
      net: periodNet,
      cumulative: number(raw.cumulative ?? raw[cumulativeKey], running),
      ev: nullableNumber(raw.ev),
      tournaments: number(raw.tournaments ?? raw.games)
    };
  });
}

function normalizeBreakdown(values: unknown): BreakdownRow[] {
  if (!Array.isArray(values)) return [];
  return values.map((value) => {
    const raw = value as JsonRecord;
    return {
      label: string(raw.label),
      tournaments: number(raw.tournaments ?? raw.games),
      net_result: number(raw.net_result ?? raw.net),
      roi: number(raw.roi ?? raw.roi_percent),
      itm: number(raw.itm ?? raw.itm_percent),
      win_rate: number(raw.win_rate ?? raw.win_rate_percent)
    };
  });
}

function normalizeDashboard(raw: JsonRecord): DashboardData {
  const summary = raw.summary && typeof raw.summary === "object" ? raw.summary as JsonRecord : raw;
  const expresso = raw.expresso && typeof raw.expresso === "object" ? raw.expresso as JsonRecord : {};
  const grouped = raw.grouped_results && typeof raw.grouped_results === "object" ? raw.grouped_results as JsonRecord : {};
  const byLimit = normalizeBreakdown(expresso.by_limit ?? raw.by_limit);
  const byMultiplier = normalizeBreakdown(expresso.by_multiplier ?? raw.by_multiplier);
  const normalizeHeroStats = (value: unknown): HeroStats | undefined => {
    if (!value || typeof value !== "object") return undefined;
    const stats = value as JsonRecord;
    const metrics: HeroStats["metrics"] = {};
    Object.entries(stats.metrics ?? {}).forEach(([key, metricValue]) => {
      const metric = metricValue as JsonRecord;
      metrics[key] = { value: nullableNumber(metric.value), numerator: number(metric.numerator), denominator: number(metric.denominator) };
    });
    const normalizeSlices = (slices: unknown): Record<string, HeroStats> | undefined => {
      if (!slices || typeof slices !== "object") return undefined;
      return Object.fromEntries(Object.entries(slices as JsonRecord).map(([key, slice]) => [key, normalizeHeroStats(slice)!]));
    };
    return {
      hands: number(stats.hands),
      metrics,
      by_position: normalizeSlices(stats.by_position),
      by_depth: normalizeSlices(stats.by_depth),
      by_players: normalizeSlices(stats.by_players)
    };
  };
  return {
    tournaments_count: number(summary.tournaments_count ?? summary.tournaments ?? summary.games),
    hands_count: number(summary.hands_count ?? summary.hands),
    total_buy_ins: number(summary.total_buy_ins ?? summary.total_buyins),
    total_winnings: number(summary.total_winnings),
    net_result: number(summary.net_result ?? summary.net),
    roi: number(summary.roi),
    win_rate: number(summary.win_rate),
    second_place_rate: number(summary.second_place_rate),
    third_place_rate: number(summary.third_place_rate),
    itm: number(summary.itm),
    average_profit: number(summary.average_profit ?? summary.average_gain),
    hourly_profit: number(summary.hourly_profit ?? summary.hourly_gain),
    average_duration_minutes: summary.average_duration_minutes !== undefined ? number(summary.average_duration_minutes) : number(summary.average_duration_seconds) / 60,
    average_hands: number(summary.average_hands),
    average_buy_in: number(summary.average_buy_in ?? summary.average_buyin),
    biggest_win: number(summary.biggest_win),
    biggest_downswing: number(summary.biggest_downswing ?? summary.max_downswing),
    chipev_per_game: nullableNumber(summary.chipev_per_game),
    profit_series: normalizeTimePoints(raw.bankroll ?? raw.profit_curve, "net"),
    daily_results: normalizeTimePoints(grouped.day ?? raw.daily, "net"),
    weekly_results: normalizeTimePoints(grouped.week ?? raw.weekly, "net"),
    monthly_results: normalizeTimePoints(grouped.month ?? raw.monthly, "net"),
    by_limit: byLimit,
    by_multiplier: byMultiplier,
    multiplier_distribution: byMultiplier.map((row) => ({ label: row.label, count: row.tournaments })),
    hero_stats: normalizeHeroStats(raw.hero_stats),
    expresso_stats: {
      average_multiplier: nullableNumber(expresso.average_multiplier),
      heads_up_win_rate: nullableNumber(expresso.heads_up_win_rate),
      three_handed_win_rate: nullableNumber(expresso.three_handed_win_rate),
      first_elimination_rate: nullableNumber(expresso.first_elimination_rate),
      average_elimination_minutes: nullableNumber(expresso.average_elimination_seconds) === null ? null : number(expresso.average_elimination_seconds) / 60,
      comeback_under_10bb_rate: nullableNumber(expresso.comeback_under_10bb_rate),
      comeback_note: string(expresso.comeback_note)
    }
  };
}

function normalizeSession(raw: JsonRecord): Session {
  return {
    id: raw.id,
    started_at: string(raw.started_at ?? raw.start),
    ended_at: string(raw.ended_at ?? raw.end),
    duration_minutes: raw.duration_minutes !== undefined ? number(raw.duration_minutes) : number(raw.duration_seconds) / 60,
    tournaments_count: number(raw.tournaments_count ?? raw.games),
    net_result: number(raw.net_result ?? raw.net),
    roi: number(raw.roi),
    best_tournament: nullableNumber(raw.best_tournament ?? raw.best_game) ?? undefined,
    worst_tournament: nullableNumber(raw.worst_tournament ?? raw.worst_game) ?? undefined,
    evolution: normalizeTimePoints(raw.evolution ?? raw.curve, "net")
  };
}

function normalizeLeak(raw: JsonRecord): LeakFlag {
  const severityRaw = string(raw.severity).toLowerCase();
  const severity = severityRaw.includes("lev") ? "high" : severityRaw.includes("mod") ? "medium" : severityRaw.includes("faib") ? "low" : severityRaw || "info";
  const confidenceValue = number(raw.confidence);
  return {
    id: raw.id ?? raw.name,
    name: string(raw.name),
    severity,
    observed_value: number(raw.observed_value ?? raw.observed),
    threshold: number(raw.threshold),
    unit: string(raw.unit, "%"),
    occurrences: number(raw.occurrences),
    sample_size: number(raw.sample_size),
    hand_ids: Array.isArray(raw.hand_ids ?? raw.hands) ? (raw.hand_ids ?? raw.hands) : [],
    explanation: string(raw.explanation),
    recommendation: string(raw.recommendation),
    confidence: confidenceValue <= 1 ? confidenceValue * 100 : confidenceValue,
    category: string(raw.category, "Analyse"),
    active: raw.active === undefined ? true : Boolean(raw.active)
  };
}

function normalizeSettings(raw: JsonRecord): AppSettings {
  return {
    history_paths: stringList(raw.history_paths),
    hero_name: string(raw.hero_name),
    import_delay_seconds: number(raw.import_delay_seconds ?? raw.stable_delay_seconds, 10),
    currency: string(raw.currency, "EUR"),
    session_gap_minutes: number(raw.session_gap_minutes, 30),
    leak_thresholds: raw.leak_thresholds && typeof raw.leak_thresholds === "object" ? raw.leak_thresholds : {},
    autostart: Boolean(raw.autostart ?? raw.auto_start),
    theme: (["dark", "light", "system"].includes(raw.theme) ? raw.theme : "dark") as ThemeMode,
    anonymize_exports: raw.anonymize_exports !== false,
    ai_analysis_enabled: Boolean(raw.ai_analysis_enabled ?? raw.ai_enabled)
  };
}

function settingsPayload(settings: AppSettings): JsonRecord {
  return {
    history_paths: settings.history_paths,
    hero_name: settings.hero_name,
    stable_delay_seconds: settings.import_delay_seconds,
    currency: settings.currency,
    session_gap_minutes: settings.session_gap_minutes,
    leak_thresholds: settings.leak_thresholds,
    auto_start: settings.autostart,
    theme: settings.theme,
    anonymize_exports: settings.anonymize_exports,
    ai_enabled: settings.ai_analysis_enabled ?? false
  };
}

function normalizeImportStatus(raw: JsonRecord): ImportStatus {
  const states = raw.states && typeof raw.states === "object" ? raw.states as JsonRecord : {};
  const guard = raw.active_guard && typeof raw.active_guard === "object" ? raw.active_guard as JsonRecord : {};
  const active = Boolean(guard.active ?? guard.potentially_active ?? raw.tournament_active);
  return {
    watching: Boolean(raw.watcher_running ?? raw.watching),
    configured_paths: stringList(raw.history_paths ?? raw.configured_paths),
    last_import_at: string(raw.last_import_at ?? raw.last_import) || null,
    active_files: active ? Math.max(1, number(guard.reason_count)) : number(raw.active_files),
    pending_files: number(raw.pending_files, number(states.detected) + number(states.waiting_for_completion)),
    failed_files: number(raw.failed_files ?? states.failed),
    imported_files: number(raw.imported_files ?? states.imported),
    tournament_active: active,
    safe_to_analyze: !active,
    latest_state: raw.latest_state,
    message: string(raw.message ?? guard.policy)
  };
}

function normalizeReplay(raw: JsonRecord, anonymizeOpponents = false): ReplayData {
  const players: JsonRecord[] = Array.isArray(raw.players) ? raw.players : [];
  const actions: JsonRecord[] = Array.isArray(raw.actions) ? raw.actions : [];
  const blinds = raw.blinds && typeof raw.blinds === "object" && !Array.isArray(raw.blinds) ? raw.blinds as JsonRecord : {};
  const result = raw.result && typeof raw.result === "object" ? raw.result as JsonRecord : {};
  const heroNet = nullableNumber(result.hero_net ?? raw.hero_net);
  const playerLabels = new Map<string, string>();
  let opponentIndex = 0;
  players.forEach((player) => {
    const rawName = string(player.name ?? player.alias, "Joueur");
    const isHero = Boolean(player.is_hero) || rawName.toUpperCase() === "HERO";
    if (!isHero) opponentIndex += 1;
    playerLabels.set(rawName, isHero ? "Héros" : `Adversaire ${opponentIndex}`);
  });
  const publicPlayerName = (value: unknown, isHero = false) => {
    const rawName = string(value, "Joueur");
    if (!anonymizeOpponents) return rawName;
    if (isHero || rawName.toUpperCase() === "HERO") return "Héros";
    return playerLabels.get(rawName) ?? "Adversaire";
  };
  const redactPlayerNames = (value: unknown) => {
    let output = string(value);
    if (!anonymizeOpponents) return output;
    [...playerLabels.entries()]
      .sort(([left], [right]) => right.length - left.length)
      .forEach(([rawName, label]) => {
        if (rawName) output = output.split(rawName).join(label);
      });
    return output;
  };
  return {
    hand: {
      id: raw.id ?? raw.public_id ?? raw.hand_id ?? raw.hand_number,
      hand_id: string(raw.hand_id ?? raw.hand_number),
      tournament_id: raw.tournament_id,
      played_at: string(raw.played_at),
      notes: anonymizeOpponents ? null : string(raw.notes) || null,
      tags: anonymizeOpponents ? [] : stringList(raw.tags)
    },
    seats: players.map((player, index) => ({
      id: player.seat ?? index,
      name: publicPlayerName(player.name ?? player.alias ?? `Joueur ${index + 1}`, Boolean(player.is_hero)),
      position: string(player.position) || undefined,
      starting_stack: number(player.starting_stack ?? player.stack),
      is_hero: Boolean(player.is_hero) || string(player.name ?? player.alias).toUpperCase() === "HERO"
    })),
    actions: actions.map((action, index): ReplayAction => {
      const actor = action.player_name ?? action.actor ?? action.actor_alias;
      const isHero = Boolean(action.is_hero) || string(actor).toUpperCase() === "HERO" || playerLabels.get(string(actor)) === "Héros";
      return {
        id: action.id ?? action.sequence ?? index,
        order: number(action.order ?? action.step ?? action.sequence, index + 1),
        street: string(action.street, "preflop").toLowerCase(),
        player_name: publicPlayerName(actor, isHero),
        position: string(action.position) || undefined,
        action: redactPlayerNames(action.action ?? action.type ?? action.action_type),
        amount: nullableNumber(action.amount ?? action.to_amount),
        amount_bb: nullableNumber(action.amount_bb),
        pot_after: nullableNumber(action.pot_after),
        stack_after: nullableNumber(action.stack_after),
        is_hero: isHero
      };
    }),
    hero_cards: splitCards(raw.hero_cards),
    board: splitCards(raw.board),
    initial_pot: number(raw.initial_pot),
    final_pot: number(raw.final_pot ?? raw.pot ?? raw.total_pot),
    small_blind: number(blinds.small ?? raw.small_blind ?? (Array.isArray(raw.blinds) ? raw.blinds[0] : 0)),
    big_blind: number(blinds.big ?? raw.big_blind ?? (Array.isArray(raw.blinds) ? raw.blinds[1] : 0)),
    ante: number(blinds.ante ?? raw.ante ?? (Array.isArray(raw.blinds) ? raw.blinds[2] : 0)),
    winner: string(raw.winner) ? publicPlayerName(raw.winner, playerLabels.get(string(raw.winner)) === "Héros") : undefined,
    result: typeof raw.result === "string" ? redactPlayerNames(raw.result) : heroNet === null ? "Résultat non renseigné" : `Résultat du héros : ${heroNet >= 0 ? "+" : ""}${heroNet} jetons`,
    equity: raw.equity ?? null,
    safe_to_replay: true,
    tournament_finished: true
  };
}

function communityPayload(raw: unknown): unknown {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return raw;
  const record = raw as JsonRecord;
  return record.data ?? record.payload ?? record.result ?? raw;
}

function communityRecord(raw: unknown): JsonRecord {
  const payload = communityPayload(raw);
  return payload && typeof payload === "object" && !Array.isArray(payload) ? payload as JsonRecord : {};
}

function communityItems(raw: unknown): JsonRecord[] {
  const payload = communityPayload(raw);
  if (Array.isArray(payload)) return payload as JsonRecord[];
  if (!payload || typeof payload !== "object") return [];
  const record = payload as JsonRecord;
  const values = record.items ?? record.contributors ?? record.tournaments ?? record.hands;
  return Array.isArray(values) ? values as JsonRecord[] : [];
}

function normalizeCommunityStatus(raw: unknown): CommunityStatus {
  const payload = communityRecord(raw);
  const member = payload.member && typeof payload.member === "object" ? payload.member as JsonRecord : null;
  const sync = payload.sync && typeof payload.sync === "object" ? payload.sync as JsonRecord : {};
  const available = Boolean(payload.available ?? sync.available ?? payload.configured);
  const onlineValue = payload.online ?? sync.online;
  const online = onlineValue === undefined || onlineValue === null ? null : Boolean(onlineValue);
  const pending = number(sync.pending_tournaments ?? sync.pending ?? payload.pending);
  const blockedReason = string(payload.blocked_reason ?? sync.blocked_reason ?? sync.last_error) || null;
  const state = blockedReason || !available
    ? "blocked"
    : online === false
      ? "failed"
      : pending > 0
        ? "pending"
        : "synced";
  return {
    configured: Boolean(payload.configured ?? member),
    available,
    online,
    member: member
      ? {
          contributor_id: string(member.contributor_id ?? member.id),
          display_name: string(member.display_name ?? member.name, "Membre"),
          joined_at: string(member.joined_at) || null
        }
      : null,
    sync: {
      state: string(sync.state, state),
      mandatory: sync.mandatory === undefined ? true : Boolean(sync.mandatory),
      pending_tournaments: pending,
      last_success_at: string(sync.last_success_at ?? sync.last_sync_at ?? payload.last_sync_at) || null,
      last_error: string(sync.last_error ?? blockedReason) || null
    },
    synced_tournaments: number(payload.synced ?? sync.synced),
    blocked_reason: blockedReason
  };
}

function normalizeCommunityContributor(raw: JsonRecord): CommunityContributor {
  return {
    id: string(raw.contributor_id ?? raw.public_id ?? raw.id),
    display_name: string(raw.display_name ?? raw.name, "Contributeur"),
    tournaments_count: number(raw.tournaments_count ?? raw.tournament_count ?? raw.tournaments),
    hands_count: number(raw.hands_count ?? raw.hand_count ?? raw.hands),
    last_sync_at: string(raw.last_sync_at ?? raw.last_seen_at) || null,
    is_self: Boolean(raw.is_self ?? raw.self)
  };
}

function normalizeCommunityTournament(raw: JsonRecord): CommunityTournament {
  const contributor = raw.contributor && typeof raw.contributor === "object" ? raw.contributor as JsonRecord : {};
  return {
    ...normalizeTournament({
      ...raw,
      id: raw.id ?? raw.public_id,
      buy_in: raw.buy_in ?? raw.total_buyin,
      hands_count: raw.hands_count ?? raw.total_hands,
      player_count: raw.player_count ?? raw.registered_players,
      chipev: raw.chipev ?? raw.chip_delta
    }),
    players: undefined,
    contributor_id: string(raw.contributor_id ?? contributor.id),
    contributor_display_name: string(raw.contributor_display_name ?? raw.display_name ?? contributor.display_name ?? contributor.name, "Contributeur")
  };
}

function normalizeCommunityHand(raw: JsonRecord): CommunityHand {
  const contributor = raw.contributor && typeof raw.contributor === "object" ? raw.contributor as JsonRecord : {};
  return {
    ...normalizeHand({
      ...raw,
      id: raw.id ?? raw.public_id,
      hand_id: raw.hand_id ?? raw.hand_number,
      position: raw.position ?? raw.hero_position,
      players_count: raw.players_count ?? raw.active_players,
      pot: raw.pot ?? raw.total_pot,
      net_result_chips: raw.net_result_chips ?? raw.hero_net,
      showdown: raw.showdown ?? raw.reached_showdown
    }),
    contributor_id: string(raw.contributor_id ?? contributor.id),
    contributor_display_name: string(raw.contributor_display_name ?? raw.display_name ?? contributor.display_name ?? contributor.name, "Contributeur"),
    replay_key: string(raw.replay_key ?? raw.hand_key ?? raw.public_id) || undefined
  };
}

function normalizeCommunityProfileBreakdown(
  raw: JsonRecord,
  kind: "currency" | "limit" | "multiplier",
  index: number
): CommunityContributorProfile["by_limit"][number] {
  const currency = string(raw.currency, "EUR").toUpperCase();
  const rawValue = kind === "limit"
    ? raw.buyin ?? raw.buy_in ?? raw.total_buyin
    : kind === "multiplier" ? raw.multiplier : currency;
  const fallbackLabel = rawValue === undefined || rawValue === null
    ? `${kind === "limit" ? "Limite" : "Multiplicateur"} ${index + 1}`
    : kind === "currency"
      ? currency
      : kind === "limit" ? `${number(rawValue)} ${currency}` : `×${number(rawValue)} · ${currency}`;
  return {
    label: string(raw.label, fallbackLabel),
    currency,
    buyin: nullableNumber(raw.buyin ?? raw.buy_in ?? raw.total_buyin),
    multiplier: nullableNumber(raw.multiplier),
    games: number(raw.games ?? raw.tournaments_count ?? raw.tournaments),
    hands: number(raw.hands ?? raw.hands_count),
    total_buyins: number(raw.total_buyins ?? raw.total_buy_ins ?? raw.total_buyin),
    total_winnings: number(raw.total_winnings ?? raw.winnings ?? raw.total_reward),
    net_result: number(raw.net_result ?? raw.net),
    roi_percent: number(raw.roi_percent ?? raw.roi),
    wins: number(raw.wins ?? raw.first_places),
    win_rate_percent: number(raw.win_rate_percent ?? raw.win_rate),
    itm_count: number(raw.itm_count),
    itm_percent: number(raw.itm_percent ?? raw.itm),
    average_net: number(raw.average_net ?? raw.average_gain),
    chip_ev_per_game: nullableNumber(raw.chip_ev_per_game ?? raw.chipev_per_game),
    chip_ev_games: number(raw.chip_ev_games ?? raw.chipev_games),
    chip_ev_coverage_percent: number(raw.chip_ev_coverage_percent ?? raw.chipev_coverage)
  };
}

function normalizeCommunityContributorProfile(raw: unknown): CommunityContributorProfile {
  const payload = communityRecord(raw);
  const contributor = payload.contributor && typeof payload.contributor === "object"
    ? payload.contributor as JsonRecord
    : {};
  const summary = payload.summary && typeof payload.summary === "object"
    ? payload.summary as JsonRecord
    : {};
  const publicId = string(contributor.public_id ?? contributor.id);
  const displayName = string(contributor.display_name ?? contributor.name, "Contributeur");
  const byCurrency = Array.isArray(payload.by_currency) ? payload.by_currency as JsonRecord[] : [];
  const byLimit = Array.isArray(payload.by_limit) ? payload.by_limit as JsonRecord[] : [];
  const byMultiplier = Array.isArray(payload.by_multiplier) ? payload.by_multiplier as JsonRecord[] : [];
  const trend = Array.isArray(payload.trend) ? payload.trend as JsonRecord[] : [];
  const recent = Array.isArray(payload.recent_tournaments)
    ? payload.recent_tournaments as JsonRecord[]
    : [];
  return {
    contributor: {
      public_id: publicId,
      display_name: displayName,
      joined_at: string(contributor.joined_at) || null
    },
    summary: {
      games: number(summary.games ?? summary.tournaments_count),
      hands: number(summary.hands ?? summary.hands_count),
      currency: string(summary.currency).toUpperCase() || null,
      total_buyins: nullableNumber(summary.total_buyins ?? summary.total_buy_ins),
      total_winnings: nullableNumber(summary.total_winnings ?? summary.winnings),
      net_result: nullableNumber(summary.net_result ?? summary.net),
      roi_percent: nullableNumber(summary.roi_percent ?? summary.roi),
      wins: number(summary.wins ?? summary.first_places),
      second_places: number(summary.second_places),
      third_places: number(summary.third_places),
      win_rate_percent: number(summary.win_rate_percent ?? summary.win_rate),
      second_place_percent: number(summary.second_place_percent ?? summary.second_place_rate),
      third_place_percent: number(summary.third_place_percent ?? summary.third_place_rate),
      itm_count: number(summary.itm_count),
      itm_percent: number(summary.itm_percent ?? summary.itm),
      average_buyin: nullableNumber(summary.average_buyin ?? summary.average_buy_in),
      average_winnings: nullableNumber(summary.average_winnings),
      average_net: nullableNumber(summary.average_net ?? summary.average_gain),
      average_duration_seconds: number(summary.average_duration_seconds),
      average_hands: number(summary.average_hands),
      chip_ev_per_game: nullableNumber(summary.chip_ev_per_game ?? summary.chipev_per_game),
      chip_ev_games: number(summary.chip_ev_games ?? summary.chipev_games),
      chip_ev_coverage_percent: number(summary.chip_ev_coverage_percent ?? summary.chipev_coverage),
      first_game_at: string(summary.first_game_at) || null,
      last_game_at: string(summary.last_game_at) || null
    },
    by_currency: byCurrency.map((row, index) => normalizeCommunityProfileBreakdown(row, "currency", index)),
    by_limit: byLimit.map((row, index) => normalizeCommunityProfileBreakdown(row, "limit", index)),
    by_multiplier: byMultiplier.map((row, index) => normalizeCommunityProfileBreakdown(row, "multiplier", index)),
    trend: trend.map((row) => ({
      date: string(row.date ?? row.label),
      currency: string(row.currency, "EUR").toUpperCase(),
      games: number(row.games),
      total_buyins: number(row.total_buyins ?? row.total_buy_ins),
      total_winnings: number(row.total_winnings),
      net_result: number(row.net_result ?? row.net),
      cumulative_net: number(row.cumulative_net ?? row.cumulative)
    })),
    recent_tournaments: recent.map((row) => ({
      ...normalizeCommunityTournament(row),
      contributor_id: string(row.contributor_id, publicId),
      contributor_display_name: string(row.contributor_display_name, displayName)
    }))
  };
}

function pagination(filters?: ListFilters, fallback = 25): { page: number; pageSize: number; offset: number } {
  const page = Math.max(1, number(filters?.page, 1));
  const pageSize = Math.max(1, number(filters?.page_size, fallback));
  return { page, pageSize, offset: (page - 1) * pageSize };
}

export const api = {
  health: () => request<HealthStatus>("/health"),
  dashboard: async (filters?: ListFilters) => {
    const buyin = filters?.buy_in === "other" ? undefined : nullableNumber(filters?.buy_in);
    const raw = await request<JsonRecord>(`/dashboard${queryString({
      start: filters?.date_from,
      end: filters?.date_to,
      buyin,
      multiplier: filters?.multiplier,
      rank: filters?.rank,
      players: filters?.players,
      result: filters?.result
    })}`);
    return normalizeDashboard(raw);
  },
  tournaments: async (filters?: ListFilters) => {
    const { page, pageSize, offset } = pagination(filters);
    const buyin = filters?.buy_in === "other" ? undefined : nullableNumber(filters?.buy_in);
    const backendStatus = filters?.status === "complete" ? "analysé" : filters?.status === "imported" ? "importé" : filters?.status;
    const raw = await request<JsonRecord>(`/tournaments${queryString({
      start: filters?.date_from,
      end: filters?.date_to,
      buyin,
      multiplier: filters?.multiplier,
      rank: filters?.rank,
      players: filters?.players,
      result: filters?.result,
      search: filters?.search,
      analysis_status: backendStatus,
      limit: pageSize,
      offset
    })}`);
    let items: Tournament[] = (Array.isArray(raw) ? raw : raw.items ?? []).map((item: JsonRecord) => normalizeTournament(item));
    return normalizePage(raw, items, page, pageSize);
  },
  tournament: async (id: number | string) => normalizeTournament(await request<JsonRecord>(`/tournaments/${encodeURIComponent(id)}`)),
  hands: async (filters?: ListFilters) => {
    const { page, pageSize, offset } = pagination(filters, 30);
    const stackLimits: Record<string, number> = { "0-5": 5, "5-10": 10, "10-15": 15, "15-25": 25 };
    const result = string(filters?.result);
    const preflopMap: Record<string, string> = { limp: "call", open_raise: "raise", "3bet": "raise", shove: "raise" };
    const postflopMap: Record<string, string> = { cbet: "flop:bet", check_raise: "raise", hero_call_river: "river:call" };
    const preflop = string(filters?.preflop);
    const raw = await request<JsonRecord>(`/hands${queryString({
      cards: filters?.cards,
      position: filters?.position,
      max_stack_bb: stackLimits[string(filters?.stack)],
      all_in: booleanFilter(filters?.all_in),
      showdown: booleanFilter(filters?.showdown),
      min_pot_bb: filters?.min_pot_bb,
      lost: result === "lost" ? true : result === "won" ? false : undefined,
      leak: booleanFilter(filters?.leak),
      text: filters?.query,
      preflop_action: preflop === "call_shove" ? undefined : preflopMap[preflop] ?? preflop,
      postflop_action: postflopMap[string(filters?.postflop)] ?? filters?.postflop,
      call_shove: preflop === "call_shove" ? true : undefined,
      limit: pageSize,
      offset
    })}`);
    const items: HandSummary[] = (Array.isArray(raw) ? raw : raw.items ?? []).map((item: JsonRecord) => normalizeHand(item));
    return normalizePage(raw, items, page, pageSize);
  },
  hand: async (id: number | string) => normalizeHand(await request<JsonRecord>(`/hands/${encodeURIComponent(id)}`)),
  replay: async (id: number | string) => normalizeReplay(await request<JsonRecord>(`/hands/${encodeURIComponent(id)}/replay`)),
  updateHand: async (id: number | string, changes: Pick<HandSummary, "notes" | "tags">) =>
    normalizeHand(await request<JsonRecord>(`/hands/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(changes) })),
  sessions: async (_filters?: ListFilters) => {
    const raw = await request<JsonRecord>("/sessions");
    const items: Session[] = (raw.items ?? []).map((item: JsonRecord) => normalizeSession(item));
    return normalizePage(raw, items, 1, Math.max(1, items.length));
  },
  leaks: async (filters?: ListFilters) => {
    const raw = await request<JsonRecord>("/leaks");
    let items: LeakFlag[] = (raw.items ?? []).map((item: JsonRecord) => normalizeLeak(item));
    if (filters?.severity) items = items.filter((item: LeakFlag) => item.severity === filters.severity);
    if (filters?.category) items = items.filter((item: LeakFlag) => item.category?.toLowerCase() === string(filters.category).toLowerCase());
    return normalizePage(raw, items, 1, Math.max(1, items.length));
  },
  settings: async () => normalizeSettings(await request<JsonRecord>("/settings")),
  updateSettings: async (settings: AppSettings) => normalizeSettings(await request<JsonRecord>("/settings", { method: "PUT", body: JSON.stringify(settingsPayload(settings)) })),
  importStatus: async () => normalizeImportStatus(await request<JsonRecord>("/import/status")),
  rescan: () => request<ActionResult>("/import/rescan", { method: "POST" }),
  communityStatus: async () => normalizeCommunityStatus(await request<unknown>("/community/status")),
  communityJoin: (input: CommunityJoinInput) =>
    request<unknown>("/community/join", { method: "POST", body: JSON.stringify(input) }),
  communityLeave: () => request<CommunityLeaveResult>("/community/leave", { method: "DELETE" }),
  communitySync: () => request<ActionResult>("/community/sync", { method: "POST" }),
  communityContributors: async () =>
    communityItems(await request<unknown>("/community/contributors")).map(normalizeCommunityContributor),
  communityContributorProfile: async (publicId: string) =>
    normalizeCommunityContributorProfile(
      await request<unknown>(`/community/contributors/${encodeURIComponent(publicId)}/profile`)
    ),
  communityDashboard: async (filters?: ListFilters): Promise<CommunityDashboard> => {
    const raw = communityRecord(await request<unknown>(`/community/dashboard${queryString({ contributor_id: filters?.contributor_id })}`));
    const summary = raw.summary && typeof raw.summary === "object" ? raw.summary as JsonRecord : raw;
    return {
      tournaments_count: number(summary.tournaments_count ?? summary.tournaments ?? summary.games),
      hands_count: number(summary.hands_count ?? summary.hands),
      contributors_count: number(summary.contributors_count ?? summary.contributors),
      total_buy_ins: number(summary.total_buy_ins ?? summary.total_buyins ?? summary.total_buyin),
      total_winnings: number(summary.total_winnings ?? summary.winnings ?? summary.total_reward),
      net_result: number(summary.net_result ?? summary.net),
      roi: number(summary.roi ?? summary.roi_percent),
      itm: number(summary.itm ?? summary.itm_percent),
      win_rate: number(summary.win_rate ?? summary.win_rate_percent)
    };
  },
  communityTournaments: async (filters?: ListFilters): Promise<ApiPage<CommunityTournament>> => {
    const { page, pageSize, offset } = pagination(filters);
    const response = await request<unknown>(`/community/tournaments${queryString({
      contributor_id: filters?.contributor_id,
      limit: pageSize,
      offset
    })}`);
    const payload = communityRecord(response);
    const items = communityItems(response).map(normalizeCommunityTournament);
    return { items, total: number(payload.total, items.length), page, page_size: pageSize };
  },
  communityHands: async (filters?: ListFilters): Promise<ApiPage<CommunityHand>> => {
    const { page, pageSize, offset } = pagination(filters, 30);
    const response = await request<unknown>(`/community/hands${queryString({
      contributor_id: filters?.contributor_id,
      limit: pageSize,
      offset
    })}`);
    const payload = communityRecord(response);
    const items = communityItems(response).map(normalizeCommunityHand);
    return { items, total: number(payload.total, items.length), page, page_size: pageSize };
  },
  communityReplay: async (handKey: number | string, contributorId?: string) => {
    const response = await request<unknown>(`/community/replay/${encodeURIComponent(handKey)}${queryString({ contributor_id: contributorId })}`);
    const envelope = communityRecord(response);
    const replay = envelope.replay && typeof envelope.replay === "object" ? envelope.replay as JsonRecord : {};
    return normalizeReplay({
      ...envelope,
      ...replay,
      id: envelope.public_id ?? replay.id,
      hand_id: envelope.hand_number ?? replay.hand_id,
      tournament_id: envelope.tournament_id ?? replay.tournament_id,
      played_at: envelope.played_at ?? replay.played_at,
      hero_net: envelope.hero_net ?? replay.hero_net,
      total_pot: envelope.total_pot ?? replay.total_pot
    }, true);
  },
  contributionPreview: () => request<ContributionPreview>("/contributions/preview"),
  backupDatabase: () => request<ActionResult>("/database/backup", { method: "POST" }),
  listBackups: async () => {
    const raw = await request<JsonRecord>("/database/backups");
    return Array.isArray(raw.items) ? raw.items : [];
  },
  restoreDatabase: (backupName: string) => request<ActionResult>("/database/restore", { method: "POST", body: JSON.stringify({ backup_name: backupName, confirm: true }) }),
  deleteData: () => request<ActionResult>("/database/data", { method: "DELETE", body: JSON.stringify({ confirmation: "SUPPRIMER" }) }),
  exportTournamentsUrl: (anonymize: boolean) => `${API_ROOT}/export/tournaments.csv?anonymize=${anonymize ? "true" : "false"}`
};
