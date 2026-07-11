import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  ChevronRight,
  CircleStop,
  Files,
  Hand,
  Menu,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  X
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { SafetyContext } from "../contexts/SafetyContext";
import { api } from "../services/api";
import type { ImportStatus } from "../types";
import { formatDate } from "../utils/format";

const navigation = [
  { to: "/", label: "Tableau de bord", icon: BarChart3, end: true },
  { to: "/parties", label: "Parties", icon: Files },
  { to: "/mains", label: "Mains", icon: Hand },
  { to: "/sessions", label: "Sessions", icon: Activity },
  { to: "/leaks", label: "Leaks", icon: BrainCircuit },
  { to: "/parametres", label: "Paramètres", icon: Settings }
];

const routeTitles: Record<string, string> = {
  "/": "Vue d’ensemble",
  "/parties": "Historique des parties",
  "/mains": "Explorateur de mains",
  "/sessions": "Sessions",
  "/leaks": "Analyse des leaks",
  "/parametres": "Paramètres"
};

function deriveSafeState(status: ImportStatus | null, error: Error | null): boolean {
  if (!status || error) return false;
  if (status.safe_to_analyze === false || status.tournament_active) return false;
  if (status.safe_to_analyze === true) return true;
  return status.active_files === 0;
}

export function AppLayout() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [status, setStatus] = useState<ImportStatus | null>(null);
  const [statusError, setStatusError] = useState<Error | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  const refreshStatus = useCallback(() => {
    setStatusLoading(true);
    api
      .importStatus()
      .then((next) => {
        setStatus(next);
        setStatusError(null);
      })
      .catch((reason: unknown) => setStatusError(reason instanceof Error ? reason : new Error(String(reason))))
      .finally(() => setStatusLoading(false));
  }, []);

  useEffect(() => {
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 15_000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const stored = localStorage.getItem("winamax-analyzer-theme") ?? "dark";
    document.documentElement.dataset.theme = stored === "system" ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : stored;
  }, []);

  const safeToAnalyze = deriveSafeState(status, statusError);
  const currentTitle = location.pathname.startsWith("/parties/") ? "Détail de la partie" : routeTitles[location.pathname] ?? "RiverScope";

  return (
    <SafetyContext.Provider value={{ status, loading: statusLoading, error: statusError, safeToAnalyze, refresh: refreshStatus }}>
      <div className="app-shell">
        <aside className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Navigation principale">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <span>R</span>
            </div>
            <div>
              <strong>RiverScope</strong>
              <small>Expresso · local</small>
            </div>
            <button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Fermer le menu" type="button">
              <X />
            </button>
          </div>

          <div className="compliance-card">
            <ShieldCheck size={20} aria-hidden="true" />
            <div>
              <strong>Post-session uniquement</strong>
              <span>Arrêt total si Winamax.exe est détecté.</span>
            </div>
          </div>

          <nav className="nav-list">
            {navigation.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? "active" : undefined)}>
                <Icon size={19} aria-hidden="true" />
                <span>{label}</span>
                <ChevronRight className="nav-chevron" size={15} aria-hidden="true" />
              </NavLink>
            ))}
          </nav>

          <div className="sidebar-footer">
            <span className={`watch-dot ${status?.watching && !statusError ? "online" : ""}`} aria-hidden="true" />
            <div>
              <strong>
                {statusError
                  ? "Analyseur arrêté ou indisponible"
                  : status?.watching
                    ? "Watcher confirmé actif"
                    : status
                      ? "Backend local joignable"
                      : "État non confirmé"}
              </strong>
              <small>
                {statusError
                  ? "Fermez Winamax puis relancez manuellement."
                  : status?.last_import_at
                    ? `Import ${formatDate(status.last_import_at, true)}`
                    : "Aucun import récent"}
              </small>
            </div>
          </div>
        </aside>
        {menuOpen && <button className="sidebar-backdrop" aria-label="Fermer le menu" onClick={() => setMenuOpen(false)} type="button" />}

        <div className="main-column">
          <header className="topbar">
            <button className="icon-button menu-button" onClick={() => setMenuOpen(true)} aria-label="Ouvrir le menu" type="button">
              <Menu />
            </button>
            <div>
              <p className="topbar-kicker">Analyse locale</p>
              <strong>{currentTitle}</strong>
            </div>
            <div className="topbar-status">
              <SlidersHorizontal size={16} aria-hidden="true" />
              <span>127.0.0.1</span>
            </div>
          </header>

          {!safeToAnalyze && (
            <div className={`safety-banner ${statusError ? "error" : "warning"}`} role="status">
              {statusError ? <AlertTriangle aria-hidden="true" /> : <CircleStop aria-hidden="true" />}
              <div>
                <strong>{statusError ? "Analyseur arrêté ou indisponible" : "Analyse temporairement verrouillée"}</strong>
                <span>
                  {statusError
                    ? "Si Winamax.exe est ouvert, fermez-le puis relancez manuellement start.ps1. Aucun redémarrage automatique n’est effectué."
                    : "La seconde garde a trouvé un fichier récent, incomplet ou en attente. L’application attend la fin confirmée du tournoi."}
                </span>
              </div>
              <button className="button compact" onClick={refreshStatus} type="button">
                Vérifier
              </button>
            </div>
          )}

          <main className="page-content">
            <Outlet />
          </main>
          <footer className="app-footer">
            <span>Données stockées localement · aucune télémétrie</span>
            <span>Analyse post-session responsable</span>
          </footer>
        </div>
      </div>
    </SafetyContext.Provider>
  );
}
