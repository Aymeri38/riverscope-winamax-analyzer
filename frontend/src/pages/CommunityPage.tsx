import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  CloudUpload,
  Database,
  Eye,
  LoaderCircle,
  LogOut,
  Play,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  UserRoundSearch,
  Users
} from "lucide-react";
import { CommunityOpponents } from "../components/CommunityOpponents";
import { HandReplayer } from "../components/HandReplayer";
import { CommunityContributorProfileView } from "../components/CommunityContributorProfile";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Pagination, SectionCard, StatusPill } from "../components/Ui";
import { useSafety } from "../contexts/SafetyContext";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { CommunityHand, CommunityStatus } from "../types";
import { formatDate, formatDuration, formatMoney, formatNumber, joinCards } from "../utils/format";

const CONSENT_VERSION = "2";
type CommunityView = "overview" | "tournaments" | "hands" | "opponents";

function syncTone(state: string): "positive" | "negative" | "warning" | "info" | "neutral" {
  if (["synced", "success", "complete", "up_to_date"].includes(state)) return "positive";
  if (["failed", "error", "blocked"].includes(state)) return "negative";
  if (["pending", "waiting"].includes(state)) return "warning";
  if (["syncing", "running"].includes(state)) return "info";
  return "neutral";
}

function syncLabel(state: string): string {
  const labels: Record<string, string> = {
    idle: "En attente",
    pending: "Synchronisation requise",
    syncing: "Synchronisation en cours",
    running: "Synchronisation en cours",
    synced: "À jour",
    success: "À jour",
    complete: "À jour",
    up_to_date: "À jour",
    failed: "Échec",
    error: "Échec",
    blocked: "Bloquée"
  };
  return labels[state] ?? state;
}

function blockedReasonLabel(reason?: string | null): string {
  const labels: Record<string, string> = {
    pending_sync: "Vos parties terminées doivent être synchronisées avant l’accès aux données communes.",
    no_contribution: "Synchronisez au moins une partie terminée avant d’accéder aux données communes.",
    hub_offline: "Le serveur hôte du hub est actuellement injoignable.",
    activity_detected: "Une activité potentiellement en cours a été détectée ; l’accès reste fermé par précaution.",
    winamax_running: "Winamax.exe est détecté ; le backend communautaire reste arrêté.",
    consent_required: "Le consentement communautaire v2 doit être accepté explicitement avant tout suivi adverse.",
    consent_upgrade_required: "Le consentement communautaire v2 doit être accepté explicitement avant tout suivi adverse.",
    policy_upgrade_required: "Le consentement communautaire v2 doit être accepté explicitement avant tout suivi adverse.",
    not_configured: "Cette installation n’est pas encore associée à un hub."
  };
  return reason ? labels[reason] ?? "Le backend a bloqué l’accès communautaire par précaution." : "Le service communautaire n’est pas disponible dans l’état actuel.";
}

export function CommunityPage() {
  const { safeToAnalyze } = useSafety();
  const [status, setStatus] = useState<CommunityStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<Error | null>(null);
  const [actionLoading, setActionLoading] = useState<"join" | "sync" | "leave" | "consent" | null>(null);
  const [actionError, setActionError] = useState("");
  const [view, setView] = useState<CommunityView>("overview");
  const [contributorId, setContributorId] = useState("");
  const [tournamentsPage, setTournamentsPage] = useState(1);
  const [handsPage, setHandsPage] = useState(1);
  const [dataRevision, setDataRevision] = useState(0);
  const [replayHand, setReplayHand] = useState<CommunityHand | null>(null);

  const loadStatus = useCallback(async (showLoading = false) => {
    if (showLoading) setStatusLoading(true);
    try {
      const next = await api.communityStatus();
      setStatus(next);
      setStatusError(null);
    } catch (reason) {
      setStatusError(reason instanceof Error ? reason : new Error(String(reason)));
    } finally {
      if (showLoading) setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus(true);
    const timer = window.setInterval(() => void loadStatus(false), 2_000);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  const configured = status?.configured === true && status.available;
  const contributors = useApi(
    () => configured ? api.communityContributors() : Promise.resolve([]),
    [configured, dataRevision]
  );
  const dashboard = useApi(
    () => configured ? api.communityDashboard({ contributor_id: contributorId }) : Promise.resolve(null),
    [configured, contributorId, dataRevision]
  );
  const contributorProfile = useApi(
    () => configured && contributorId
      ? api.communityContributorProfile(contributorId)
      : Promise.resolve(null),
    [configured, contributorId, dataRevision]
  );
  const tournaments = useApi(
    () => configured ? api.communityTournaments({ contributor_id: contributorId, page: tournamentsPage, page_size: 25 }) : Promise.resolve({ items: [], total: 0, page: 1, page_size: 25 }),
    [configured, contributorId, tournamentsPage, dataRevision]
  );
  const hands = useApi(
    () => configured ? api.communityHands({ contributor_id: contributorId, page: handsPage, page_size: 30 }) : Promise.resolve({ items: [], total: 0, page: 1, page_size: 30 }),
    [configured, contributorId, handsPage, dataRevision]
  );

  const loadCommunityReplay = useCallback(
    (id: number | string) => api.communityReplay(replayHand?.replay_key ?? id, replayHand?.contributor_id),
    [replayHand]
  );

  function selectContributor(value: string) {
    setContributorId(value);
    if (value) setView("overview");
    setTournamentsPage(1);
    setHandsPage(1);
  }

  async function syncNow() {
    setActionLoading("sync");
    setActionError("");
    try {
      await api.communitySync();
      await loadStatus(false);
      setDataRevision((current) => current + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Synchronisation impossible.");
    } finally {
      setActionLoading(null);
    }
  }

  async function leaveCommunity() {
    if (!window.confirm("Retirer cette installation du hub communautaire ? Les données déjà partagées restent soumises à la politique du hub.")) return;
    setActionLoading("leave");
    setActionError("");
    try {
      const result = await api.communityLeave();
      if (!result.remote_revoked) {
        window.alert(result.message);
      }
      setContributorId("");
      setStatus(null);
      await loadStatus(true);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Déconnexion impossible.");
    } finally {
      setActionLoading(null);
    }
  }

  async function acceptOpponentTracking() {
    setActionLoading("consent");
    setActionError("");
    try {
      await api.communityConsent();
      await loadStatus(true);
      setDataRevision((current) => current + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Mise à jour du consentement impossible.");
    } finally {
      setActionLoading(null);
    }
  }

  if (statusLoading && !status) return <LoadingState label="Vérification de la configuration communautaire…" />;
  if (statusError) return <ErrorState error={statusError} retry={() => void loadStatus(true)} />;
  if (!status?.configured) {
    return <CommunityOnboarding onJoined={() => void loadStatus(true)} busy={actionLoading === "join"} setBusy={(busy) => setActionLoading(busy ? "join" : null)} />;
  }
  if (status.consent_upgrade_required) {
    return (
      <>
        <PageHeader
          eyebrow="Consentement communautaire v2 requis"
          title="Le suivi adverse change la portée du partage"
          description="Aucune donnée communautaire n’est chargée tant que vous n’avez pas accepté explicitement cette nouvelle politique."
        />
        <section className="community-consent-upgrade" aria-labelledby="community-consent-v2-title">
          <div className="community-consent-upgrade-heading">
            <ShieldCheck aria-hidden="true" />
            <div><span>Politique v2</span><h2 id="community-consent-v2-title">Transmission des pseudos adverses après la partie</h2></div>
          </div>
          <p>Votre installation a accepté la politique {status.consent_version ?? "antérieure"}. La politique {status.required_consent_version} exige une nouvelle action explicite pour les quatre traitements suivants :</p>
          <div className="community-consent-upgrade-grid">
            <article><Database /><div><strong>Tournois terminés uniquement</strong><small>Les pseudos adverses observés sont transmis au VPS seulement avec les données d’un tournoi complètement terminé.</small></div></article>
            <article><ShieldCheck /><div><strong>Chiffrement au repos</strong><small>Les pseudos affichables sont chiffrés dans le stockage du VPS et ne sont pas conservés en clair dans la base.</small></div></article>
            <article><Users /><div><strong>Rapprochement entre contributeurs</strong><small>Un même pseudo peut être rapproché entre plusieurs observations et devient visible uniquement aux membres contributeurs autorisés.</small></div></article>
            <article><Eye /><div><strong>Jamais en direct</strong><small>Aucune lecture, transmission ou consultation n’est permise pendant que Winamax ou une partie potentiellement active est détectée.</small></div></article>
          </div>
          <p className="community-consent-upgrade-warning"><AlertTriangle size={17} /> Ce changement reste désactivé tant que vous ne cliquez pas sur le bouton ci-dessous. Il n’existe aucun opt-in implicite.</p>
          {actionError && <p className="community-action-error" role="alert"><AlertTriangle size={16} />{actionError}</p>}
          <div className="community-consent-upgrade-actions">
            <button className="button ghost" type="button" onClick={() => void leaveCommunity()} disabled={actionLoading !== null}><LogOut size={16} /> Quitter le hub</button>
            <button className="button primary" type="button" onClick={() => void acceptOpponentTracking()} disabled={actionLoading !== null}>
              {actionLoading === "consent" ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}
              {actionLoading === "consent" ? "Activation…" : "Accepter et activer le suivi adverse"}
            </button>
          </div>
        </section>
      </>
    );
  }
  if (!status.available) {
    return (
      <>
        <PageHeader eyebrow="Protection post-session" title="Communauté indisponible" description="L’accès aux données partagées est bloqué tant que le backend local ne confirme pas que toutes les conditions post-session sont réunies." />
        <div className="community-storage-banner" role="note">
          <ShieldCheck aria-hidden="true" />
          <div><strong>Aucune donnée communautaire chargée</strong><span>{blockedReasonLabel(status.blocked_reason)}</span></div>
          <AlertTriangle aria-hidden="true" />
        </div>
        {actionError && <p className="community-action-error" role="alert"><AlertTriangle size={16} />{actionError}</p>}
        <div className="community-blocked-actions">
          <button className="button secondary" onClick={() => void loadStatus(true)} type="button"><RefreshCw size={16} /> Vérifier</button>
          <button className="button primary" onClick={() => void syncNow()} disabled={actionLoading === "sync"} type="button">
            {actionLoading === "sync" ? <LoaderCircle className="spin" size={16} /> : <CloudUpload size={16} />}
            {actionLoading === "sync" ? "Synchronisation…" : "Synchroniser mes parties terminées"}
          </button>
          <button className="button ghost" onClick={() => void leaveCommunity()} disabled={actionLoading !== null} type="button"><LogOut size={16} /> Quitter le hub</button>
        </div>
      </>
    );
  }

  const selectedContributor = contributors.data?.find((contributor) => contributor.id === contributorId);
  const selectionLabel = selectedContributor?.display_name ?? "Tous les contributeurs";
  const syncRunning = ["syncing", "running"].includes(status.sync.state) || actionLoading === "sync";

  return (
    <>
      <PageHeader
        eyebrow="Données partagées post-session"
        title="Communauté"
        description="Comparez les parties terminées des membres autorisés. La synchronisation de vos propres parties terminées est obligatoire pour conserver cet accès."
        actions={<StatusPill tone={syncTone(status.sync.state)}>{syncLabel(status.sync.state)}</StatusPill>}
      />

      <div className="community-storage-banner" role="note">
        <Server aria-hidden="true" />
        <div>
          <strong>Données centrales stockées sur le serveur de l’hôte du hub</strong>
          <span>Les parties entièrement terminées et les pseudos adverses observés sont synchronisés par les backends. Les pseudos sont chiffrés au repos ; le navigateur ne contacte jamais directement le hub.</span>
        </div>
        <ShieldCheck aria-hidden="true" />
      </div>

      <div className="community-toolbar">
        <label>
          Joueur affiché
          <select value={contributorId} onChange={(event) => selectContributor(event.target.value)}>
            <option value="">Tous les contributeurs</option>
            {contributors.data?.map((contributor) => (
              <option value={contributor.id} key={contributor.id}>{contributor.display_name}{contributor.is_self ? " (vous)" : ""}</option>
            ))}
          </select>
        </label>
        <div className="community-sync-summary">
          <CloudUpload aria-hidden="true" />
          <div>
            <strong>{status.sync.pending_tournaments} partie{status.sync.pending_tournaments === 1 ? "" : "s"} en attente</strong>
            <small>{status.sync.last_success_at ? `Dernier succès ${formatDate(status.sync.last_success_at, true)}` : "Aucune synchronisation réussie"}</small>
          </div>
        </div>
        <button className="button primary" type="button" onClick={() => void syncNow()} disabled={syncRunning}>
          {syncRunning ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}
          {syncRunning ? "Synchronisation…" : "Synchroniser"}
        </button>
        <button className="button ghost" type="button" onClick={() => void leaveCommunity()} disabled={actionLoading !== null}>
          <LogOut size={16} /> Quitter
        </button>
      </div>

      {status.sync.mandatory && (
        <p className="community-mandatory-note">
          <AlertTriangle size={16} aria-hidden="true" /> L’envoi des nouvelles parties terminées est obligatoire. Les pseudos adverses sont transmis uniquement après la fin confirmée du tournoi, chiffrés au repos et visibles seulement des membres contributeurs.
        </p>
      )}
      {(status.sync.last_error || actionError) && <p className="community-action-error" role="alert"><AlertTriangle size={16} />{actionError || status.sync.last_error}</p>}

      <nav className="community-tabs" aria-label="Sections communautaires">
        <button className={view === "overview" ? "active" : ""} onClick={() => setView("overview")} type="button"><Database size={16} /> Vue d’ensemble</button>
        <button className={view === "tournaments" ? "active" : ""} onClick={() => setView("tournaments")} type="button"><Eye size={16} /> Parties</button>
        <button className={view === "hands" ? "active" : ""} onClick={() => setView("hands")} type="button"><Search size={16} /> Mains</button>
        <button className={view === "opponents" ? "active" : ""} onClick={() => setView("opponents")} type="button"><UserRoundSearch size={16} /> Adversaires</button>
      </nav>

      {view === "overview" && (
        contributorId ? (
          contributorProfile.loading ? (
            <LoadingState label="Construction de la fiche du contributeur…" />
          ) : contributorProfile.error ? (
            <ErrorState error={contributorProfile.error} retry={contributorProfile.reload} />
          ) : contributorProfile.data ? (
            <CommunityContributorProfileView profile={contributorProfile.data} />
          ) : (
            <EmptyState title="Profil indisponible" description="Aucune statistique consentie n’est disponible pour ce contributeur." />
          )
        ) : dashboard.loading ? <LoadingState /> : dashboard.error ? <ErrorState error={dashboard.error} retry={dashboard.reload} /> : dashboard.data ? (
          <div className="community-overview">
            <div className="metrics-grid community-metrics">
              <MetricCard label="Contributeurs" value={formatNumber(dashboard.data.contributors_count)} icon={<Users />} />
              <MetricCard label="Parties" value={formatNumber(dashboard.data.tournaments_count)} hint={selectionLabel} />
              <MetricCard label="Mains" value={formatNumber(dashboard.data.hands_count)} />
              <MetricCard label="Buy-ins" value={formatMoney(dashboard.data.total_buy_ins)} />
              <MetricCard label="Gains" value={formatMoney(dashboard.data.total_winnings)} />
              <MetricCard label="Résultat net" value={formatMoney(dashboard.data.net_result, "EUR", true)} tone={dashboard.data.net_result >= 0 ? "positive" : "negative"} />
              <MetricCard label="ROI" value={`${formatNumber(dashboard.data.roi, 1)} %`} />
              <MetricCard label="ITM" value={`${formatNumber(dashboard.data.itm, 1)} %`} />
            </div>
            <SectionCard title="Contributeurs" subtitle="Identités choisies par les membres ; le suivi adverse post-session se trouve dans son onglet dédié.">
              {!contributors.data?.length ? <EmptyState title="Aucun contributeur synchronisé" /> : (
                <div className="community-contributor-grid">
                  {contributors.data.map((contributor) => (
                    <button type="button" key={contributor.id} className={contributor.id === contributorId ? "active" : ""} onClick={() => selectContributor(contributor.id)}>
                      <span className="community-avatar" aria-hidden="true">{contributor.display_name.slice(0, 1).toUpperCase()}</span>
                      <span><strong>{contributor.display_name}</strong><small>{formatNumber(contributor.tournaments_count)} parties · {formatNumber(contributor.hands_count)} mains</small></span>
                      {contributor.is_self && <StatusPill tone="info">Vous</StatusPill>}
                    </button>
                  ))}
                </div>
              )}
            </SectionCard>
          </div>
        ) : <EmptyState />
      )}

      {view === "tournaments" && (
        tournaments.loading ? <LoadingState /> : tournaments.error ? <ErrorState error={tournaments.error} retry={tournaments.reload} /> : !tournaments.data?.items.length ? <EmptyState title="Aucune partie partagée" /> : (
          <section className="section-card table-card">
            <div className="table-scroll">
              <table className="data-table community-table">
                <thead><tr><th>Contributeur</th><th>Date</th><th>Buy-in</th><th>Multi.</th><th>Place</th><th>Gain</th><th>Net</th><th>Durée</th><th>Mains</th><th>chipEV</th></tr></thead>
                <tbody>{tournaments.data.items.map((tournament) => (
                  <tr key={`${tournament.contributor_id}-${tournament.id}`}>
                    <td><strong>{tournament.contributor_display_name}</strong></td>
                    <td>{formatDate(tournament.started_at, true)}</td>
                    <td>{formatMoney(tournament.buy_in, tournament.currency ?? "EUR")}</td>
                    <td>{tournament.multiplier ? `×${tournament.multiplier}` : "—"}</td>
                    <td>{tournament.rank ? `${tournament.rank}${tournament.rank === 1 ? "er" : "e"}` : "—"}</td>
                    <td>{formatMoney(tournament.reward, tournament.currency ?? "EUR")}</td>
                    <td className={tournament.net_result >= 0 ? "value-positive" : "value-negative"}>{formatMoney(tournament.net_result, tournament.currency ?? "EUR", true)}</td>
                    <td>{formatDuration(tournament.duration_minutes)}</td>
                    <td>{formatNumber(tournament.hands_count)}</td>
                    <td>{tournament.chipev === null || tournament.chipev === undefined ? "—" : formatNumber(tournament.chipev, 1)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <Pagination page={tournaments.data.page} total={tournaments.data.total} pageSize={tournaments.data.page_size} onPage={setTournamentsPage} />
          </section>
        )
      )}

      {view === "hands" && (
        <div className="community-hands-stack">
          {hands.loading ? <LoadingState /> : hands.error ? <ErrorState error={hands.error} retry={hands.reload} /> : !hands.data?.items.length ? <EmptyState title="Aucune main partagée" /> : (
            <section className="section-card table-card">
              <div className="table-scroll">
                <table className="data-table community-table">
                  <thead><tr><th>Contributeur</th><th>Date</th><th>Cartes</th><th>Pos.</th><th>Prof.</th><th>Board</th><th>Pot</th><th>Résultat</th><th>Classification</th><th><span className="sr-only">Revoir</span></th></tr></thead>
                  <tbody>{hands.data.items.map((hand) => (
                    <tr key={`${hand.contributor_id}-${hand.id}`}>
                      <td><strong>{hand.contributor_display_name}</strong></td>
                      <td>{formatDate(hand.played_at, true)}</td>
                      <td className="cards-text">{joinCards(hand.hero_cards)}</td>
                      <td>{hand.position ?? "—"}</td>
                      <td>{hand.effective_stack_bb === null || hand.effective_stack_bb === undefined ? "—" : `${formatNumber(hand.effective_stack_bb, 1)} BB`}</td>
                      <td className="cards-text">{joinCards(hand.board)}</td>
                      <td>{hand.pot_bb === null || hand.pot_bb === undefined ? "—" : `${formatNumber(hand.pot_bb, 1)} BB`}</td>
                      <td className={(hand.net_result_chips ?? 0) >= 0 ? "value-positive" : "value-negative"}>{formatNumber(hand.net_result_chips)} j</td>
                      <td>{hand.classification ?? "Non classée"}</td>
                      <td><button className="icon-button replay-button" type="button" onClick={() => setReplayHand(hand)} disabled={!safeToAnalyze} aria-label="Revoir cette main terminée"><Play size={17} /></button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <Pagination page={hands.data.page} total={hands.data.total} pageSize={hands.data.page_size} onPage={setHandsPage} />
            </section>
          )}
        </div>
      )}

      {view === "opponents" && (
        <CommunityOpponents enabled={configured && status.opponent_tracking_enabled} dataRevision={dataRevision} />
      )}

      <HandReplayer handId={replayHand?.id ?? null} open={replayHand !== null} onClose={() => setReplayHand(null)} loadReplay={loadCommunityReplay} readOnly />
    </>
  );
}

function CommunityOnboarding({
  onJoined,
  busy,
  setBusy
}: {
  onJoined: () => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
}) {
  const [hubUrl, setHubUrl] = useState("");
  const [invite, setInvite] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");

  async function join(event: FormEvent) {
    event.preventDefault();
    setError("");
    let normalizedUrl: string;
    try {
      const url = new URL(hubUrl.trim());
      if (!(["http:", "https:"].includes(url.protocol))) throw new Error();
      const loopback = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(url.hostname.toLowerCase());
      if (url.protocol !== "https:" && !loopback) {
        setError("HTTPS est obligatoire pour un hub situé sur un autre PC.");
        return;
      }
      normalizedUrl = url.toString().replace(/\/$/, "");
    } catch {
      setError("Saisissez une URL de hub HTTP ou HTTPS valide.");
      return;
    }
    if (displayName.trim().length < 2) {
      setError("Le nom d’affichage doit contenir au moins deux caractères.");
      return;
    }
    if (!invite.trim()) {
      setError("Le code d’invitation est requis.");
      return;
    }
    if (!consent) {
      setError("Le consentement explicite est requis pour rejoindre le hub.");
      return;
    }
    setBusy(true);
    try {
      await api.communityJoin({
        hub_url: normalizedUrl,
        invite: invite.trim(),
        display_name: displayName.trim(),
        consent: true,
        consent_version: CONSENT_VERSION
      });
      setInvite("");
      onJoined();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Connexion au hub impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="community-onboarding">
      <PageHeader
        eyebrow="Fonction facultative à configurer"
        title="Rejoindre un hub communautaire"
        description="Partagez vos parties Expresso terminées avec un groupe autorisé, y compris les pseudos adverses observés selon la politique v2."
      />
      <div className="community-storage-banner" role="note">
        <Server aria-hidden="true" />
        <div><strong>Le hub est hébergé sur le serveur choisi par votre hôte</strong><span>Le navigateur communique seulement avec votre backend sur 127.0.0.1. L’invitation et le jeton de session ne sont jamais stockés dans le navigateur.</span></div>
        <ShieldCheck aria-hidden="true" />
      </div>
      <div className="community-onboarding-grid">
        <SectionCard title="Configuration" subtitle="Ces paramètres sont transmis au backend local, qui contacte ensuite le hub.">
          <form className="community-join-form" onSubmit={join}>
            <label>URL du hub<input type="url" value={hubUrl} onChange={(event) => setHubUrl(event.target.value)} placeholder="https://hub.exemple.fr" autoComplete="url" required /></label>
            <label>Code d’invitation<input type="password" value={invite} onChange={(event) => setInvite(event.target.value)} placeholder="Code fourni par l’hôte" autoComplete="off" required /></label>
            <label>Nom d’affichage<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Ex. Alice" autoComplete="nickname" maxLength={40} required /></label>
            <label className="community-consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              <span><strong>J’accepte la synchronisation communautaire v2</strong><small>Mes parties terminées, leurs mains et les pseudos adverses observés seront transmis au VPS. Les pseudos y sont chiffrés au repos, rapprochés entre contributeurs et visibles seulement aux membres contributeurs. Rien n’est lu ni envoyé pendant Winamax ou une partie active.</small></span>
            </label>
            {error && <p className="community-action-error" role="alert"><AlertTriangle size={16} />{error}</p>}
            <button className="button primary full-width" type="submit" disabled={busy || !consent}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <Users size={17} />}{busy ? "Connexion…" : "Rejoindre et synchroniser"}
            </button>
          </form>
        </SectionCard>
        <SectionCard title="Engagement post-session" subtitle="Protection conservatrice identique à l’analyse locale.">
          <div className="community-safety-list">
            <p><ShieldCheck /><span><strong>Parties terminées seulement</strong><small>Un tournoi incomplet, récent ou sans classement final reste bloqué.</small></span></p>
            <p><Database /><span><strong>Contribution obligatoire</strong><small>L’accès partagé dépend de l’envoi des données terminées du membre.</small></span></p>
            <p><Eye /><span><strong>Lecture seule</strong><small>Les données des autres membres ne modifient jamais votre base d’analyse locale.</small></span></p>
            <p><Users /><span><strong>Suivi adverse post-session</strong><small>Les pseudos adverses des tournois terminés sont chiffrés au repos et leur observation est partagée entre membres contributeurs.</small></span></p>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
