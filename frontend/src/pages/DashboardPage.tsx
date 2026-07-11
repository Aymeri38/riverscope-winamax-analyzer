import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Clock3, Coins, Gamepad2, Gauge, Hand, Target, Trophy } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { MetricCard, EmptyState, ErrorState, LoadingState, PageHeader, SectionCard } from "../components/Ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { HeroStatMetric, HeroStats } from "../types";
import { formatDuration, formatMoney, formatNumber, formatPercent } from "../utils/format";

type Period = "daily" | "weekly" | "monthly";

const defaultFilters = {
  date_from: "",
  date_to: "",
  buy_in: "",
  multiplier: "",
  rank: "",
  players: "",
  result: ""
};

const preflopMetrics = [
  ["vpip", "VPIP"], ["pfr", "PFR"], ["limp", "Limp"], ["limp_fold", "Limp-fold"],
  ["limp_call", "Limp-call"], ["limp_raise", "Limp-raise"], ["open_raise", "Open-raise"],
  ["fold_face_open", "Fold face à open"], ["call_face_open", "Call face à open"], ["three_bet", "3-bet"],
  ["fold_face_three_bet", "Fold face à 3-bet"], ["shove", "Shove"], ["call_shove", "Call de shove"], ["bb_walk", "Walk en BB"]
] as const;

const postflopMetrics = [
  ["cbet_flop", "C-bet flop"], ["fold_face_cbet", "Fold face à c-bet"], ["check_raise", "Check-raise"],
  ["aggression_frequency", "Fréquence d’agression"], ["aggression_factor", "Facteur d’agression"],
  ["went_to_showdown", "Went to showdown"], ["won_at_showdown", "Won at showdown"],
  ["won_when_saw_flop", "Won when saw flop"], ["barrel_turn", "Barrel turn"], ["barrel_river", "Barrel river"],
  ["fold_river", "Fold river"], ["hero_call_river", "Hero call river"]
] as const;

function TechnicalMetric({ metric, label, factor = false }: { metric?: HeroStatMetric; label: string; factor?: boolean }) {
  return (
    <div className="technical-metric">
      <span>{label}</span>
      <strong>{metric?.value === null || metric?.value === undefined ? "—" : factor ? formatNumber(metric.value, 2) : formatPercent(metric.value)}</strong>
      <small>{metric?.denominator ? `${formatNumber(metric.numerator)} / ${formatNumber(metric.denominator)} occasions` : "Échantillon insuffisant"}</small>
    </div>
  );
}

function selectStats(root: HeroStats | undefined, slice: string): HeroStats | undefined {
  if (!root || slice === "global") return root;
  const [group, ...keyParts] = slice.split(":");
  const key = keyParts.join(":");
  if (group === "position") return root.by_position?.[key];
  if (group === "players") return root.by_players?.[key];
  if (group === "depth") return root.by_depth?.[key];
  return root;
}

export function DashboardPage() {
  const [filters, setFilters] = useState(defaultFilters);
  const [period, setPeriod] = useState<Period>("daily");
  const [statSlice, setStatSlice] = useState("global");
  const { data, loading, error, reload } = useApi(
    () => api.dashboard(filters),
    [filters.date_from, filters.date_to, filters.buy_in, filters.multiplier, filters.rank, filters.players, filters.result]
  );

  const periodSeries = data?.[`${period}_results`] ?? [];
  const selectedStats = selectStats(data?.hero_stats, statSlice) ?? data?.hero_stats;

  return (
    <>
      <PageHeader
        eyebrow="Performance Expresso"
        title="Tableau de bord"
        description="Vos résultats, tendances et volumes — uniquement sur les tournois dont la fin est confirmée."
      />

      <section className="filter-bar" aria-label="Filtres du tableau de bord">
        <label>
          Du
          <input type="date" value={filters.date_from} onChange={(event) => setFilters({ ...filters, date_from: event.target.value })} />
        </label>
        <label>
          Au
          <input type="date" value={filters.date_to} onChange={(event) => setFilters({ ...filters, date_to: event.target.value })} />
        </label>
        <label>
          Buy-in
          <select value={filters.buy_in} onChange={(event) => setFilters({ ...filters, buy_in: event.target.value })}>
            <option value="">Tous</option>
            <option value="1">1 €</option><option value="2">2 €</option><option value="5">5 €</option><option value="other">Autre</option>
          </select>
        </label>
        <label>
          Multiplicateur
          <input inputMode="numeric" placeholder="Tous" value={filters.multiplier} onChange={(event) => setFilters({ ...filters, multiplier: event.target.value })} />
        </label>
        <label>
          Classement
          <select value={filters.rank} onChange={(event) => setFilters({ ...filters, rank: event.target.value })}>
            <option value="">Tous</option><option value="1">1er</option><option value="2">2e</option><option value="3">3e</option>
          </select>
        </label>
        <label>
          Joueurs
          <select value={filters.players} onChange={(event) => setFilters({ ...filters, players: event.target.value })}>
            <option value="">Tous</option><option value="2">Heads-up</option><option value="3">3 joueurs</option>
          </select>
        </label>
        <label>
          Résultat
          <select value={filters.result} onChange={(event) => setFilters({ ...filters, result: event.target.value })}>
            <option value="">Tous</option><option value="positive">Positif</option><option value="negative">Négatif</option>
          </select>
        </label>
        <button className="button ghost filter-reset" type="button" onClick={() => setFilters(defaultFilters)}>Réinitialiser</button>
      </section>

      {loading ? (
        <LoadingState label="Calcul de vos statistiques…" />
      ) : error ? (
        <ErrorState error={error} retry={reload} />
      ) : !data || data.tournaments_count === 0 ? (
        <EmptyState title="Aucune partie importée" description="Configurez votre dossier Winamax, puis lancez un rescannage depuis les paramètres." />
      ) : (
        <div className="dashboard-stack">
          <section className="metrics-grid primary-metrics" aria-label="Indicateurs principaux">
            <MetricCard label="Résultat net" value={formatMoney(data.net_result, "EUR", true)} hint={`${formatNumber(data.tournaments_count)} parties`} tone={data.net_result >= 0 ? "positive" : "negative"} icon={data.net_result >= 0 ? <ArrowUpRight /> : <ArrowDownRight />} />
            <MetricCard label="ROI" value={formatPercent(data.roi)} hint={`ITM ${formatPercent(data.itm)}`} tone={data.roi >= 0 ? "positive" : "negative"} icon={<Target />} />
            <MetricCard label="Gain horaire" value={formatMoney(data.hourly_profit, "EUR", true)} hint={`Durée moy. ${formatDuration(data.average_duration_minutes)}`} icon={<Clock3 />} />
            <MetricCard label="chipEV / partie" value={data.chipev_per_game === null || data.chipev_per_game === undefined ? "Non calculable" : `${formatNumber(data.chipev_per_game, 1)} jetons`} hint="Jetons nets moyens, sans valeur inventée" tone="accent" icon={<Gauge />} />
          </section>

          <SectionCard title="Courbe de gains" subtitle="Bankroll théorique cumulée et EV lorsque les cartes connues permettent son calcul.">
            <div className="chart-wrap chart-large" aria-label="Courbe des gains cumulés">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.profit_series ?? []} margin={{ top: 12, right: 18, left: 2, bottom: 2 }}>
                  <defs>
                    <linearGradient id="profitFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#49d49d" stopOpacity={0.35} /><stop offset="100%" stopColor="#49d49d" stopOpacity={0} /></linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" minTickGap={28} />
                  <YAxis tickFormatter={(value) => `${value}€`} width={54} />
                  <Tooltip formatter={(value) => formatMoney(Number(value), "EUR", true)} />
                  <Legend />
                  <Area type="monotone" dataKey="cumulative" name="Gains cumulés" stroke="#49d49d" strokeWidth={2.4} fill="url(#profitFill)" />
                  <Line type="monotone" dataKey="ev" name="EV calculable" stroke="#e8b94f" strokeWidth={2} dot={false} connectNulls={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </SectionCard>

          <section className="metrics-grid secondary-metrics" aria-label="Statistiques complémentaires">
            <MetricCard label="Parties" value={formatNumber(data.tournaments_count)} hint={`${formatNumber(data.hands_count)} mains`} icon={<Gamepad2 />} />
            <MetricCard label="Buy-ins" value={formatMoney(data.total_buy_ins)} hint={`Mise moy. ${formatMoney(data.average_buy_in)}`} icon={<Coins />} />
            <MetricCard label="Gains bruts" value={formatMoney(data.total_winnings)} hint={`Plus gros gain ${formatMoney(data.biggest_win)}`} icon={<Trophy />} />
            <MetricCard label="Gain moyen" value={formatMoney(data.average_profit, "EUR", true)} hint={`${formatNumber(data.average_hands, 1)} mains / partie`} icon={<Hand />} />
            <MetricCard label="Victoires" value={formatPercent(data.win_rate)} hint={`2e : ${formatPercent(data.second_place_rate)}`} />
            <MetricCard label="3e place" value={formatPercent(data.third_place_rate)} hint={`Downswing max ${formatMoney(data.biggest_downswing)}`} tone={data.third_place_rate > 40 ? "negative" : "default"} />
          </section>

          <SectionCard
            title="Statistiques techniques du héros"
            subtitle={`Fréquences observées sur ${formatNumber(selectedStats?.hands)} mains ; le dénominateur dépend des occasions réelles.`}
            action={data.hero_stats ? (
              <label className="inline-select">Ventilation
                <select value={statSlice} onChange={(event) => setStatSlice(event.target.value)}>
                  <option value="global">Toutes les mains</option>
                  {Object.keys(data.hero_stats.by_position ?? {}).map((key) => <option key={`p-${key}`} value={`position:${key}`}>Position · {key}</option>)}
                  {Object.keys(data.hero_stats.by_players ?? {}).map((key) => <option key={`j-${key}`} value={`players:${key}`}>{key}</option>)}
                  {Object.keys(data.hero_stats.by_depth ?? {}).map((key) => <option key={`d-${key}`} value={`depth:${key}`}>Profondeur · {key}</option>)}
                </select>
              </label>
            ) : undefined}
          >
            {!selectedStats ? <EmptyState title="Statistiques techniques indisponibles" description="Les actions du héros n’ont pas encore pu être identifiées." /> : (
              <div className="technical-stats-grid">
                <div className="technical-group"><h3>Préflop</h3><div>{preflopMetrics.map(([key, label]) => <TechnicalMetric key={key} label={label} metric={selectedStats.metrics[key]} />)}</div></div>
                <div className="technical-group"><h3>Postflop</h3><div>{postflopMetrics.map(([key, label]) => <TechnicalMetric key={key} label={label} metric={selectedStats.metrics[key]} factor={key === "aggression_factor"} />)}</div></div>
              </div>
            )}
          </SectionCard>

          <SectionCard title="Repères spécifiques Expresso" subtitle="Contexte de tournoi calculé sur les résultats importés.">
            <div className="expresso-stats-strip">
              <div><span>Multiplicateur moyen</span><strong>{data.expresso_stats?.average_multiplier === null || data.expresso_stats?.average_multiplier === undefined ? "—" : `×${formatNumber(data.expresso_stats.average_multiplier, 2)}`}</strong></div>
              <div><span>Victoires en heads-up</span><strong>{formatPercent(data.expresso_stats?.heads_up_win_rate)}</strong></div>
              <div><span>Victoires à 3 joueurs</span><strong>{formatPercent(data.expresso_stats?.three_handed_win_rate)}</strong></div>
              <div><span>Éliminations en premier</span><strong>{formatPercent(data.expresso_stats?.first_elimination_rate)}</strong></div>
              <div><span>Durée avant élimination</span><strong>{formatDuration(data.expresso_stats?.average_elimination_minutes)}</strong></div>
              <div><span>Remontées sous 10 BB</span><strong>{formatPercent(data.expresso_stats?.comeback_under_10bb_rate)}</strong></div>
            </div>
            <p className="formula-note"><strong>chipEV/game</strong> = moyenne des variations nettes de jetons du héros par tournoi lorsque les stacks sont suffisamment connus. Aucune valeur n’est extrapolée si les données manquent. {data.expresso_stats?.comeback_note}</p>
          </SectionCard>

          <div className="two-column-grid">
            <SectionCard title="Résultats par limite" subtitle="ROI, net et volume par buy-in.">
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Limite</th><th>Parties</th><th>Net</th><th>ROI</th><th>ITM</th><th>Victoires</th></tr></thead>
                  <tbody>
                    {(data.by_limit ?? []).map((row) => (
                      <tr key={row.label}><td><strong>{row.label}</strong></td><td>{formatNumber(row.tournaments)}</td><td className={row.net_result >= 0 ? "value-positive" : "value-negative"}>{formatMoney(row.net_result, "EUR", true)}</td><td>{formatPercent(row.roi)}</td><td>{formatPercent(row.itm)}</td><td>{formatPercent(row.win_rate)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <SectionCard title="Multiplicateurs observés" subtitle="Distribution réelle des Expresso importés.">
              <div className="chart-wrap chart-medium">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.multiplier_distribution ?? []}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" /><YAxis allowDecimals={false} />
                    <Tooltip /><Bar dataKey="count" name="Parties" fill="#e8b94f" radius={[5, 5, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </SectionCard>
          </div>

          <SectionCard
            title="Résultats dans le temps"
            action={
              <div className="segmented-control" aria-label="Période d’agrégation">
                {(["daily", "weekly", "monthly"] as const).map((value) => (
                  <button key={value} className={period === value ? "active" : ""} onClick={() => setPeriod(value)} type="button">
                    {{ daily: "Jour", weekly: "Semaine", monthly: "Mois" }[value]}
                  </button>
                ))}
              </div>
            }
          >
            {periodSeries.length ? (
              <div className="chart-wrap chart-medium">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={periodSeries}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" minTickGap={20} /><YAxis tickFormatter={(value) => `${value}€`} /><Tooltip formatter={(value) => formatMoney(Number(value), "EUR", true)} /><Bar dataKey="net" name="Résultat" fill="#49d49d" radius={[5, 5, 0, 0]} /></BarChart>
                </ResponsiveContainer>
              </div>
            ) : <EmptyState title="Pas assez de données" description="Cette agrégation sera disponible après plusieurs parties." />}
          </SectionCard>
        </div>
      )}
    </>
  );
}
