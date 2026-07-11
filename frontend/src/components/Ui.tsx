import type { ReactNode } from "react";
import { AlertTriangle, Inbox, LoaderCircle, RefreshCw } from "lucide-react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function LoadingState({ label = "Chargement des données…" }: { label?: string }) {
  return (
    <div className="state-panel" role="status" aria-live="polite">
      <LoaderCircle className="spin" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className="state-panel state-error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>Impossible de charger ces données</strong>
        <p>{error.message}</p>
      </div>
      {retry && (
        <button className="button secondary" onClick={retry} type="button">
          <RefreshCw size={16} aria-hidden="true" /> Réessayer
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title = "Aucune donnée pour le moment",
  description = "Importez une partie terminée ou modifiez les filtres.",
  action
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-panel empty-state">
      <Inbox aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

export function StatusPill({ tone = "neutral", children }: { tone?: "positive" | "negative" | "warning" | "info" | "neutral"; children: ReactNode }) {
  return <span className={`status-pill ${tone}`}>{children}</span>;
}

export function MetricCard({
  label,
  value,
  hint,
  tone = "default",
  icon
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "positive" | "negative" | "accent";
  icon?: ReactNode;
}) {
  return (
    <article className={`metric-card ${tone}`}>
      <div className="metric-card-top">
        <span>{label}</span>
        {icon && <span className="metric-icon">{icon}</span>}
      </div>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </article>
  );
}

export function SectionCard({ title, subtitle, action, children, className = "" }: { title?: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`section-card ${className}`}>
      {(title || action) && (
        <header className="section-card-header">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Pagination({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <nav className="pagination" aria-label="Pagination">
      <button className="button ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} type="button">
        Précédent
      </button>
      <span>
        Page {page} sur {pages}
      </span>
      <button className="button ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} type="button">
        Suivant
      </button>
    </nav>
  );
}
