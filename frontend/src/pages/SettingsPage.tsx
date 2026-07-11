import { useEffect, useState } from "react";
import {
  Archive,
  Bot,
  Check,
  Database,
  Download,
  EyeOff,
  FileSearch,
  Folder,
  HardDriveDownload,
  KeyRound,
  MonitorCog,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  Upload,
  X
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState, PageHeader, SectionCard, StatusPill } from "../components/Ui";
import { ContributionPanel } from "../components/ContributionPanel";
import { useSafety } from "../contexts/SafetyContext";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { ActionResult, AppSettings, ThemeMode } from "../types";
import { formatDate, formatNumber } from "../utils/format";

const thresholdLabels: Record<string, string> = {
  limp_fold_pct: "Limp-fold trop fréquent",
  oop_call_pct: "Calls hors position",
  vpip_pct: "VPIP élevé",
  pfr_min_pct: "PFR faible",
  vpip_pfr_gap_pct: "Écart VPIP / PFR",
  button_vpip_min_pct: "Sous-utilisation du bouton",
  bb_fold_pct: "Folds en grosse blinde",
  short_call_shove_pct: "Calls de shove à faible stack",
  invested_fold_pct: "Folds après fort investissement",
  cbet_pct: "C-bet automatique",
  fold_to_cbet_pct: "Abandon face aux c-bets",
  turn_aggression_min_pct: "Passivité à la turn",
  river_hero_call_pct: "Hero calls river",
  heads_up_win_min_pct: "Résultats heads-up",
  third_place_pct: "Éliminations en 3e place"
};

const fallbackSettings: AppSettings = {
  history_paths: [],
  hero_name: "",
  import_delay_seconds: 10,
  currency: "EUR",
  session_gap_minutes: 30,
  leak_thresholds: {
    limp_fold_pct: 50,
    oop_call_pct: 35,
    vpip_pct: 65,
    pfr_min_pct: 25,
    vpip_pfr_gap_pct: 25,
    button_vpip_min_pct: 65,
    bb_fold_pct: 65,
    short_call_shove_pct: 35,
    invested_fold_pct: 25,
    cbet_pct: 80,
    fold_to_cbet_pct: 65,
    turn_aggression_min_pct: 25,
    river_hero_call_pct: 40,
    heads_up_win_min_pct: 45,
    third_place_pct: 45
  },
  autostart: false,
  theme: "dark",
  anonymize_exports: true,
  ai_analysis_enabled: false
};

function applyTheme(theme: ThemeMode) {
  localStorage.setItem("winamax-analyzer-theme", theme);
  document.documentElement.dataset.theme = theme === "system" ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : theme;
}

export function SettingsPage() {
  const { status, error: safetyError, refresh: refreshSafety } = useSafety();
  const { data, loading, error, reload } = useApi(() => api.settings(), []);
  const [settings, setSettings] = useState<AppSettings>(fallbackSettings);
  const [newPath, setNewPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [action, setAction] = useState<{ type: string; loading: boolean; result?: ActionResult; error?: string }>({ type: "", loading: false });

  useEffect(() => {
    if (!data) return;
    setSettings({
      ...fallbackSettings,
      ...data,
      history_paths: data.history_paths ?? [],
      leak_thresholds: { ...fallbackSettings.leak_thresholds, ...(data.leak_thresholds ?? {}) }
    });
    applyTheme(data.theme ?? "dark");
  }, [data]);

  function change<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setSettings((current) => ({ ...current, [key]: value }));
    if (key === "theme") applyTheme(value as ThemeMode);
  }

  function addPath() {
    const path = newPath.trim();
    if (!path || settings.history_paths.includes(path)) return;
    change("history_paths", [...settings.history_paths, path]);
    setNewPath("");
  }

  async function saveSettings() {
    setSaving(true);
    setSaveMessage("");
    try {
      const saved = await api.updateSettings(settings);
      setSettings({ ...settings, ...saved });
      setSaveMessage("Paramètres enregistrés.");
      refreshSafety();
    } catch (reason) {
      setSaveMessage(reason instanceof Error ? reason.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
  }

  async function runAction(type: string, operation: () => Promise<ActionResult>) {
    setAction({ type, loading: true });
    try {
      const result = await operation();
      setAction({ type, loading: false, result });
      refreshSafety();
    } catch (reason) {
      setAction({ type, loading: false, error: reason instanceof Error ? reason.message : "Opération impossible." });
    }
  }

  async function restore() {
    setAction({ type: "restore", loading: true });
    try {
      const backups = await api.listBackups();
      if (!backups.length) {
        setAction({ type: "restore", loading: false, error: "Aucune sauvegarde locale disponible." });
        return;
      }
      const names = backups.map((item) => typeof item === "string" ? item : String(item.name ?? item.filename ?? "")).filter(Boolean);
      const selected = window.prompt(`Sauvegardes disponibles :\n${names.join("\n")}\n\nSaisissez le nom exact à restaurer :`, names[0]);
      if (!selected) {
        setAction({ type: "", loading: false });
        return;
      }
      if (!names.includes(selected) || !window.confirm("Restaurer cette base remplacera les données locales actuelles. Continuer ?")) {
        setAction({ type: "restore", loading: false, error: names.includes(selected) ? undefined : "Nom de sauvegarde invalide." });
        return;
      }
      const result = await api.restoreDatabase(selected);
      setAction({ type: "restore", loading: false, result });
    } catch (reason) {
      setAction({ type: "restore", loading: false, error: reason instanceof Error ? reason.message : "Restauration impossible." });
    }
  }

  async function deleteData() {
    const confirmation = window.prompt("Cette action supprime les données analysées. Saisissez SUPPRIMER pour confirmer.");
    if (confirmation !== "SUPPRIMER") return;
    await runAction("delete", () => api.deleteData());
  }

  if (loading) return <LoadingState label="Chargement des paramètres…" />;
  if (error) return <ErrorState error={error} retry={reload} />;

  return (
    <>
      <PageHeader
        eyebrow="Configuration locale"
        title="Paramètres"
        description="Toutes les préférences et données restent sur cet ordinateur. Aucun identifiant Winamax n’est nécessaire."
        actions={<button className="button primary" onClick={saveSettings} disabled={saving} type="button"><Save size={17} /> {saving ? "Enregistrement…" : "Enregistrer"}</button>}
      />
      {saveMessage && <div className={`toast-inline ${saveMessage.includes("enregistrés") ? "success" : "error"}`} role="status">{saveMessage.includes("enregistrés") && <Check size={17} />}{saveMessage}</div>}

      <div className="settings-grid">
        <div className="settings-main">
          <SectionCard title="Import Winamax" subtitle="Après le contrôle de Winamax.exe, la garde fichiers exige des historiques stables et des tournois terminés." className="settings-section">
            <div className="setting-row vertical">
              <div className="setting-label"><Folder /><div><strong>Dossiers d’historique</strong><small>Vous pouvez surveiller plusieurs dossiers, y compris un dossier Documents redirigé vers OneDrive.</small></div></div>
              <div className="path-list">
                {settings.history_paths.length ? settings.history_paths.map((path) => (
                  <div className="path-item" key={path}><code>{path}</code><button className="icon-button" type="button" onClick={() => change("history_paths", settings.history_paths.filter((item) => item !== path))} aria-label={`Retirer ${path}`}><X size={16} /></button></div>
                )) : <EmptyState title="Aucun dossier configuré" description="Ajoutez le dossier contenant vos historiques et résumés Winamax." />}
              </div>
              <div className="path-input"><input value={newPath} onChange={(event) => setNewPath(event.target.value)} onKeyDown={(event) => event.key === "Enter" && (event.preventDefault(), addPath())} placeholder="C:\Users\…\Documents\Winamax Poker\accounts\pseudo\history" aria-label="Nouveau dossier d’historique" /><button className="button secondary" type="button" onClick={addPath}><Plus size={16} /> Ajouter</button></div>
            </div>
            <div className="settings-form-grid">
              <label>Pseudo du héros<input value={settings.hero_name} onChange={(event) => change("hero_name", event.target.value)} placeholder="Votre pseudo exact" autoComplete="off" /></label>
              <label>Délai avant import (secondes)<input type="number" min="10" max="600" value={settings.import_delay_seconds} onChange={(event) => change("import_delay_seconds", Math.max(10, Number(event.target.value)))} /><small>10 secondes minimum de stabilité.</small></label>
              <label>Devise<select value={settings.currency} onChange={(event) => change("currency", event.target.value)}><option value="EUR">Euro (€)</option><option value="USD">Dollar ($)</option><option value="GBP">Livre (£)</option></select></label>
              <label>Séparation des sessions (minutes)<input type="number" min="1" max="240" value={settings.session_gap_minutes} onChange={(event) => change("session_gap_minutes", Number(event.target.value))} /></label>
            </div>
          </SectionCard>

          <SectionCard title="Apparence et démarrage" className="settings-section">
            <div className="settings-form-grid">
              <label>Thème<select value={settings.theme} onChange={(event) => change("theme", event.target.value as ThemeMode)}><option value="dark">Sombre</option><option value="light">Clair</option><option value="system">Système</option></select></label>
              <label className="toggle-setting"><span><MonitorCog /><span><strong>Préférence de démarrage</strong><small>Préférence enregistrée uniquement. Aucune relance automatique; tout lancement reste refusé si Winamax.exe est présent.</small></span></span><input type="checkbox" role="switch" checked={settings.autostart} onChange={(event) => change("autostart", event.target.checked)} /></label>
            </div>
          </SectionCard>

          <SectionCard title="Seuils du moteur de leaks" subtitle="Ces repères sont configurables et ne constituent pas une stratégie GTO absolue." className="settings-section" >
            <div id="leak-thresholds" className="threshold-grid">
              {Object.entries(settings.leak_thresholds).map(([key, value]) => (
                <label key={key}><span>{thresholdLabels[key] ?? key.replaceAll("_", " ")}</span><div><input type="number" min="0" max="100" step="0.5" value={value} onChange={(event) => change("leak_thresholds", { ...settings.leak_thresholds, [key]: Number(event.target.value) })} /><span>%</span></div></label>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Analyse IA facultative" subtitle="Désactivée par défaut et jamais nécessaire au fonctionnement de l’application." className="settings-section">
            <div className="ai-setting">
              <Bot aria-hidden="true" />
              <div><strong>Préparer l’analyse pédagogique externe</strong><p>Une confirmation explicite sera toujours demandée avant l’envoi d’une main terminée. Les adversaires seront pseudonymisés et les données exactes affichées avant l’envoi.</p><small><KeyRound size={14} /> La clé API doit rester dans une variable d’environnement.</small></div>
              <input type="checkbox" role="switch" aria-label="Activer l’option d’analyse IA" checked={settings.ai_analysis_enabled ?? false} onChange={(event) => change("ai_analysis_enabled", event.target.checked)} />
            </div>
          </SectionCard>

          <ContributionPanel />

          <SectionCard title="Sauvegarde, restauration et export" className="settings-section">
            <div className="data-actions">
              <button className="action-tile" type="button" disabled={action.loading} onClick={() => runAction("backup", api.backupDatabase)}><Archive /><span><strong>Sauvegarder la base</strong><small>Crée une copie datée de SQLite.</small></span></button>
              <button className="action-tile" type="button" disabled={action.loading} onClick={restore}><Upload /><span><strong>Restaurer une base</strong><small>Choisissez une sauvegarde créée localement.</small></span></button>
              <a className="action-tile" href={api.exportTournamentsUrl(settings.anonymize_exports)} download><Download /><span><strong>Exporter les parties</strong><small>Fichier CSV local.</small></span></a>
            </div>
            <label className="toggle-setting export-toggle"><span><EyeOff /><span><strong>Minimiser les exports</strong><small>Retire pseudos, identifiants, dates exactes, noms de format libres et notes sensibles.</small></span></span><input type="checkbox" role="switch" checked={settings.anonymize_exports} onChange={(event) => change("anonymize_exports", event.target.checked)} /></label>
            {action.result && <p className="action-feedback success-text"><Check size={15} /> {action.result.message ?? "Opération terminée."}{action.result.path ? ` — ${action.result.path}` : ""}</p>}
            {action.error && <p className="action-feedback error-text">{action.error}</p>}
          </SectionCard>

          <SectionCard title="Zone sensible" className="settings-section danger-section">
            <div className="danger-row"><div><Trash2 /><span><strong>Supprimer les données analysées</strong><small>Les fichiers Winamax originaux ne sont jamais modifiés. Une confirmation textuelle est requise.</small></span></div><button className="button danger" onClick={deleteData} disabled={action.loading} type="button">Supprimer les données</button></div>
          </SectionCard>
        </div>

        <aside className="settings-sidebar">
          <SectionCard title="État de l’import">
            <div className="import-status-card">
              <div className="status-main">
                <span className={`watch-dot ${status?.watching && !safetyError ? "online" : ""}`} />
                <div>
                  <strong>{safetyError ? "Analyseur arrêté ou indisponible" : status?.watching ? "Watcher confirmé actif" : "État du watcher non confirmé"}</strong>
                  <small>
                    {safetyError
                      ? "Si Winamax est ouvert, fermez-le puis relancez manuellement l’application."
                      : status?.message ?? "Les chemins configurés ne suffisent pas à déclarer le watcher actif."}
                  </small>
                </div>
              </div>
              <dl><div><dt>Importés</dt><dd>{formatNumber(status?.imported_files)}</dd></div><div><dt>En attente</dt><dd>{formatNumber(status?.pending_files)}</dd></div><div><dt>Échecs</dt><dd>{formatNumber(status?.failed_files)}</dd></div><div><dt>Dernier import</dt><dd>{formatDate(status?.last_import_at, true)}</dd></div></dl>
              <button className="button secondary full-width" type="button" disabled={action.loading} onClick={() => runAction("rescan", api.rescan)}><RefreshCw className={action.loading && action.type === "rescan" ? "spin" : ""} size={17} /> Rescanner les fichiers</button>
            </div>
          </SectionCard>

          <SectionCard title="Protection active">
            <div className="privacy-checklist">
              <p><ShieldCheck /> <span><strong>Interverrouillage Winamax</strong><small>Démarrage refusé et arrêt du watcher/backend si Winamax.exe est détecté.</small></span></p>
              <p><FileSearch /> <span><strong>Seconde garde fichiers</strong><small>Stabilité, résumé et classement final restent obligatoires.</small></span></p>
              <p><Database /> <span><strong>Base locale</strong><small>SQLite, aucune télémétrie.</small></span></p>
              <p><HardDriveDownload /> <span><strong>Fichiers préservés</strong><small>Aucune modification de Winamax.</small></span></p>
            </div>
          </SectionCard>

          <SectionCard title="Accès local">
            <div className="localhost-box"><code>http://127.0.0.1:8000</code><StatusPill tone="positive">Local uniquement</StatusPill></div>
          </SectionCard>
        </aside>
      </div>
    </>
  );
}
