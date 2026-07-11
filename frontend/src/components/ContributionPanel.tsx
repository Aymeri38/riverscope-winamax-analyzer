import { useState } from "react";
import { AlertTriangle, Download, Eye, FileJson, LoaderCircle, ShieldCheck } from "lucide-react";
import { api } from "../services/api";
import type { ContributionPreview } from "../types";
import { SectionCard, StatusPill } from "./Ui";

const byteFormatter = new Intl.NumberFormat("fr-FR");

function savePreviewLocally(preview: ContributionPreview) {
  const blob = new Blob([preview.payload], {
    type: `${preview.media_type};charset=${preview.encoding}`
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = preview.filename || "contribution-winamax-minimisee.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ContributionPanel() {
  const [preview, setPreview] = useState<ContributionPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState(false);

  async function preparePreview() {
    setLoading(true);
    setError("");
    setConsent(false);
    setPreview(null);
    try {
      setPreview(await api.contributionPreview());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de préparer l’aperçu local.");
    } finally {
      setLoading(false);
    }
  }

  const previewIsLocal = preview?.network_sent === false;
  const canSave = Boolean(preview && previewIsLocal && preview.payload && consent);

  return (
    <SectionCard
      title="Export agrégé volontaire"
      subtitle="Outil indépendant du hub communautaire : préparez manuellement un paquet minimisé pour améliorer la compatibilité de RiverScope."
      className="settings-section contribution-panel"
    >
      <div className="contribution-intro">
        <ShieldCheck aria-hidden="true" />
        <div>
          <strong>Ce panneau ne pilote pas la synchronisation communautaire</strong>
          <p>
            L’aperçu est généré uniquement à votre demande par le backend local sur <code>127.0.0.1</code>.
            Vous voyez l’intégralité du fichier agrégé avant de décider de l’enregistrer. Cet export séparé reste volontaire et sa transmission reste manuelle, même lorsqu’un hub communautaire est configuré.
          </p>
        </div>
      </div>

      <div className="contribution-start">
        <div>
          <strong>Historiques terminés uniquement</strong>
          <small>Les pseudos, chemins et identifiants corrélables sont exclus; les volumes sont regroupés en tranches.</small>
        </div>
        <button className="button secondary" type="button" onClick={preparePreview} disabled={loading}>
          {loading ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
          {loading ? "Préparation…" : preview ? "Régénérer l’aperçu" : "Préparer l’aperçu"}
        </button>
      </div>

      {error && (
        <p className="contribution-feedback error-text" role="alert">
          <AlertTriangle size={16} aria-hidden="true" /> {error}
        </p>
      )}

      {preview && (
        <div className="contribution-preview" aria-live="polite">
          <div className="contribution-preview-heading">
            <div>
              <FileJson aria-hidden="true" />
              <span><strong>{preview.filename}</strong><small>Contenu exact du fichier à enregistrer</small></span>
            </div>
            <StatusPill tone={previewIsLocal ? "positive" : "negative"}>
              {previewIsLocal ? "Aucun envoi externe" : "État réseau inattendu"}
            </StatusPill>
          </div>

          <dl className="contribution-meta">
            <div><dt>Taille UTF-8</dt><dd>{byteFormatter.format(preview.byte_size)} octets</dd></div>
            <div><dt>Format</dt><dd>{preview.media_type} · {preview.encoding}</dd></div>
            <div className="contribution-hash"><dt>SHA-256</dt><dd><code>{preview.sha256}</code></dd></div>
          </dl>

          {!previewIsLocal && (
            <p className="contribution-feedback error-text" role="alert">
              <AlertTriangle size={16} aria-hidden="true" /> L’enregistrement est bloqué car le backend n’a pas confirmé l’absence d’envoi réseau.
            </p>
          )}

          <div className="contribution-disclosures">
            <DisclosureList title="Mesures de minimisation" items={preview.redactions} />
            <DisclosureList title="Données exclues" items={preview.exclusions} />
          </div>

          {preview.warnings.length > 0 && (
            <div className="contribution-warnings" role="status">
              <strong><AlertTriangle size={15} aria-hidden="true" /> Points à vérifier</strong>
              <ul>{preview.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul>
            </div>
          )}

          <div className="contribution-payload-block">
            <div><strong>Aperçu intégral exact</strong><small>Le texte ci-dessous sera enregistré tel quel, sans nouvelle transformation.</small></div>
            <pre className="contribution-payload" tabIndex={0} aria-label="Contenu exact de la contribution">{preview.payload}</pre>
          </div>

          <label className={`contribution-consent ${previewIsLocal ? "" : "disabled"}`}>
            <input
              type="checkbox"
              checked={consent}
              disabled={!previewIsLocal || !preview.payload}
              onChange={(event) => setConsent(event.target.checked)}
            />
            <span>
              <strong>Consentement ponctuel</strong>
              <small>J’ai examiné l’intégralité de cet export agrégé et je souhaite créer ce fichier local. Cette action est distincte de la synchronisation obligatoire d’un hub configuré.</small>
            </span>
          </label>

          <div className="contribution-save-row">
            <small>Ce bouton enregistre un fichier sur votre PC. Il ne contacte aucun service externe.</small>
            <button className="button primary" type="button" disabled={!canSave} onClick={() => preview && savePreviewLocally(preview)}>
              <Download size={17} aria-hidden="true" /> Enregistrer le fichier
            </button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function DisclosureList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <strong>{title}</strong>
      {items.length ? <ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <small>Aucun élément signalé.</small>}
    </div>
  );
}
