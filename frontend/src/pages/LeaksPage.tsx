import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusPill } from "../components/Ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { LeakFlag } from "../types";
import { formatNumber, formatPercent, severityLabel } from "../utils/format";

function severityTone(severity: string): "negative" | "warning" | "info" | "neutral" {
  if (["critical", "high"].includes(severity)) return "negative";
  if (severity === "medium") return "warning";
  if (severity === "low") return "info";
  return "neutral";
}

export function LeaksPage() {
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [expanded, setExpanded] = useState<number | string | null>(null);
  const { data, loading, error, reload } = useApi(() => api.leaks({ severity, category }), [severity, category]);
  const leaks = data?.items ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Moteur transparent"
        title="Leaks détectés"
        description="Des signaux statistiques configurables, jamais des vérités GTO ni des jugements basés sur une main perdue."
        actions={<div className="header-filters"><select aria-label="Gravité" value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">Toutes les gravités</option><option value="high">Élevée</option><option value="medium">Modérée</option><option value="low">Faible</option></select><select aria-label="Catégorie" value={category} onChange={(event) => setCategory(event.target.value)}><option value="">Toutes les catégories</option><option value="preflop">Préflop</option><option value="postflop">Postflop</option><option value="results">Résultats</option></select></div>}
      />

      <div className="method-banner">
        <ShieldAlert aria-hidden="true" />
        <div><strong>Comment lire ces alertes ?</strong><p>Un signal combine une statistique observée, un seuil modifiable, un nombre d’occurrences et un niveau de confiance. Vérifiez toujours les mains concernées et le contexte de stack.</p></div>
        <Link className="button ghost compact" to="/parametres#leak-thresholds">Configurer les seuils</Link>
      </div>

      {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={reload} /> : !leaks.length ? (
        <EmptyState title="Aucun signal avec ces filtres" description="Cela ne prouve pas un jeu parfait : l’échantillon peut être insuffisant." action={<CheckCircle2 className="value-positive" />} />
      ) : (
        <div className="leaks-list">
          {leaks.map((leak: LeakFlag) => {
            const open = expanded === leak.id;
            const unit = leak.unit === "percent" || leak.unit === "%" ? "%" : leak.unit ?? "";
            return (
              <article className={`leak-card severity-${leak.severity}`} key={leak.id}>
                <button className="leak-summary" type="button" aria-expanded={open} onClick={() => setExpanded(open ? null : leak.id)}>
                  <span className="leak-icon"><AlertTriangle aria-hidden="true" /></span>
                  <div className="leak-title"><span>{leak.category ?? "Analyse"}</span><strong>{leak.name}</strong></div>
                  <StatusPill tone={severityTone(leak.severity)}>{severityLabel(leak.severity)}</StatusPill>
                  <div><small>Observé</small><strong>{unit === "%" ? formatPercent(leak.observed_value) : `${formatNumber(leak.observed_value, 1)} ${unit}`}</strong></div>
                  <div><small>Seuil</small><strong>{unit === "%" ? formatPercent(leak.threshold) : `${formatNumber(leak.threshold, 1)} ${unit}`}</strong></div>
                  <div><small>Occurrences</small><strong>{formatNumber(leak.occurrences)} / {formatNumber(leak.sample_size)}</strong></div>
                  <div className="confidence"><small>Confiance</small><span><i style={{ width: `${Math.min(100, Math.max(0, leak.confidence))}%` }} /></span><strong>{formatPercent(leak.confidence, 0)}</strong></div>
                  <ChevronDown className={open ? "open" : ""} />
                </button>
                {open && (
                  <div className="leak-details">
                    <div><h3>Pourquoi ce signal ?</h3><p>{leak.explanation}</p></div>
                    <div><h3>Piste de travail générale</h3><p>{leak.recommendation}</p></div>
                    <div className="leak-hands"><h3>Mains concernées</h3>{leak.hand_ids?.length ? <Link className="button secondary compact" to={`/mains?leak=${encodeURIComponent(String(leak.id))}`}>Voir {leak.hand_ids.length} mains <ExternalLink size={14} /></Link> : <p className="muted">Aucune référence de main disponible.</p>}</div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
