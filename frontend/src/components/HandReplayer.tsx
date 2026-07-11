import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, LockKeyhole, Save, SkipBack, SkipForward, X } from "lucide-react";
import { useSafety } from "../contexts/SafetyContext";
import { api } from "../services/api";
import type { ReplayAction, ReplayData } from "../types";
import { cardLabel, formatNumber } from "../utils/format";
import { ErrorState, LoadingState, StatusPill } from "./Ui";

function PlayingCard({ value, hidden = false }: { value?: string; hidden?: boolean }) {
  if (hidden || !value) return <span className="playing-card back" aria-label="Carte cachée" />;
  const card = cardLabel(value);
  return (
    <span className={`playing-card ${card.red ? "red" : ""}`} aria-label={`${card.rank} ${card.suit}`}>
      <strong>{card.rank}</strong>
      <span>{card.suit}</span>
    </span>
  );
}

function boardAtAction(board: string[], action?: ReplayAction): string[] {
  if (!action) return [];
  if (action.street === "preflop") return [];
  if (action.street === "flop") return board.slice(0, 3);
  if (action.street === "turn") return board.slice(0, 4);
  return board.slice(0, 5);
}

export function HandReplayer({
  handId,
  open,
  onClose,
  loadReplay,
  readOnly = false
}: {
  handId: number | string | null;
  open: boolean;
  onClose: () => void;
  loadReplay?: (id: number | string) => Promise<ReplayData>;
  readOnly?: boolean;
}) {
  const { safeToAnalyze } = useSafety();
  const [data, setData] = useState<ReplayData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [step, setStep] = useState(-1);
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const replayLoader = loadReplay ?? api.replay;

  useEffect(() => {
    if (!open || handId === null || !safeToAnalyze) return;
    let active = true;
    setLoading(true);
    setError(null);
    setStep(-1);
    replayLoader(handId)
      .then((replay) => {
        if (!active) return;
        setData(replay);
        setNotes(replay.hand.notes ?? "");
        setTags((replay.hand.tags ?? []).join(", "));
      })
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason : new Error(String(reason))))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [handId, open, replayLoader, safeToAnalyze]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft") setStep((value) => Math.max(-1, value - 1));
      if (event.key === "ArrowRight" && data) setStep((value) => Math.min(data.actions.length - 1, value + 1));
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [data, onClose, open]);

  const currentAction = data && step >= 0 ? data.actions[step] : undefined;
  const visibleBoard = useMemo(() => (data ? boardAtAction(data.board, currentAction) : []), [currentAction, data]);
  const pot = currentAction?.pot_after ?? data?.initial_pot ?? 0;
  const street = currentAction?.street ?? "distribution";

  function jumpStreet(direction: 1 | -1) {
    if (!data) return;
    const streets = ["preflop", "flop", "turn", "river", "showdown"];
    const currentStreetIndex = Math.max(0, streets.indexOf(currentAction?.street ?? "preflop"));
    const targetStreet = streets[Math.min(streets.length - 1, Math.max(0, currentStreetIndex + direction))];
    let targetIndex = data.actions.findIndex((action) => action.street === targetStreet);
    if (direction < 0) {
      targetIndex = -1;
      for (let index = data.actions.length - 1; index >= 0; index -= 1) {
        if (data.actions[index].street === targetStreet) {
          targetIndex = index;
          break;
        }
      }
    }
    if (targetIndex >= 0) setStep(targetIndex);
  }

  async function saveAnnotations() {
    if (!handId) return;
    setSaveState("saving");
    try {
      await api.updateHand(handId, {
        notes,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean)
      });
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.currentTarget === event.target && onClose()}>
      <section className="replayer-modal" role="dialog" aria-modal="true" aria-labelledby="replayer-title">
        <header className="modal-header">
          <div>
            <p className="eyebrow">{readOnly ? "Lecture partagée · main terminée" : "Lecture manuelle · main terminée"}</p>
            <h2 id="replayer-title">Replayer {data?.hand.hand_id ? `#${data.hand.hand_id}` : "de la main"}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Fermer le replayer" type="button">
            <X />
          </button>
        </header>

        {!safeToAnalyze ? (
          <div className="replayer-locked" role="alert">
            <LockKeyhole size={32} aria-hidden="true" />
            <h3>Replayer verrouillé</h3>
            <p>Le tournoi ou un fichier associé n’est pas confirmé comme terminé. Aucune donnée de replay n’a été chargée.</p>
          </div>
        ) : loading ? (
          <LoadingState label="Préparation du replayer…" />
        ) : error ? (
          <ErrorState error={error} />
        ) : data ? (
          <div className="replayer-content">
            <div className="replayer-stage">
              <div className="replay-meta">
                <StatusPill tone="info">{street}</StatusPill>
                <span>Blindes {data.small_blind ?? "—"}/{data.big_blind ?? "—"}</span>
                {data.ante ? <span>Ante {data.ante}</span> : null}
              </div>
              <div className="poker-table" aria-label="Table de poker reconstituée après la partie">
                {data.seats.map((seat, index) => {
                  const latest = data.actions.slice(0, step + 1).filter((action) => action.player_name === seat.name).at(-1);
                  return (
                    <div className={`seat seat-${index} ${seat.is_hero ? "hero" : ""}`} key={`${seat.name}-${index}`}>
                      <strong>{seat.is_hero ? "Héros" : seat.name}</strong>
                      <small>{seat.position ?? ""}</small>
                      <span>{formatNumber(latest?.stack_after ?? seat.starting_stack, 0)} jetons</span>
                      {seat.is_hero && (
                        <div className="mini-cards">
                          {data.hero_cards.map((card) => (
                            <PlayingCard key={card} value={card} />
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                <div className="table-center">
                  <div className="board-cards">
                    {[0, 1, 2, 3, 4].map((index) => (
                      <PlayingCard key={index} value={visibleBoard[index]} hidden={!visibleBoard[index]} />
                    ))}
                  </div>
                  <strong>Pot · {formatNumber(pot, 0)}</strong>
                </div>
              </div>
              <div className="replay-current-action" aria-live="polite">
                {currentAction ? (
                  <>
                    <strong>{currentAction.is_hero ? "Héros" : currentAction.player_name}</strong>
                    <span>{currentAction.action}</span>
                    {currentAction.amount ? <b>{formatNumber(currentAction.amount)} jetons</b> : null}
                  </>
                ) : (
                  <span>Stacks initiaux — utilisez Suivant pour commencer.</span>
                )}
              </div>
              <div className="replay-controls">
                <button className="icon-button" onClick={() => setStep(-1)} disabled={step < 0} aria-label="Revenir au début" type="button">
                  <SkipBack />
                </button>
                <button className="button secondary" onClick={() => jumpStreet(-1)} disabled={step <= 0} type="button">
                  <ChevronLeft size={17} /> Rue précédente
                </button>
                <span className="step-counter">
                  {step + 1} / {data.actions.length}
                </span>
                <button className="button secondary" onClick={() => jumpStreet(1)} disabled={step >= data.actions.length - 1} type="button">
                  Rue suivante <ChevronRight size={17} />
                </button>
                <button className="icon-button" onClick={() => setStep(data.actions.length - 1)} disabled={step >= data.actions.length - 1} aria-label="Aller à la fin" type="button">
                  <SkipForward />
                </button>
              </div>
              <div className="replay-step-buttons">
                <button className="button ghost" onClick={() => setStep((value) => Math.max(-1, value - 1))} disabled={step < 0} type="button">
                  Précédent
                </button>
                <button className="button primary" onClick={() => setStep((value) => Math.min(data.actions.length - 1, value + 1))} disabled={step >= data.actions.length - 1} type="button">
                  Suivant
                </button>
              </div>
            </div>

            <aside className="replayer-sidebar">
              <div className="replay-result">
                <h3>Résultat final</h3>
                <p>{data.result ?? (data.winner ? `Gagnant : ${data.winner}` : "Résultat non renseigné")}</p>
                {data.equity ? (
                  <dl className="equity-grid">
                    <div><dt>Victoire</dt><dd>{formatNumber(data.equity.win, 1)} %</dd></div>
                    <div><dt>Partage</dt><dd>{formatNumber(data.equity.tie, 1)} %</dd></div>
                    <div><dt>Défaite</dt><dd>{formatNumber(data.equity.lose, 1)} %</dd></div>
                    <div><dt>EV jetons</dt><dd>{formatNumber(data.equity.ev_chips, 1)}</dd></div>
                  </dl>
                ) : (
                  <p className="muted">Équité non calculable : cartes adverses inconnues.</p>
                )}
              </div>
              <div className="timeline-list">
                <h3>Actions</h3>
                {data.actions.map((action, index) => (
                  <button key={`${action.order}-${index}`} className={index === step ? "active" : ""} onClick={() => setStep(index)} type="button">
                    <span>{action.street}</span>
                    <strong>{action.is_hero ? "Héros" : action.player_name}</strong>
                    <small>{action.action}{action.amount ? ` · ${formatNumber(action.amount)}` : ""}</small>
                  </button>
                ))}
              </div>
              {readOnly ? (
                <div className="annotation-form community-readonly-note">
                  <h3>Lecture seule</h3>
                  <p>Les annotations privées du contributeur ne sont ni chargées ni modifiables.</p>
                </div>
              ) : (
                <div className="annotation-form">
                  <h3>Notes personnelles</h3>
                  <label>
                    Notes
                    <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={4} placeholder="Votre lecture de la main…" />
                  </label>
                  <label>
                    Tags <small>(séparés par des virgules)</small>
                    <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="à revoir, HU, river" />
                  </label>
                  <button className="button secondary" onClick={saveAnnotations} disabled={saveState === "saving"} type="button">
                    <Save size={16} /> {saveState === "saving" ? "Enregistrement…" : "Enregistrer"}
                  </button>
                  {saveState === "saved" && <small className="success-text">Annotations enregistrées.</small>}
                  {saveState === "error" && <small className="error-text">Enregistrement impossible.</small>}
                </div>
              )}
            </aside>
          </div>
        ) : null}
      </section>
    </div>
  );
}
