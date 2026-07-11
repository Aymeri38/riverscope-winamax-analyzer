import {
  Clock3,
  Coins,
  Gamepad2,
  Gauge,
  ShieldCheck,
  Target,
  TrendingUp,
  Trophy
} from "lucide-react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import type {
  CommunityContributorProfile,
  CommunityProfileBreakdown,
  CommunityProfileTrendPoint
} from "../types";
import { EmptyState, MetricCard, SectionCard } from "./Ui";
import {
  formatDate,
  formatDuration,
  formatMoney,
  formatNumber,
  formatPercent
} from "../utils/format";

export function CommunityContributorProfileView({
  profile
}: {
  profile: CommunityContributorProfile;
}) {
  const { contributor, summary } = profile;
  const summaryCurrency = summary.currency;
  const globalMoney = (value: number | null, sign = false) => {
    if (!summaryCurrency) return "Plusieurs devises";
    return value === null ? "—" : formatMoney(value, summaryCurrency, sign);
  };

  if (!summary.games) {
    return (
      <div className="community-profile-stack">
        <ProfileIdentity profile={profile} />
        <EmptyState
          title="Aucune partie partagée"
          description="La fiche apparaîtra dès que ce contributeur aura synchronisé une partie entièrement terminée."
        />
      </div>
    );
  }

  return (
    <div className="community-profile-stack">
      <ProfileIdentity profile={profile} />

      <section className="metrics-grid community-profile-kpis" aria-label="Indicateurs du contributeur">
        <MetricCard
          label="Résultat net"
          value={globalMoney(summary.net_result, true)}
          hint={summaryCurrency && summary.total_winnings !== null
            ? `${formatMoney(summary.total_winnings, summaryCurrency)} gagnés`
            : "Détail séparé par devise ci-dessous"}
          tone={summary.net_result === null ? "default" : summary.net_result >= 0 ? "positive" : "negative"}
          icon={<TrendingUp />}
        />
        <MetricCard
          label="ROI"
          value={formatPercent(summary.roi_percent)}
          hint={summary.roi_percent === null ? "Non agrégé entre devises" : `ITM ${formatPercent(summary.itm_percent)}`}
          tone={summary.roi_percent === null ? "default" : summary.roi_percent >= 0 ? "positive" : "negative"}
          icon={<Target />}
        />
        <MetricCard
          label="Volume"
          value={`${formatNumber(summary.games)} parties`}
          hint={`${formatNumber(summary.hands)} mains`}
          icon={<Gamepad2 />}
        />
        <MetricCard
          label="Buy-ins"
          value={globalMoney(summary.total_buyins)}
          hint={summaryCurrency && summary.average_buyin !== null
            ? `Moyenne ${formatMoney(summary.average_buyin, summaryCurrency)}`
            : "Aucune conversion entre devises"}
          icon={<Coins />}
        />
        <MetricCard
          label="Victoires"
          value={formatPercent(summary.win_rate_percent)}
          hint={`2e ${formatPercent(summary.second_place_percent)} · 3e ${formatPercent(summary.third_place_percent)}`}
          icon={<Trophy />}
        />
        <MetricCard
          label="Gain moyen"
          value={summaryCurrency && summary.average_net !== null
            ? formatMoney(summary.average_net, summaryCurrency, true)
            : "—"}
          hint={summaryCurrency && summary.average_winnings !== null
            ? `Récompense moy. ${formatMoney(summary.average_winnings, summaryCurrency)}`
            : "Consultez les synthèses par devise"}
          tone={summary.average_net === null ? "default" : summary.average_net >= 0 ? "positive" : "negative"}
        />
        <MetricCard
          label="Durée moyenne"
          value={formatDuration(summary.average_duration_seconds / 60)}
          hint={`${formatNumber(summary.average_hands, 1)} mains / partie`}
          icon={<Clock3 />}
        />
        <MetricCard
          label="chipEV / partie"
          value={summary.chip_ev_per_game === null
            ? "Non calculable"
            : `${formatNumber(summary.chip_ev_per_game, 1)} jetons`}
          hint={`Couverture ${formatPercent(summary.chip_ev_coverage_percent)} · ${formatNumber(summary.chip_ev_games)} parties`}
          tone="accent"
          icon={<Gauge />}
        />
      </section>

      <SectionCard
        title="Évolution du résultat"
        subtitle="Résultats quotidiens et cumul des parties terminées partagées par ce contributeur."
      >
        {profile.trend.length ? (
          <ProfileTrend points={profile.trend} />
        ) : (
          <EmptyState title="Historique insuffisant" description="La tendance sera visible après plusieurs journées de jeu partagées." />
        )}
      </SectionCard>

      <div className="community-profile-breakdowns">
        <ProfileBreakdown
          title="Synthèse par devise"
          subtitle="Chaque devise reste indépendante ; aucun montant EUR, USD ou autre n’est additionné."
          rows={profile.by_currency}
          empty="Aucune devise disponible"
          kind="currency"
          className="community-profile-currency-breakdown"
        />
        <ProfileBreakdown
          title="Résultats par limite"
          subtitle="Volume, rentabilité et chipEV selon le buy-in."
          rows={profile.by_limit}
          empty="Aucune limite disponible"
          kind="limit"
        />
        <ProfileBreakdown
          title="Résultats par multiplicateur"
          subtitle="Comportement des résultats selon les multiplicateurs observés."
          rows={profile.by_multiplier}
          empty="Aucun multiplicateur disponible"
          kind="multiplier"
        />
      </div>

      <SectionCard
        title="Parties récentes"
        subtitle="Les dix dernières parties terminées partagées par ce contributeur."
      >
        {!profile.recent_tournaments.length ? (
          <EmptyState title="Aucune partie récente" />
        ) : (
          <div className="table-scroll">
            <table className="data-table community-profile-recent">
              <thead>
                <tr><th>Date</th><th>Buy-in</th><th>Multi.</th><th>Place</th><th>Gain</th><th>Net</th><th>Durée</th><th>Mains</th></tr>
              </thead>
              <tbody>
                {profile.recent_tournaments.map((tournament) => (
                  <tr key={tournament.id}>
                    <td>{formatDate(tournament.started_at, true)}</td>
                    <td>{formatMoney(tournament.buy_in, tournament.currency ?? "EUR")}</td>
                    <td>{tournament.multiplier ? `×${formatNumber(tournament.multiplier, 2)}` : "—"}</td>
                    <td>{tournament.rank ? `${tournament.rank}${tournament.rank === 1 ? "er" : "e"}` : "—"}</td>
                    <td>{formatMoney(tournament.reward, tournament.currency ?? "EUR")}</td>
                    <td className={tournament.net_result >= 0 ? "value-positive" : "value-negative"}>
                      {formatMoney(tournament.net_result, tournament.currency ?? "EUR", true)}
                    </td>
                    <td>{formatDuration(tournament.duration_minutes)}</td>
                    <td>{formatNumber(tournament.hands_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}

function ProfileTrend({ points }: { points: CommunityProfileTrendPoint[] }) {
  const currencies = Array.from(new Set(points.map((point) => point.currency)));
  return (
    <div className={`community-profile-trend-grid ${currencies.length > 1 ? "multi-currency" : ""}`}>
      {currencies.map((currency) => {
        const series = points.filter((point) => point.currency === currency);
        const gradientId = `communityProfileFill-${currency.replace(/[^A-Z0-9]/gi, "")}`;
        return (
          <div className="community-profile-trend-panel" key={currency}>
            <div className="community-profile-trend-heading">
              <strong>{currency}</strong>
              <span>{formatNumber(series.reduce((total, point) => total + point.games, 0))} parties</span>
            </div>
            <div className="chart-wrap community-profile-chart" aria-label={`Courbe du résultat cumulé en ${currency}`}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={series} margin={{ top: 12, right: 18, left: 2, bottom: 2 }}>
                  <defs>
                    <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#49d49d" stopOpacity={0.32} />
                      <stop offset="100%" stopColor="#49d49d" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" minTickGap={28} tickFormatter={(value) => formatDate(String(value))} />
                  <YAxis tickFormatter={(value) => formatMoney(Number(value), currency)} width={67} />
                  <Tooltip
                    labelFormatter={(value) => formatDate(String(value))}
                    formatter={(value, name) => [
                      formatMoney(Number(value), currency, true),
                      name === "cumulative_net" ? "Cumul" : "Résultat du jour"
                    ]}
                  />
                  <Area type="monotone" dataKey="cumulative_net" stroke="none" fill={`url(#${gradientId})`} />
                  <Bar dataKey="net_result" name="Résultat du jour" fill="#e8b94f" opacity={0.65} radius={[4, 4, 0, 0]} maxBarSize={22} />
                  <Line type="monotone" dataKey="cumulative_net" name="Cumul" stroke="#49d49d" strokeWidth={2.5} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProfileIdentity({ profile }: { profile: CommunityContributorProfile }) {
  const { contributor, summary } = profile;
  return (
    <section className="community-profile-identity">
      <div className="community-profile-avatar" aria-hidden="true">
        {contributor.display_name.slice(0, 1).toUpperCase()}
      </div>
      <div className="community-profile-title">
        <span>Fiche globale consentie</span>
        <h2>{contributor.display_name}</h2>
        <p>
          {contributor.joined_at ? `Membre depuis le ${formatDate(contributor.joined_at)}` : "Date d’adhésion indisponible"}
          {summary.first_game_at && <> · Première partie {formatDate(summary.first_game_at)}</>}
          {summary.last_game_at && <> · Dernière partie {formatDate(summary.last_game_at)}</>}
        </p>
      </div>
      <div className="community-profile-consent">
        <ShieldCheck aria-hidden="true" />
        <div>
          <strong>Identité choisie par le membre</strong>
          <small>Cette fiche concerne le contributeur ; le suivi adverse post-session est présenté séparément.</small>
        </div>
      </div>
    </section>
  );
}

function ProfileBreakdown({
  title,
  subtitle,
  rows,
  empty,
  kind,
  className = ""
}: {
  title: string;
  subtitle: string;
  rows: CommunityProfileBreakdown[];
  empty: string;
  kind: "currency" | "limit" | "multiplier";
  className?: string;
}) {
  return (
    <SectionCard title={title} subtitle={subtitle} className={className}>
      {!rows.length ? <EmptyState title={empty} /> : (
        <div className="table-scroll">
          <table className="data-table community-profile-breakdown-table">
            <thead><tr><th>Segment</th><th>Parties</th><th>Net</th><th>ROI</th><th>ITM</th><th>Victoires</th><th>chipEV</th></tr></thead>
            <tbody>
              {rows.map((row) => {
                const segment = kind === "currency"
                  ? row.currency
                  : kind === "limit"
                    ? row.buyin === null ? row.label : formatMoney(row.buyin, row.currency)
                    : row.multiplier === null ? row.label : `×${formatNumber(row.multiplier, 2)} · ${row.currency}`;
                return (
                  <tr key={`${kind}-${row.currency}-${row.buyin ?? "all"}-${row.multiplier ?? "all"}`}>
                    <td><strong>{segment}</strong></td>
                    <td>{formatNumber(row.games)}</td>
                    <td className={row.net_result >= 0 ? "value-positive" : "value-negative"}>{formatMoney(row.net_result, row.currency, true)}</td>
                    <td>{formatPercent(row.roi_percent)}</td>
                    <td>{formatPercent(row.itm_percent)}</td>
                    <td>{formatPercent(row.win_rate_percent)}</td>
                    <td>{row.chip_ev_per_game === null ? "—" : formatNumber(row.chip_ev_per_game, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
