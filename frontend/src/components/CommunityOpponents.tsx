import { useState } from "react";
import {
  Activity,
  ArrowLeft,
  CalendarDays,
  Eye,
  Gauge,
  Search,
  ShieldCheck,
  Users
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type {
  CommunityOpponentProfile,
  CommunityOpponentRate,
  CommunityOpponentStatSlice
} from "../types";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  Pagination,
  SectionCard,
  StatusPill
} from "./Ui";
import { formatDate, formatNumber, formatPercent } from "../utils/format";

const PAGE_SIZE = 25;

export function CommunityOpponents({
  enabled,
  dataRevision
}: {
  enabled: boolean;
  dataRevision: number;
}) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const opponents = useApi(
    () => enabled ? api.communityOpponents(page, PAGE_SIZE) : Promise.resolve({ items: [], total: 0, page: 1, page_size: PAGE_SIZE }),
    [enabled, page, dataRevision]
  );
  const profile = useApi(
    () => enabled && selectedId ? api.communityOpponentProfile(selectedId) : Promise.resolve(null),
    [enabled, selectedId, dataRevision]
  );
  const normalizedSearch = search.trim().toLocaleLowerCase("fr-FR");
  const visibleOpponents = (opponents.data?.items ?? []).filter((opponent) =>
    !normalizedSearch || opponent.display_name.toLocaleLowerCase("fr-FR").includes(normalizedSearch)
  );

  if (selectedId) {
    return (
      <div className="community-opponent-stack">
        <button className="button ghost community-opponent-back" type="button" onClick={() => setSelectedId("")}>
          <ArrowLeft size={16} /> Retour aux adversaires observés
        </button>
        {profile.loading ? (
          <LoadingState label="Calcul des observations post-session…" />
        ) : profile.error ? (
          <ErrorState error={profile.error} retry={profile.reload} />
        ) : profile.data ? (
          <CommunityOpponentProfileView profile={profile.data} />
        ) : (
          <EmptyState title="Observation indisponible" />
        )}
      </div>
    );
  }

  return (
    <div className="community-opponent-stack">
      <section className="community-opponent-intro">
        <div><Eye aria-hidden="true" /><span><strong>Suivi adverse post-session</strong><small>Données factuelles issues uniquement de tournois terminés. Cette vue n’est ni un conseil de jeu ni une assistance en direct.</small></span></div>
        <div><ShieldCheck aria-hidden="true" /><span><strong>Accès réservé aux contributeurs</strong><small>Les pseudos sont chiffrés au repos sur le VPS et rapprochés entre les observations autorisées.</small></span></div>
      </section>

      <label className="community-opponent-search">
        <Search aria-hidden="true" />
        <span className="sr-only">Rechercher dans les pseudos chargés</span>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Rechercher dans cette page…"
          autoComplete="off"
        />
        <small>Recherche locale sur la page chargée : le pseudo n’est jamais placé dans l’URL.</small>
      </label>

      {opponents.loading ? (
        <LoadingState label="Chargement des observations…" />
      ) : opponents.error ? (
        <ErrorState error={opponents.error} retry={opponents.reload} />
      ) : !opponents.data?.items.length ? (
        <EmptyState title="Aucun adversaire observé" description="Les observations apparaîtront après la resynchronisation v2 de tournois terminés." />
      ) : !visibleOpponents.length ? (
        <EmptyState title="Aucun pseudo correspondant sur cette page" description="Effacez la recherche ou chargez une autre page." />
      ) : (
        <section className="section-card community-opponent-list-card">
          <div className="community-opponent-grid">
            {visibleOpponents.map((opponent) => (
              <button type="button" key={opponent.id} onClick={() => setSelectedId(opponent.id)}>
                <span className="community-opponent-avatar" aria-hidden="true">{opponent.display_name.slice(0, 1).toUpperCase()}</span>
                <span className="community-opponent-card-copy">
                  <strong>{opponent.display_name}</strong>
                  <small>{formatNumber(opponent.hands_count)} mains · {formatNumber(opponent.tournaments_count)} tournois</small>
                  <small>{formatNumber(opponent.contributors_count)} contributeur{opponent.contributors_count > 1 ? "s" : ""} · vu {formatDate(opponent.last_seen_at)}</small>
                </span>
                <Eye size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
          <Pagination
            page={opponents.data.page}
            total={opponents.data.total}
            pageSize={opponents.data.page_size}
            onPage={(next) => { setPage(next); setSearch(""); }}
          />
        </section>
      )}
    </div>
  );
}

function CommunityOpponentProfileView({ profile }: { profile: CommunityOpponentProfile }) {
  const { opponent, summary } = profile;
  return (
    <div className="community-opponent-profile">
      <section className="community-opponent-profile-hero">
        <div className="community-opponent-profile-avatar" aria-hidden="true">{opponent.display_name.slice(0, 1).toUpperCase()}</div>
        <div>
          <span>Observation post-session</span>
          <h2>{opponent.display_name}</h2>
          <p>Première observation {formatDate(opponent.first_seen_at)} · dernière observation {formatDate(opponent.last_seen_at)}</p>
        </div>
        <div className="community-opponent-disclaimer">
          <Activity aria-hidden="true" />
          <p><strong>Lecture descriptive uniquement</strong><small>Aucune range supposée, aucun ROI, aucune étiquette péjorative et aucun conseil pendant le jeu.</small></p>
        </div>
      </section>

      <section className="metrics-grid community-opponent-sample" aria-label="Échantillon observé">
        <MetricCard label="Mains observées" value={formatNumber(summary.hands)} hint={`${formatNumber(summary.preflop_known_hands)} préflops exploitables · ${formatNumber(summary.tournaments)} tournois`} icon={<Eye />} />
        <MetricCard label="Contributeurs" value={formatNumber(summary.contributors)} hint="Sources d’observation autorisées" icon={<Users />} />
        <MetricCard
          label="Jetons nets connus"
          value={`${summary.net_chips >= 0 ? "+" : ""}${formatNumber(summary.net_chips)} j`}
          hint={`${formatNumber(summary.known_net_hands)} / ${formatNumber(summary.hands)} mains couvertes`}
          tone={summary.net_chips >= 0 ? "positive" : "negative"}
          icon={<Gauge />}
        />
        <MetricCard label="Période" value={formatDate(opponent.last_seen_at)} hint={`Depuis ${formatDate(opponent.first_seen_at)}`} icon={<CalendarDays />} />
      </section>

      <SectionCard title="Fréquences observées" subtitle="Chaque mesure affiche son numérateur, son dénominateur et la couverture réellement disponible.">
        <div className="community-opponent-rate-grid">
          <OpponentRate label="VPIP" metric={summary.vpip} sampleSize={summary.hands} />
          <OpponentRate label="PFR" metric={summary.pfr} sampleSize={summary.hands} />
          <OpponentRate label="Limp" metric={summary.limp} sampleSize={summary.hands} />
          <OpponentRate label="3-bet" metric={summary.three_bet} sampleSize={summary.hands} />
          <OpponentRate label="Shove" metric={summary.shove} sampleSize={summary.hands} />
          <OpponentRate label="All-in" metric={summary.all_in} sampleSize={summary.hands} />
          <OpponentRate label="WTSD" metric={summary.wtsd} sampleSize={summary.hands} />
          <OpponentRate label="WSD" metric={summary.wsd} sampleSize={summary.hands} />
          <article className="community-opponent-rate">
            <span>Agressivité postflop</span>
            <strong>{summary.aggression.factor === null ? "—" : formatNumber(summary.aggression.factor, 2)}</strong>
            <small>{formatNumber(summary.aggression.aggressive_actions)} / {formatNumber(summary.aggression.opportunities)} occasions · {formatNumber(summary.aggression.calls)} calls</small>
            <em>{formatNumber(summary.aggression.checks)} checks · {formatNumber(summary.aggression.folds)} folds · fréquence {formatPercent(summary.aggression.frequency_percent)}</em>
          </article>
        </div>
      </SectionCard>

      <div className="community-opponent-slices">
        <OpponentSliceTable title="Par position" label="Position" rows={profile.by_position} />
        <OpponentSliceTable title="Par profondeur" label="Profondeur" rows={profile.by_depth} />
      </div>

      <SectionCard title="Observations récentes" subtitle="Échantillon factuel de mains terminées ; aucune reconstruction de range ou de cartes inconnues.">
        {!profile.recent_observations.length ? <EmptyState title="Aucune observation récente" /> : (
          <div className="table-scroll">
            <table className="data-table community-opponent-observations">
              <thead><tr><th>Date</th><th>Pos.</th><th>Prof.</th><th>Préflop</th><th>Postflop</th><th>Showdown</th><th>Jetons nets</th></tr></thead>
              <tbody>{profile.recent_observations.map((row) => (
                <tr key={`${row.tournament_id}-${row.hand_id}`}>
                  <td>{formatDate(row.played_at, true)}</td>
                  <td>{row.position ?? "—"}</td>
                  <td>{row.stack_bb === null ? "—" : `${formatNumber(row.stack_bb, 1)} BB`}</td>
                  <td>{row.preflop_known ? [row.vpip && "VPIP", row.pfr && "PFR", row.limp && "Limp", row.three_bet && "3-bet", row.shove && "Shove", row.is_all_in && "All-in"].filter(Boolean).join(" · ") || "Aucune action volontaire" : "Données insuffisantes"}</td>
                  <td>{formatNumber(row.postflop_aggressive_actions)} agressions / {formatNumber(row.postflop_calls)} calls</td>
                  <td>{row.went_showdown ? row.won_showdown ? "Vu · gagné" : "Vu" : "Non vu"}</td>
                  <td className={row.net === null ? "" : row.net >= 0 ? "value-positive" : "value-negative"}>
                    {row.net === null ? "—" : <>{row.net >= 0 ? "+" : ""}{formatNumber(row.net)} j</>}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}

function OpponentRate({ label, metric, sampleSize }: { label: string; metric: CommunityOpponentRate; sampleSize: number }) {
  return (
    <article className="community-opponent-rate">
      <span>{label}</span>
      <strong>{formatPercent(metric.percent)}</strong>
      <small>{formatNumber(metric.made)} / {formatNumber(metric.opportunities)} occasions</small>
      <em>Couverture {sampleSize ? formatPercent((metric.opportunities / sampleSize) * 100) : "0 %"}</em>
    </article>
  );
}

function OpponentSliceTable({ title, label, rows }: { title: string; label: string; rows: CommunityOpponentStatSlice[] }) {
  return (
    <SectionCard title={title} subtitle="Dénominateurs propres à chaque segment observé.">
      {!rows.length ? <EmptyState title="Échantillon indisponible" /> : (
        <div className="table-scroll">
          <table className="data-table community-opponent-slice-table">
            <thead><tr><th>{label}</th><th>Mains</th><th>Net connu</th><th>VPIP</th><th>PFR</th><th>3-bet</th><th>Shove</th><th>All-in</th><th>WTSD</th><th>WSD</th><th>Agression</th></tr></thead>
            <tbody>{rows.map((row) => (
              <tr key={row.label}>
                <td><strong>{row.label}</strong></td>
                <td>{formatNumber(row.hands)} <small>({formatNumber(row.preflop_known_hands)} préflops)</small></td>
                <td>{row.net_chips >= 0 ? "+" : ""}{formatNumber(row.net_chips)} j <small>({formatNumber(row.known_net_hands)}/{formatNumber(row.hands)})</small></td>
                <td><CompactRate metric={row.vpip} /></td>
                <td><CompactRate metric={row.pfr} /></td>
                <td><CompactRate metric={row.three_bet} /></td>
                <td><CompactRate metric={row.shove} /></td>
                <td><CompactRate metric={row.all_in} /></td>
                <td><CompactRate metric={row.wtsd} /></td>
                <td><CompactRate metric={row.wsd} /></td>
                <td>{formatNumber(row.aggression.aggressive_actions)}/{formatNumber(row.aggression.opportunities)} <small>AF {row.aggression.factor === null ? "—" : formatNumber(row.aggression.factor, 2)} · {formatNumber(row.aggression.calls)} calls</small></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

function CompactRate({ metric }: { metric: CommunityOpponentRate }) {
  return <>{formatNumber(metric.made)}/{formatNumber(metric.opportunities)} <small>{formatPercent(metric.percent)}</small></>;
}
