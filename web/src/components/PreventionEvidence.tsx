import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, BookOpen, ChevronDown, LoaderCircle, Search, Square } from 'lucide-react';
import { api, messageOf } from '../api';
import type {
  PreventionConfig,
  PreventionEvidence as Evidence,
  PreventionInterpretation,
  PreventionResult,
} from '../prevention';

function referenceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export default function PreventionEvidence({
  componentId,
  config,
  result,
  stale,
}: {
  componentId: string;
  config: PreventionConfig;
  result: PreventionResult | null;
  stale: boolean;
}) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [question, setQuestion] = useState('');
  const [interpretation, setInterpretation] = useState<PreventionInterpretation | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);
  const interpretationController = useRef<AbortController | null>(null);
  const { gravity_g, oxygen_percent, airflow_m_s, pressure_pa } = config;
  const snapshot =
    result && JSON.stringify(result.config) === JSON.stringify(config)
      ? result.evidence_snapshots_by_component?.[componentId]
      : undefined;

  useEffect(() => {
    if (snapshot) {
      setEvidence(snapshot);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setEvidence(null);
    void api
      .preventionEvidence(componentId, config, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setEvidence(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(messageOf(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [componentId, gravity_g, oxygen_percent, airflow_m_s, pressure_pa, retry, snapshot]);

  useEffect(() => () => interpretationController.current?.abort(), []);

  const interpret = async () => {
    if (!result || stale || interpreting) return;
    const controller = new AbortController();
    interpretationController.current = controller;
    setInterpreting(true);
    setInterpretError(null);
    try {
      const value = await api.preventionInterpret(result.id, componentId, question, controller.signal);
      if (!controller.signal.aborted) setInterpretation(value);
    } catch (reason) {
      if (!controller.signal.aborted) setInterpretError(messageOf(reason));
    } finally {
      if (interpretationController.current === controller) setInterpreting(false);
    }
  };

  return (
    <section className="panel prevention-evidence">
      <div className="panel-heading">
        <div>
          <BookOpen size={16} />
          <h2>Conclusions & preuves</h2>
        </div>
        <span>{evidence?.findings.length ?? '—'} conclusions</span>
      </div>
      <p className="prevention-note">
        Classées par applicabilité et nature des preuves. Ce classement documentaire ne mesure pas le danger
        des composants.
      </p>
      {snapshot && (
        <p className="prevention-note">
          Preuves figées pour ce composant dans l’analyse {result?.id.slice(0, 8)}. Elles correspondent aux
          résultats affichés, y compris si les paramètres sont ensuite modifiés.
        </p>
      )}
      {evidence && (
        <p className="prevention-note prevention-source-counts">
          {evidence.findings.filter((finding) => finding.is_nasa_source === true).length} conclusions NASA ·{' '}
          {evidence.findings.filter((finding) => finding.is_nasa_source === false).length} conclusions
          complémentaires hors NASA
          {evidence.findings.some((finding) => finding.is_nasa_source === undefined) &&
            ' · certaines provenances ne sont pas renseignées'}
          .
        </p>
      )}
      {loading && (
        <p className="prevention-note" role="status">
          <LoaderCircle size={15} className="spin" /> Recherche des conclusions pertinentes…
        </p>
      )}
      {error && (
        <div className="prevention-message" role="alert">
          {error}
          <button className="button ghost" onClick={() => setRetry((value) => value + 1)}>
            Réessayer les sources
          </button>
        </div>
      )}
      {evidence && !evidence.findings.length && (
        <p className="prevention-note">
          Aucune conclusion disponible dans le catalogue pour cette sélection.
        </p>
      )}
      <div className="prevention-findings">
        {evidence?.findings.map((finding, index) => (
          <details className="prevention-finding" key={finding.id} open={index === 0}>
            <summary>
              <span className="prevention-rank">{String(index + 1).padStart(2, '0')}</span>
              <span>
                <strong>{finding.title}</strong>
                <small>{finding.relevance}</small>
              </span>
              <ChevronDown size={14} />
            </summary>
            <div className="prevention-finding-body">
              <span className="prevention-quality">
                {finding.is_nasa_source === true
                  ? 'NASA'
                  : finding.is_nasa_source === false
                    ? 'Étude complémentaire · hors NASA'
                    : 'Provenance non renseignée'}{' '}
                · {finding.evidence_quality}
              </span>
              <p>{finding.statement}</p>
              <p className="prevention-small">Nature : {finding.epistemic_status}</p>
              <h3>Applicabilité au scénario</h3>
              <ul>
                {finding.reasons.map((reason, i) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
              <details>
                <summary>Conditions publiées</summary>
                <pre>{JSON.stringify(finding.conditions, null, 2)}</pre>
              </details>
              <h3>Limites de transfert</h3>
              <ul>
                {finding.limitations.map((limit, i) => (
                  <li key={i}>{limit}</li>
                ))}
              </ul>
              <div className="prevention-source">
                {referenceUrl(finding.source.url) ? (
                  <a href={referenceUrl(finding.source.url)} target="_blank" rel="noreferrer">
                    {finding.source_id}
                    <ArrowUpRight size={13} />
                  </a>
                ) : (
                  <span>{finding.source_id}</span>
                )}
                <span>{finding.source.locator}</span>
              </div>
            </div>
          </details>
        ))}
      </div>
      {evidence && (
        <details className="prevention-details">
          <summary>Comprendre le classement</summary>
          <ul>
            {evidence.limitations.map((limit, i) => (
              <li key={i}>{limit}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="prevention-interpretation">
        <h3>Comprendre cette analyse</h3>
        <p>
          Codex explique le résultat et ses sources ; les valeurs affichées proviennent des modèles de calcul.
        </p>
        <label htmlFor="prevention-question">Question facultative</label>
        <input
          id="prevention-question"
          maxLength={600}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Quelles limites pour ce composant ?"
          disabled={interpreting}
        />
        <button
          className="button secondary"
          disabled={!result || stale || interpreting}
          onClick={() => {
            void interpret();
          }}
        >
          {interpreting ? <LoaderCircle size={15} className="spin" /> : <Search size={15} />}
          {interpreting ? 'Interprétation en cours…' : 'Expliquer cette analyse'}
        </button>
        {interpreting && (
          <button
            className="button ghost"
            onClick={() => {
              interpretationController.current?.abort();
              setInterpreting(false);
              setInterpretError('Attente annulée ; la requête peut encore se terminer sur le poste.');
            }}
          >
            <Square size={12} />
            Annuler l’attente
          </button>
        )}
        {!result && <p>Une analyse est nécessaire pour obtenir une explication de ses résultats.</p>}
        {stale && (
          <p className="prevention-stale">
            Les paramètres ont changé. Relancez l’analyse pour expliquer ce nouveau scénario.
          </p>
        )}
        {interpretError && <p role="alert">{interpretError}</p>}
        {interpretation && (
          <div className="prevention-explanation">
            <span className="prevention-interpretation-method">
              {interpretation.method.includes('codex')
                ? `Codex · ${interpretation.model ?? 'modèle non renseigné'}`
                : `Synthèse extractive · ${interpretation.method}`}
            </span>
            <p className="prevention-summary">{interpretation.summary}</p>
            <p>Conclusions citées : {interpretation.evidence_ids.join(' · ') || 'non renseignées'}</p>
            <ul>
              {interpretation.limitations.map((limit, i) => (
                <li key={i}>{limit}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
