import { useState } from "react";
import { Filter, Play, Search } from "lucide-react";
import { HandReplayer } from "../components/HandReplayer";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination, StatusPill } from "../components/Ui";
import { useSafety } from "../contexts/SafetyContext";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { formatDate, formatNumber, joinCards } from "../utils/format";

const initialFilters = { query: "", cards: "", position: "", stack: "", preflop: "", postflop: "", all_in: "", showdown: "", leak: "", result: "", min_pot_bb: "" };

export function HandsPage() {
  const [filters, setFilters] = useState(initialFilters);
  const [page, setPage] = useState(1);
  const [replayHand, setReplayHand] = useState<number | string | null>(null);
  const { safeToAnalyze } = useSafety();
  const { data, loading, error, reload } = useApi(
    () => api.hands({ ...filters, page, page_size: 30 }),
    [page, filters.query, filters.cards, filters.position, filters.stack, filters.preflop, filters.postflop, filters.all_in, filters.showdown, filters.leak, filters.result, filters.min_pot_bb]
  );

  function setFilter(key: keyof typeof initialFilters, value: string) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  return (
    <>
      <PageHeader eyebrow="Explorateur" title="Mains" description="Recherchez les situations à revoir et séparez la qualité supposée de la décision de son résultat." />
      <section className="hands-search-panel">
        <div className="global-search"><Search aria-hidden="true" /><input value={filters.query} onChange={(event) => setFilter("query", event.target.value)} placeholder="Ex. AK, moins de 10 BB, call de shove, top paire, pot > 20 BB…" aria-label="Recherche en texte libre" /></div>
        <div className="advanced-filters">
          <div className="filter-title"><Filter size={17} /><strong>Filtres précis</strong></div>
          <label>Cartes<input value={filters.cards} onChange={(event) => setFilter("cards", event.target.value)} placeholder="AK, QJs…" /></label>
          <label>Position<select value={filters.position} onChange={(event) => setFilter("position", event.target.value)}><option value="">Toutes</option><option>BTN</option><option>SB</option><option>BB</option></select></label>
          <label>Profondeur<select value={filters.stack} onChange={(event) => setFilter("stack", event.target.value)}><option value="">Toutes</option><option value="0-5">0–5 BB</option><option value="5-10">5–10 BB</option><option value="10-15">10–15 BB</option><option value="15-25">15–25 BB</option><option value="25+">25+ BB</option></select></label>
          <label>Préflop<select value={filters.preflop} onChange={(event) => setFilter("preflop", event.target.value)}><option value="">Toutes</option><option value="limp">Limp</option><option value="open_raise">Open-raise</option><option value="3bet">3-bet</option><option value="shove">Shove</option><option value="call_shove">Call de shove</option></select></label>
          <label>Postflop<select value={filters.postflop} onChange={(event) => setFilter("postflop", event.target.value)}><option value="">Toutes</option><option value="cbet">C-bet</option><option value="check_raise">Check-raise</option><option value="hero_call_river">Hero call river</option></select></label>
          <label>All-in<select value={filters.all_in} onChange={(event) => setFilter("all_in", event.target.value)}><option value="">Tous</option><option value="true">Oui</option><option value="false">Non</option></select></label>
          <label>Showdown<select value={filters.showdown} onChange={(event) => setFilter("showdown", event.target.value)}><option value="">Tous</option><option value="true">Oui</option><option value="false">Non</option></select></label>
          <label>Résultat<select value={filters.result} onChange={(event) => setFilter("result", event.target.value)}><option value="">Tous</option><option value="won">Gagnée</option><option value="lost">Perdue</option></select></label>
          <label>Pot minimum<input type="number" min="0" value={filters.min_pot_bb} onChange={(event) => setFilter("min_pot_bb", event.target.value)} placeholder="BB" /></label>
          <label>Leak<select value={filters.leak} onChange={(event) => setFilter("leak", event.target.value)}><option value="">Tous</option><option value="true">Détecté</option><option value="false">Aucun</option></select></label>
          <button className="button ghost compact" type="button" onClick={() => setFilters(initialFilters)}>Effacer</button>
        </div>
      </section>

      {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={reload} /> : !data?.items.length ? <EmptyState title="Aucune main ne correspond" description="Essayez une recherche moins restrictive ou importez de nouvelles parties terminées." /> : (
        <section className="section-card table-card">
          <div className="table-scroll">
            <table className="data-table hands-table">
              <thead><tr><th>Main</th><th>Cartes</th><th>Pos.</th><th>Prof.</th><th>Préflop</th><th>Postflop</th><th>Board</th><th>Pot</th><th>Résultat</th><th>Classification</th><th>Leaks</th><th><span className="sr-only">Revoir</span></th></tr></thead>
              <tbody>
                {data.items.map((hand) => (
                  <tr key={hand.id}>
                    <td><strong>#{hand.hand_id ?? hand.id}</strong><small className="table-subline">{formatDate(hand.played_at, true)}</small></td>
                    <td className="cards-text">{joinCards(hand.hero_cards)}</td><td>{hand.position ?? "—"}</td><td>{hand.effective_stack_bb ? `${formatNumber(hand.effective_stack_bb, 1)} BB` : "—"}</td>
                    <td>{hand.preflop_action ?? "—"}</td><td>{hand.postflop_action ?? "—"}</td><td className="cards-text">{joinCards(hand.board)}</td><td>{hand.pot_bb ? `${formatNumber(hand.pot_bb, 1)} BB` : "—"}</td>
                    <td className={(hand.net_result_chips ?? 0) >= 0 ? "value-positive" : "value-negative"}>{formatNumber(hand.net_result_chips)} j</td>
                    <td><StatusPill tone={hand.classification === "standard" ? "positive" : hand.classification?.includes("insuffis") ? "neutral" : "warning"}>{hand.classification ?? "Non classée"}</StatusPill></td>
                    <td>{hand.leak_count ? <StatusPill tone="negative">{hand.leak_count} signal{hand.leak_count > 1 ? "ements" : "ement"}</StatusPill> : "—"}</td>
                    <td><button className="icon-button replay-button" type="button" onClick={() => setReplayHand(hand.id)} disabled={!safeToAnalyze} aria-label={`Revoir la main ${hand.hand_id ?? hand.id}`} title={!safeToAnalyze ? "Analyse verrouillée : fin de tournoi non confirmée" : "Ouvrir le replayer"}><Play size={17} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={data.page || page} total={data.total} pageSize={data.page_size || 30} onPage={setPage} />
        </section>
      )}
      <HandReplayer handId={replayHand} open={replayHand !== null} onClose={() => setReplayHand(null)} />
    </>
  );
}
