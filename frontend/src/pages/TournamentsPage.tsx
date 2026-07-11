import { useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination, StatusPill } from "../components/Ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { formatDate, formatDuration, formatMoney, formatNumber } from "../utils/format";

export function TournamentsPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ search: "", buy_in: "", rank: "", multiplier: "", status: "" });
  const { data, loading, error, reload } = useApi(
    () => api.tournaments({ ...filters, page, page_size: 25 }),
    [page, filters.search, filters.buy_in, filters.rank, filters.multiplier, filters.status]
  );

  function updateFilter(key: keyof typeof filters, value: string) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  return (
    <>
      <PageHeader eyebrow="Historique" title="Parties" description="Toutes les parties Expresso terminées et importées, sans données de jeu en direct." />
      <section className="filter-bar compact-filters" aria-label="Filtres des parties">
        <label className="search-field"><span>Recherche</span><div><Search size={16} /><input value={filters.search} onChange={(event) => updateFilter("search", event.target.value)} placeholder="ID, nom…" /></div></label>
        <label>Buy-in<select value={filters.buy_in} onChange={(event) => updateFilter("buy_in", event.target.value)}><option value="">Tous</option><option value="1">1 €</option><option value="2">2 €</option><option value="5">5 €</option></select></label>
        <label>Multiplicateur<input value={filters.multiplier} onChange={(event) => updateFilter("multiplier", event.target.value)} placeholder="Tous" /></label>
        <label>Classement<select value={filters.rank} onChange={(event) => updateFilter("rank", event.target.value)}><option value="">Tous</option><option value="1">1er</option><option value="2">2e</option><option value="3">3e</option></select></label>
        <label>Analyse<select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}><option value="">Tous</option><option value="complete">Analysée</option><option value="imported">Importée</option><option value="partial">Partielle</option><option value="insufficient">Données insuffisantes</option></select></label>
      </section>

      {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={reload} /> : !data?.items.length ? <EmptyState title="Aucune partie trouvée" /> : (
        <section className="section-card table-card">
          <div className="table-scroll">
            <table className="data-table tournaments-table">
              <thead><tr><th>Date</th><th>Buy-in</th><th>Multi.</th><th>Prize pool</th><th>Place</th><th>Gain</th><th>Net</th><th>Durée</th><th>Mains</th><th>chipEV</th><th>Tags</th><th>Analyse</th><th><span className="sr-only">Ouvrir</span></th></tr></thead>
              <tbody>
                {data.items.map((tournament) => (
                  <tr key={tournament.id}>
                    <td><Link className="table-primary-link" to={`/parties/${tournament.id}`}>{formatDate(tournament.started_at, true)}<small>#{tournament.tournament_id ?? tournament.id}</small></Link></td>
                    <td>{formatMoney(tournament.buy_in, tournament.currency ?? "EUR")}</td>
                    <td>{tournament.multiplier ? `×${tournament.multiplier}` : "—"}</td>
                    <td>{formatMoney(tournament.prize_pool, tournament.currency ?? "EUR")}</td>
                    <td><span className={`rank-medal rank-${tournament.rank}`}>{tournament.rank ? `${tournament.rank}${tournament.rank === 1 ? "er" : "e"}` : "—"}</span></td>
                    <td>{formatMoney(tournament.reward, tournament.currency ?? "EUR")}</td>
                    <td className={tournament.net_result >= 0 ? "value-positive" : "value-negative"}>{formatMoney(tournament.net_result, tournament.currency ?? "EUR", true)}</td>
                    <td>{formatDuration(tournament.duration_minutes)}</td><td>{formatNumber(tournament.hands_count)}</td>
                    <td>{tournament.chipev === null || tournament.chipev === undefined ? <span title="Données insuffisantes">—</span> : formatNumber(tournament.chipev, 1)}</td>
                    <td><div className="tag-list">{tournament.tags?.slice(0, 2).map((tag: string) => <span className="tag" key={tag}>{tag}</span>) ?? "—"}</div></td>
                    <td><StatusPill tone={tournament.analysis_status === "complete" ? "positive" : "warning"}>{tournament.analysis_status === "complete" ? "Analysée" : tournament.analysis_status === "imported" ? "Importée" : tournament.analysis_status ?? "En attente"}</StatusPill></td>
                    <td><Link className="icon-button" to={`/parties/${tournament.id}`} aria-label={`Ouvrir la partie ${tournament.tournament_id ?? tournament.id}`}><ChevronRight size={18} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={data.page || page} total={data.total} pageSize={data.page_size || 25} onPage={setPage} />
        </section>
      )}
    </>
  );
}
