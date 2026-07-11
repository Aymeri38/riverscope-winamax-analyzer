import { useState } from "react";
import { ArrowLeft, Clock3, Coins, Play, Trophy, Users } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { HandReplayer } from "../components/HandReplayer";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, SectionCard, StatusPill } from "../components/Ui";
import { useSafety } from "../contexts/SafetyContext";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { formatDate, formatDuration, formatMoney, formatNumber, joinCards } from "../utils/format";

export function TournamentDetailPage() {
  const { id = "" } = useParams();
  const { safeToAnalyze } = useSafety();
  const [replayHand, setReplayHand] = useState<number | string | null>(null);
  const { data, loading, error, reload } = useApi(() => api.tournament(id), [id]);

  return (
    <>
      <Link className="back-link" to="/parties"><ArrowLeft size={17} /> Retour aux parties</Link>
      <PageHeader
        eyebrow={data?.format ?? "Expresso"}
        title={data ? `Partie #${data.tournament_id ?? data.id}` : "Détail de la partie"}
        description={data ? `${formatDate(data.started_at, true)} · tournoi terminé` : "Chargement du tournoi…"}
        actions={data?.analysis_status ? <StatusPill tone={data.analysis_status === "complete" ? "positive" : "warning"}>{data.analysis_status === "complete" ? "Analyse terminée" : data.analysis_status === "imported" ? "Analyse en attente" : "Analyse partielle"}</StatusPill> : undefined}
      />
      {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={reload} /> : !data ? <EmptyState /> : (
        <div className="detail-stack">
          <section className="metrics-grid detail-metrics">
            <MetricCard label="Résultat net" value={formatMoney(data.net_result, data.currency ?? "EUR", true)} tone={data.net_result >= 0 ? "positive" : "negative"} icon={<Coins />} />
            <MetricCard label="Classement" value={data.rank ? `${data.rank}${data.rank === 1 ? "er" : "e"}` : "—"} hint={`${formatNumber(data.player_count ?? data.players?.length)} joueurs`} icon={<Trophy />} />
            <MetricCard label="Prize pool" value={formatMoney(data.prize_pool, data.currency ?? "EUR")} hint={`Buy-in ${formatMoney(data.buy_in, data.currency ?? "EUR")} · ×${data.multiplier ?? "—"}`} icon={<Users />} />
            <MetricCard label="Durée" value={formatDuration(data.duration_minutes)} hint={`${formatNumber(data.hands_count)} mains`} icon={<Clock3 />} />
            <MetricCard label="chipEV" value={data.chipev === null || data.chipev === undefined ? "Non calculable" : `${formatNumber(data.chipev, 1)} jetons`} hint="Somme nette des jetons du héros" tone="accent" />
          </section>

          <div className="two-column-grid detail-grid">
            <SectionCard title="Participants" subtitle="Les adversaires restent locaux à cet appareil.">
              {data.players?.length ? (
                <div className="players-list">
                  {data.players.map((player, index) => (
                    <div className={player.is_hero ? "hero" : ""} key={player.id ?? `${player.name}-${index}`}>
                      <span className="player-avatar">{player.is_hero ? "H" : index + 1}</span>
                      <div><strong>{player.is_hero ? `${player.name} (héros)` : player.name}</strong><small>{player.position ?? `Place ${player.finishing_place ?? "—"}`}</small></div>
                      <span>{formatNumber(player.starting_stack, 0)} jetons</span>
                    </div>
                  ))}
                </div>
              ) : <EmptyState title="Participants non disponibles" description="L’historique ne contient pas assez d’informations." />}
            </SectionCard>
            <SectionCard title="Informations" subtitle="Résumé final détecté dans les fichiers Winamax.">
              <dl className="definition-grid">
                <div><dt>Début</dt><dd>{formatDate(data.started_at, true)}</dd></div>
                <div><dt>Fin</dt><dd>{formatDate(data.ended_at, true)}</dd></div>
                <div><dt>Stack initial</dt><dd>{formatNumber(data.initial_stack)} jetons</dd></div>
                <div><dt>Récompense</dt><dd>{formatMoney(data.reward, data.currency ?? "EUR")}</dd></div>
                <div><dt>Ticket</dt><dd>{data.ticket_won ?? "Aucun"}</dd></div>
                <div><dt>Tags</dt><dd>{data.tags?.join(", ") || "Aucun"}</dd></div>
              </dl>
            </SectionCard>
          </div>

          <SectionCard title="Mains de la partie" subtitle="Le replayer ne s’ouvre que sur votre action explicite et si la fin du tournoi est confirmée.">
            {!data.hands?.length ? <EmptyState title="Aucune main associée" /> : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Main</th><th>Cartes</th><th>Position</th><th>Stack eff.</th><th>Préflop</th><th>Board</th><th>Pot</th><th>Résultat</th><th>Lecture</th></tr></thead>
                  <tbody>
                    {data.hands.map((hand) => (
                      <tr key={hand.id}>
                        <td><strong>#{hand.hand_id ?? hand.id}</strong><small className="table-subline">{formatDate(hand.played_at, true)}</small></td>
                        <td className="cards-text">{joinCards(hand.hero_cards)}</td><td>{hand.position ?? "—"}</td><td>{hand.effective_stack_bb ? `${formatNumber(hand.effective_stack_bb, 1)} BB` : "—"}</td>
                        <td>{hand.preflop_action ?? "—"}</td><td className="cards-text">{joinCards(hand.board)}</td><td>{hand.pot_bb ? `${formatNumber(hand.pot_bb, 1)} BB` : "—"}</td>
                        <td className={(hand.net_result_chips ?? 0) >= 0 ? "value-positive" : "value-negative"}>{formatNumber(hand.net_result_chips, 0)} j</td>
                        <td><button className="button secondary compact" onClick={() => setReplayHand(hand.id)} disabled={!safeToAnalyze} title={!safeToAnalyze ? "Analyse verrouillée tant que la fin n’est pas confirmée" : undefined} type="button"><Play size={15} /> Revoir</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </div>
      )}
      <HandReplayer handId={replayHand} open={replayHand !== null} onClose={() => setReplayHand(null)} />
    </>
  );
}
