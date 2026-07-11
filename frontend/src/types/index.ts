export type Severity = "info" | "low" | "medium" | "high" | "critical" | string;
export type ImportFileState = "detected" | "waiting_for_completion" | "imported" | "failed";
export type ThemeMode = "dark" | "light" | "system";

export interface ApiPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface HealthStatus {
  status: string;
  version?: string;
  database?: string;
}

export interface ImportStatus {
  watching: boolean;
  configured_paths: string[];
  last_import_at?: string | null;
  active_files: number;
  pending_files: number;
  failed_files: number;
  imported_files: number;
  tournament_active?: boolean;
  safe_to_analyze?: boolean;
  latest_state?: ImportFileState;
  message?: string;
}

export interface TimePoint {
  date: string;
  label?: string;
  net: number;
  cumulative: number;
  ev?: number | null;
  tournaments?: number;
}

export interface BreakdownRow {
  label: string;
  tournaments: number;
  net_result: number;
  roi: number;
  itm: number;
  win_rate?: number;
}

export interface HeroStatMetric {
  value: number | null;
  numerator: number;
  denominator: number;
}

export interface HeroStats {
  hands: number;
  metrics: Record<string, HeroStatMetric>;
  by_position?: Record<string, HeroStats>;
  by_depth?: Record<string, HeroStats>;
  by_players?: Record<string, HeroStats>;
}

export interface ExpressoStats {
  average_multiplier?: number | null;
  heads_up_win_rate?: number | null;
  three_handed_win_rate?: number | null;
  first_elimination_rate?: number | null;
  average_elimination_minutes?: number | null;
  comeback_under_10bb_rate?: number | null;
  comeback_note?: string;
}

export interface DashboardData {
  tournaments_count: number;
  hands_count: number;
  total_buy_ins: number;
  total_winnings: number;
  net_result: number;
  roi: number;
  win_rate: number;
  second_place_rate: number;
  third_place_rate: number;
  itm: number;
  average_profit: number;
  hourly_profit: number;
  average_duration_minutes: number;
  average_hands: number;
  average_buy_in: number;
  biggest_win: number;
  biggest_downswing: number;
  chipev_per_game?: number | null;
  profit_series: TimePoint[];
  daily_results: TimePoint[];
  weekly_results: TimePoint[];
  monthly_results: TimePoint[];
  by_limit: BreakdownRow[];
  by_multiplier: BreakdownRow[];
  multiplier_distribution?: Array<{ label: string; count: number; percentage?: number }>;
  hero_stats?: HeroStats;
  expresso_stats?: ExpressoStats;
}

export interface PlayerSeat {
  id?: number | string;
  name: string;
  position?: string;
  starting_stack?: number;
  starting_stack_bb?: number;
  finishing_place?: number | null;
  reward?: number;
  is_hero?: boolean;
}

export interface Tournament {
  id: number | string;
  tournament_id?: string;
  started_at: string;
  ended_at?: string | null;
  buy_in: number;
  currency?: string;
  multiplier?: number | null;
  prize_pool?: number;
  rank?: number | null;
  reward?: number;
  net_result: number;
  duration_minutes?: number | null;
  hands_count: number;
  chipev?: number | null;
  tags?: string[];
  analysis_status?: string;
  format?: string;
  player_count?: number;
  initial_stack?: number;
  ticket_won?: string | null;
  players?: PlayerSeat[];
  hands?: HandSummary[];
}

export interface HandSummary {
  id: number | string;
  hand_id?: string;
  tournament_id?: number | string;
  played_at: string;
  hero_cards?: string[];
  board?: string[];
  position?: string;
  players_count?: number;
  effective_stack_bb?: number | null;
  blinds?: string;
  preflop_action?: string;
  postflop_action?: string;
  is_all_in?: boolean;
  showdown?: boolean;
  pot_bb?: number | null;
  net_result_chips?: number;
  leak_count?: number;
  leaks?: string[];
  classification?: string;
  notes?: string | null;
  tags?: string[];
}

export interface ReplayAction {
  id?: number | string;
  order: number;
  street: "preflop" | "flop" | "turn" | "river" | "showdown" | string;
  player_name: string;
  position?: string;
  action: string;
  amount?: number | null;
  amount_bb?: number | null;
  pot_after?: number | null;
  stack_after?: number | null;
  is_hero?: boolean;
}

export interface ReplayData {
  hand: HandSummary;
  seats: PlayerSeat[];
  actions: ReplayAction[];
  hero_cards: string[];
  board: string[];
  initial_pot?: number;
  final_pot?: number;
  small_blind?: number;
  big_blind?: number;
  ante?: number;
  winner?: string;
  result?: string;
  equity?: {
    win: number;
    tie: number;
    lose: number;
    ev_chips?: number | null;
    actual_chips?: number | null;
    message?: string;
  } | null;
  safe_to_replay?: boolean;
  tournament_finished?: boolean;
}

export interface Session {
  id: number | string;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  tournaments_count: number;
  net_result: number;
  roi: number;
  best_tournament?: number;
  worst_tournament?: number;
  evolution?: TimePoint[];
}

export interface LeakFlag {
  id: number | string;
  name: string;
  severity: Severity;
  observed_value: number;
  threshold: number;
  unit?: string;
  occurrences: number;
  sample_size?: number;
  hand_ids?: Array<number | string>;
  explanation: string;
  recommendation: string;
  confidence: number;
  category?: string;
  active?: boolean;
}

export interface LeakThresholds {
  [key: string]: number;
}

export interface AppSettings {
  history_paths: string[];
  hero_name: string;
  import_delay_seconds: number;
  currency: string;
  session_gap_minutes: number;
  leak_thresholds: LeakThresholds;
  autostart: boolean;
  theme: ThemeMode;
  anonymize_exports: boolean;
  ai_analysis_enabled?: boolean;
}

export interface ListFilters {
  [key: string]: string | number | boolean | undefined | null;
}

export interface ActionResult {
  ok?: boolean;
  message?: string;
  path?: string;
  queued?: number;
}

export interface ContributionPreview {
  filename: string;
  media_type: string;
  encoding: string;
  payload: string;
  byte_size: number;
  sha256: string;
  network_sent: boolean;
  redactions: string[];
  exclusions: string[];
  warnings: string[];
}
