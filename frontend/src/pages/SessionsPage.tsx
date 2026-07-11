import { useState } from "react";
import { CalendarDays, Clock3, Gamepad2, TrendingUp } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, SectionCard } from "../components/Ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { Session } from "../types";
import { formatDate, formatDuration, formatMoney, formatNumber, formatPercent } from "../utils/format";

export function SessionsPage() {
  const [period, setPeriod] = useState("all");
  const [expanded, setExpanded] = useState<number | string | null>(null);
  const { data, loading, error, reload } = useApi(() => api.sessions({ period }), [period]);
  const sessions = data?.items ?? [];
  const totals = sessions.reduce(
    (acc, session) => ({ games: acc.games + session.tournaments_count, minutes: acc.minutes + session.duration_minutes, result: acc.result + session.net_result }),
    { games: 0, minutes: 0, result: 0 }
  );
  const weightedRoi = sessions.length ? sessions.reduce((sum, session) => sum + session.roi * session.tournaments_count, 0) / Math.max(1, totals.games) : 0;

  return (
    <>
      <PageHeader
        eyebrow="Rythme de jeu"
        title="Sessions"
        description="Une session démarre automatiquement après 30 minutes d’inactivité, ou selon le seuil configuré."
        actions={<select aria-label="Période" value={period} onChange={(event) => setPeriod(event.target.value)}><option value="all">Toutes les périodes</option><option value="30d">30 derniers jours</option><option value="90d">90 derniers jours</option><option value="year">Cette année</option></select>}
      />

      {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={reload} /> : !sessions.length ? <EmptyState title="Aucune session constituée" description="Les sessions apparaîtront une fois des parties terminées importées." /> : (
        <div className="sessions-stack">
          <section className="metrics-grid detail-metrics">
            <MetricCard label="Sessions" value={formatNumber(sessions.length)} icon={<CalendarDays />} />
            <MetricCard label="Parties" value={formatNumber(totals.games)} hint={`${formatNumber(totals.games / sessions.length, 1)} par session`} icon={<Gamepad2 />} />
            <MetricCard label="Temps de jeu" value={formatDuration(totals.minutes)} hint={`${formatDuration(totals.minutes / sessions.length)} en moyenne`} icon={<Clock3 />} />
            <MetricCard label="Résultat" value={formatMoney(totals.result, "EUR", true)} hint={`ROI pondéré ${formatPercent(weightedRoi)}`} tone={totals.result >= 0 ? "positive" : "negative"} icon={<TrendingUp />} />
          </section>

          <div className="sessions-list">
            {sessions.map((session: Session, index) => {
              const open = expanded === session.id;
              return (
                <article className="session-card" key={session.id}>
                  <button className="session-summary" type="button" aria-expanded={open} onClick={() => setExpanded(open ? null : session.id)}>
                    <span className="session-index">S{sessions.length - index}</span>
                    <div><strong>{formatDate(session.started_at)}</strong><small>{formatDate(session.started_at, true).split(" à ").at(-1)} → {formatDate(session.ended_at, true).split(" à ").at(-1)}</small></div>
                    <div><small>Durée</small><strong>{formatDuration(session.duration_minutes)}</strong></div>
                    <div><small>Parties</small><strong>{formatNumber(session.tournaments_count)}</strong></div>
                    <div><small>ROI</small><strong>{formatPercent(session.roi)}</strong></div>
                    <div className={session.net_result >= 0 ? "value-positive" : "value-negative"}><small>Résultat</small><strong>{formatMoney(session.net_result, "EUR", true)}</strong></div>
                    <span className={`expand-icon ${open ? "open" : ""}`}>⌄</span>
                  </button>
                  {open && (
                    <div className="session-details">
                      <div className="session-highlights">
                        <div><small>Meilleure partie</small><strong className="value-positive">{formatMoney(session.best_tournament, "EUR", true)}</strong></div>
                        <div><small>Pire partie</small><strong className="value-negative">{formatMoney(session.worst_tournament, "EUR", true)}</strong></div>
                      </div>
                      {session.evolution?.length ? (
                        <div className="chart-wrap session-chart">
                          <ResponsiveContainer width="100%" height="100%"><AreaChart data={session.evolution}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" /><YAxis tickFormatter={(value) => `${value}€`} /><Tooltip formatter={(value) => formatMoney(Number(value), "EUR", true)} /><Area type="monotone" dataKey="cumulative" name="Cumul" stroke="#49d49d" fill="#49d49d22" /></AreaChart></ResponsiveContainer>
                        </div>
                      ) : <p className="muted">Évolution non disponible pour cette session.</p>}
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          <SectionCard title="Lecture responsable" subtitle="Les sessions décrivent des résultats passés, pas votre niveau sur un échantillon court.">
            <p className="educational-note">Le ROI d’une courte session est très volatil. Utilisez les tendances de volume, la fatigue perçue et les décisions marquées « à revoir » comme pistes de travail, sans transformer un résultat négatif en diagnostic automatique.</p>
          </SectionCard>
        </div>
      )}
    </>
  );
}
