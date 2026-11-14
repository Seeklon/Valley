import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  FileCheck2,
  LoaderCircle,
  Search,
  ShieldCheck,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { api, messageOf } from '../api';
import { format } from '../data';
import type { Insight, RunConfig } from '../types';

function referenceUrl(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export default function InsightsPanel({
  config,
  available,
  busy,
}: {
  config: RunConfig;
  available: boolean;
  busy: boolean;
}) {
  const [question, setQuestion] = useState('');
  const [insight, setInsight] = useState<Insight | null>(null);
  const [snapshot, setSnapshot] = useState<RunConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const changed = snapshot && JSON.stringify(snapshot) !== JSON.stringify(config);
  useEffect(() => () => controller.current?.abort(), []);

  const interpret = async () => {
    if (loading || !available || busy) return;
    setLoading(true);
    setError(null);
    setSnapshot({ ...config });
    const activeController = new AbortController();
    controller.current = activeController;
    try {
      const next = await api.insights(config, question, activeController.signal);
      if (!activeController.signal.aborted) setInsight(next);
    } catch (reason) {
      if (!activeController.signal.aborted) setError(messageOf(reason));
    } finally {
      if (controller.current === activeController) setLoading(false);
    }
  };

  const stopWaiting = () => {
    controller.current?.abort();
    setLoading(false);
    setError('Attente annulée. La requête peut encore se terminer sur le poste de calcul.');
  };

  return (
    <details className="panel insights-panel" open>
      <summary>
        <span className="campaign-heading-icon">
          <BookOpen size={18} />
        </span>
        <div>
          <strong>Interprétation NASA</strong>
          <span>Retrouver les expériences pertinentes et comprendre les limites de transfert.</span>
        </div>
        <ChevronDown size={16} />
      </summary>
      <div className="insights-body">
        <div className="insights-query">
          <label htmlFor="insights-question">
            Votre question sur cette configuration <span>facultatif</span>
          </label>
          <div>
            <input
              id="insights-question"
              type="text"
              maxLength={600}
              placeholder="Que montrent les expériences quand la ventilation varie ?"
              value={question}
              disabled={loading}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void interpret();
                }
              }}
            />
            <button
              className="button secondary"
              disabled={!available || loading || busy}
              onClick={() => {
                void interpret();
              }}
            >
              {loading ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}
              {loading ? 'Recherche et interprétation…' : 'Interpréter ce scénario'}
            </button>
          </div>
          {loading && (
            <button className="text-button insights-cancel" onClick={stopWaiting}>
              <Square size={10} />
              Annuler l’attente
            </button>
          )}
          {!available && (
            <p className="field-help">Le service documentaire doit être connecté pour établir la synthèse.</p>
          )}
        </div>
        {error && (
          <div className="inline-error" role="alert">
            <TriangleAlert size={15} />
            <p>{error}</p>
          </div>
        )}
        {insight ? (
          <>
            {changed && (
              <div className="result-context">
                <TriangleAlert size={13} />
                Les paramètres ont changé depuis cette interprétation. Lancez une nouvelle recherche pour les
                prendre en compte.
              </div>
            )}
            <div className="insights-result">
              <div className="insights-narrative">
                <span className="eyebrow cyan-text">SYNTHÈSE DOCUMENTAIRE</span>
                <p className="insights-summary">{insight.summary}</p>
                {insight.facts.length > 0 && (
                  <div className="insights-facts">
                    <h3>
                      <FileCheck2 size={15} />
                      Observations sourcées
                    </h3>
                    {insight.facts.map((fact, index) => {
                      const source = insight.sources.find((entry) => entry.id === fact.source_id);
                      return (
                        <div key={`${fact.source_id}-${index}`}>
                          <p>{fact.text}</p>
                          {referenceUrl(source?.url) ? (
                            <a href={referenceUrl(source?.url)} target="_blank" rel="noreferrer">
                              {fact.source_id}
                              <ArrowUpRight size={11} />
                            </a>
                          ) : (
                            <span>{fact.source_id}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {insight.limits.length > 0 && (
                  <div className="insights-limits">
                    <h3>
                      <ShieldCheck size={15} />
                      Ce que ces preuves permettent de conclure
                    </h3>
                    <ul>
                      {insight.limits.map((limit) => (
                        <li key={limit}>{limit}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="insights-method">
                  <span>
                    Méthode :{' '}
                    {insight.method === 'codex_grounded_in_nasa_evidence'
                      ? 'Codex · interprétation fondée sur les sources NASA'
                      : insight.method === 'extractive_evidence'
                        ? 'Extraction des preuves documentaires'
                        : insight.method}
                  </span>
                  {insight.model && <span>Modèle : {insight.model}</span>}
                </div>
              </div>
              <div className="ranked-sources">
                <h3>Sources classées pour ce scénario</h3>
                <p>Le classement reflète la pertinence documentaire, pas une probabilité de sécurité.</p>
                {insight.sources.map((source, index) => (
                  <article key={source.id}>
                    <div>
                      <span>{String(index + 1).padStart(2, '0')}</span>
                      <h4>{source.name}</h4>
                      {referenceUrl(source.url) && (
                        <a
                          href={referenceUrl(source.url)}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={`Ouvrir ${source.name}`}
                        >
                          <ArrowUpRight size={15} />
                        </a>
                      )}
                    </div>
                    <code>
                      {source.id}
                      {source.score !== undefined ? ` · pertinence ${format(source.score, 1)}` : ''}
                    </code>
                    <ul>
                      {source.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            </div>
          </>
        ) : (
          !loading && (
            <div className="insights-empty">
              <FileCheck2 size={23} strokeWidth={1.3} />
              <p>
                La configuration sera rapprochée des sources expérimentales. Chaque conclusion conservera ses
                références et les conditions dans lesquelles elle s’applique.
              </p>
            </div>
          )
        )}
      </div>
    </details>
  );
}
