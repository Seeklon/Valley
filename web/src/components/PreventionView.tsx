import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  Battery,
  Box,
  Cable,
  Check,
  ChevronRight,
  Clock3,
  GitCompareArrows,
  Layers,
  LoaderCircle,
  Play,
  RotateCcw,
  ScanLine,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  TriangleAlert,
  X,
} from 'lucide-react';
import { api, messageOf } from '../api';
import { finite, format } from '../data';
import {
  comparisonIssue,
  observationPrefix,
  preventionConfigIssue,
  preventionState,
  preventionStates,
  preventionStatusLabels,
} from '../prevention';
import type {
  ComponentAssessment,
  PreventionCatalog,
  PreventionComponent,
  PreventionConfig,
  PreventionResult,
} from '../prevention';
import type { Scene } from '../types';
import PreventionChart from './PreventionChart';
import PreventionEvidence from './PreventionEvidence';
import '../prevention.css';

const Viewport = lazy(() => import('./Viewport'));
type NumberKey = Exclude<keyof PreventionConfig, 'scene_id'>;
const environmentKeys: NumberKey[] = [
  'current_a',
  'airflow_m_s',
  'gravity_g',
  'ambient_temperature_c',
  'oxygen_percent',
  'pressure_pa',
];
const timingKeys: NumberKey[] = ['duration_s', 'observation_cutoff_s', 'horizon_s'];
const noObjectSelection = () => {};

export interface PreventionSession {
  config: PreventionConfig | null;
  selectedId: string | null;
  mode: 'design' | 'replay';
  cutaway: boolean;
  result: PreventionResult | null;
  baseline: PreventionResult | null;
}

function Parameter({
  name,
  config,
  catalog,
  disabled,
  onChange,
}: {
  name: NumberKey;
  config: PreventionConfig;
  catalog: PreventionCatalog;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  const parameter = catalog.parameters[name];
  if (!parameter) return null;
  return (
    <label className="prevention-parameter" htmlFor={`prevention-${name}`}>
      <span>
        {parameter.label}
        <small>{parameter.unit}</small>
      </span>
      <input
        id={`prevention-${name}`}
        type="number"
        min={parameter.min}
        max={parameter.max}
        step={parameter.step}
        value={finite(config[name]) ? (config[name] as number) : ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.valueAsNumber)}
      />
    </label>
  );
}

function ComponentInspector({
  component,
  assessment,
  result,
  config,
}: {
  component: PreventionComponent;
  assessment?: ComponentAssessment;
  result: PreventionResult | null;
  config: PreventionConfig;
}) {
  const state = preventionState(assessment);
  const estimate = state === 'unknown' ? null : assessment?.estimate;
  const lastObserved = observationPrefix(assessment?.observations ?? [], config.observation_cutoff_s).at(-1);
  return (
    <section className="panel prevention-inspector" aria-label="Détail du composant">
      <div className="panel-heading">
        <div>
          {component.kind === 'battery' ? <Battery size={16} /> : <Cable size={16} />}
          <h2>{component.name}</h2>
        </div>
      </div>
      <div className="prevention-inspector-body">
        <div className={`prevention-component-state ${state}`} data-prevention-state={state}>
          <i style={{ background: preventionStates[state].color }} />
          {preventionStates[state].label}
        </div>
        <p className="prevention-small">
          {assessment ? preventionStatusLabels[assessment.status] : 'Aucune analyse effectuée.'}
        </p>
        <div className="prevention-estimate">
          <span>Délai d’allumage estimé</span>
          <strong data-testid="ignition-delay">
            {estimate ? format(estimate.ignition_delay_s, 2) : '—'}
            <small> s</small>
          </strong>
          <span>depuis la mise sous courant</span>
        </div>
        <dl className="prevention-facts">
          <div>
            <dt>Instant de prévision</dt>
            <dd>{format(config.observation_cutoff_s, 2)} s</dd>
          </div>
          <div>
            <dt>Horizon étudié</dt>
            <dd>{format(config.horizon_s, 2)} s</dd>
          </div>
          <div>
            <dt>{state === 'reached' ? 'Instant estimé dépassé de' : 'Temps restant estimé'}</dt>
            <dd>
              {estimate
                ? `${format(state === 'reached' ? Math.abs(estimate.remaining_time_s) : estimate.remaining_time_s, 2)} s`
                : 'Non estimé'}
            </dd>
          </div>
          <div>
            <dt>Incertitude du délai</dt>
            <dd>
              {estimate && assessment?.interval
                ? `${format(assessment.interval.lower_s, 2)}–${format(assessment.interval.upper_s, 2)} s (${assessment.interval.kind})`
                : 'Non quantifiée'}
            </dd>
          </div>
          <div>
            <dt>Probabilité réelle de feu</dt>
            <dd>Non quantifiée</dd>
          </div>
        </dl>
        {state === 'beyond' && (
          <p className="prevention-inspector-note">
            L’instant estimé dépasse cet horizon. Cela ne démontre pas l’absence de danger.
          </p>
        )}
        {state === 'reached' && (
          <p className="prevention-inspector-note">
            L’instant estimé est atteint. Il ne s’agit pas d’une flamme détectée.
          </p>
        )}
        {!!assessment?.reasons.length && (
          <ul className="prevention-reasons">
            {assessment.reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        )}
        {estimate && (
          <div className="prevention-protocol">
            <h3>Conditions de l’estimation</h3>
            <p>{estimate.conditional_on}</p>
            <span>Domaine : {estimate.domain}</span>
            <span>Modèle : {estimate.model_id}</span>
          </div>
        )}
        {result && <p className="prevention-small">{result.target.criterion}</p>}
        <details className="prevention-component-details" open>
          <summary>Composant & hypothèses</summary>
          <dl className="prevention-facts">
            <div>
              <dt>Matériau</dt>
              <dd>{component.material_id}</dd>
            </div>
            <div>
              <dt>Courant du composant</dt>
              <dd>
                {component.kind === 'wire'
                  ? `${format(assessment?.current_a ?? config.current_a * component.current_factor, 2)} A`
                  : 'Non modélisé'}
              </dd>
            </div>
            {component.kind === 'wire' && (
              <div>
                <dt>Référence × facteur</dt>
                <dd>
                  {format(config.current_a, 2)} A × {format(component.current_factor, 2)}
                </dd>
              </div>
            )}
            <div>
              <dt>Position hypothétique X/Y/Z</dt>
              <dd>{component.position_m.map((value) => format(value, 2)).join(' / ')} m</dd>
            </div>
            <div>
              <dt>Dernière température simulée</dt>
              <dd>
                {lastObserved
                  ? `${format(lastObserved.surface_temperature_c, 1)} °C à ${format(lastObserved.time_s, 2)} s`
                  : 'Indisponible'}
              </dd>
            </div>
          </dl>
          <p>{component.provenance}</p>
          <ul>
            {component.limitations.map((limit, index) => (
              <li key={index}>{limit}</li>
            ))}
          </ul>
        </details>
        {assessment?.thermal && (
          <details className="prevention-component-details">
            <summary>Validité de la thermique</summary>
            <p>Modèle local exploratoire, sans allumage gazeux. Statut : {assessment.thermal.status}.</p>
            <ul>
              {assessment.thermal.limitations.map((limit, index) => (
                <li key={index}>{limit}</li>
              ))}
            </ul>
            <pre>{JSON.stringify(assessment.thermal.summary, null, 2)}</pre>
          </details>
        )}
      </div>
    </section>
  );
}

function Comparison({
  result,
  baseline,
  componentId,
  onClear,
}: {
  result: PreventionResult;
  baseline: PreventionResult;
  componentId: string;
  onClear: () => void;
}) {
  const issue = comparisonIssue(result, baseline, componentId);
  const before = baseline.components.find((item) => item.component_id === componentId)?.estimate;
  const current = result.components.find((item) => item.component_id === componentId)?.estimate;
  const delta = !issue && before && current ? current.ignition_delay_s - before.ignition_delay_s : null;
  return (
    <section className="panel prevention-comparison">
      <div className="panel-heading">
        <div>
          <GitCompareArrows size={16} />
          <h2>Comparaison des analyses</h2>
        </div>
        <button className="icon-button" aria-label="Retirer la référence de prévention" onClick={onClear}>
          <X size={15} />
        </button>
      </div>
      <div className="prevention-comparison-body">
        <div>
          <span>Référence {baseline.id.slice(0, 8)}</span>
          <strong>{before ? `${format(before.ignition_delay_s, 2)} s` : 'Non estimé'}</strong>
          <small>
            {format(baseline.config.current_a, 2)} A · air {format(baseline.config.airflow_m_s, 2)} m/s
          </small>
        </div>
        <ArrowRight size={16} />
        <div>
          <span>Analyse {result.id.slice(0, 8)}</span>
          <strong>{current ? `${format(current.ignition_delay_s, 2)} s` : 'Non estimé'}</strong>
          <small>
            {format(result.config.current_a, 2)} A · air {format(result.config.airflow_m_s, 2)} m/s
          </small>
        </div>
      </div>
      <p className="prevention-note" data-testid="prevention-comparison">
        {delta !== null
          ? `Écart de délai : ${delta > 0 ? '+' : ''}${format(delta, 2)} s, dans le même protocole et au même horizon. Ce n’est pas une réduction de probabilité de feu.`
          : `Écart non calculé : ${issue}`}
      </p>
    </section>
  );
}

export default function PreventionView({
  scenes,
  connected,
  session,
  onSessionChange,
}: {
  scenes: Scene[];
  connected: boolean;
  session: PreventionSession | null;
  onSessionChange: (session: PreventionSession) => void;
}) {
  const [catalog, setCatalog] = useState<PreventionCatalog | null>(null);
  const [config, setConfig] = useState<PreventionConfig | null>(session?.config ?? null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(session?.selectedId ?? null);
  const [mode, setMode] = useState<'design' | 'replay'>(session?.mode ?? 'design');
  const [cutaway, setCutaway] = useState(session?.cutaway ?? true);
  const [result, setResult] = useState<PreventionResult | null>(session?.result ?? null);
  const [baseline, setBaseline] = useState<PreventionResult | null>(session?.baseline ?? null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    onSessionChange({ config, selectedId, mode, cutaway, result, baseline });
  }, [config, selectedId, mode, cutaway, result, baseline, onSessionChange]);

  useEffect(() => {
    const request = new AbortController();
    setCatalogError(null);
    void api
      .preventionCatalog(request.signal)
      .then((value) => {
        if (request.signal.aborted) return;
        setCatalog(value);
        setConfig((previous) => previous ?? { ...value.defaults });
      })
      .catch((reason) => {
        if (!request.signal.aborted) setCatalogError(messageOf(reason));
      });
    return () => request.abort();
  }, [retry]);
  useEffect(() => () => controller.current?.abort(), []);

  const scene = scenes.find((entry) => entry.id === config?.scene_id);
  const components = useMemo(
    () => catalog?.components.filter((entry) => entry.scene_id === config?.scene_id) ?? [],
    [catalog, config?.scene_id],
  );
  const component = components.find((entry) => entry.id === selectedId) ?? components[0];
  const displayedConfig = result?.config ?? config;
  const assessment = result?.components.find((entry) => entry.component_id === component?.id);
  const stale = Boolean(result && config && JSON.stringify(result.config) !== JSON.stringify(config));
  const issue = catalog && config ? preventionConfigIssue(config, catalog) : null;
  const markers = useMemo(
    () =>
      components.map((entry) => ({
        id: entry.id,
        name: entry.name,
        position_m: entry.position_m,
        object_id: entry.object_id ?? undefined,
        color:
          preventionStates[preventionState(result?.components.find((item) => item.component_id === entry.id))]
            .color,
      })),
    [components, result],
  );

  const update = (key: NumberKey, value: number | null) =>
    setConfig((previous) => (previous ? { ...previous, [key]: value } : previous));
  const analyze = async () => {
    if (!config || !catalog || analyzing || issue || !connected) return;
    const request = new AbortController();
    controller.current = request;
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const next = await api.preventionAnalyze({ ...config }, request.signal);
      if (!request.signal.aborted) setResult(next);
    } catch (reason) {
      if (!request.signal.aborted) setAnalysisError(messageOf(reason));
    } finally {
      if (controller.current === request) setAnalyzing(false);
    }
  };

  return (
    <div className="prevention-view">
      <section className="workspace-heading">
        <div>
          <div className="breadcrumb">
            PRÉVENTION <ChevronRight size={11} /> AVANT L’ALLUMAGE
          </div>
          <h1>
            Anticiper l’échauffement. <span>Comprendre les limites.</span>
          </h1>
          <p>
            Explorez les composants, comparez des scénarios et retrouvez les preuves expérimentales
            applicables.
          </p>
        </div>
        <div className="workspace-meta">
          <span className="status-chip">
            <ShieldCheck size={13} />
            Étude exploratoire
          </span>
          <a
            href="https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/?tab=details"
            target="_blank"
            rel="noreferrer"
          >
            NASA Space Apps · Flame in Freefall <ArrowRight size={13} />
          </a>
        </div>
      </section>
      <div className="prevention-context">
        <ScanLine size={17} />
        <p>
          <strong>Scène instrumentée hypothétique.</strong> Historiques simulés, aucun capteur réel connecté.
          Les délais sont conditionnels à un protocole de laboratoire ; la probabilité réelle d’incendie n’est
          pas quantifiée.
        </p>
      </div>
      {catalogError && (
        <div className="prevention-message" role="alert">
          <TriangleAlert size={16} />
          {catalogError}
          <button className="button secondary" onClick={() => setRetry((value) => value + 1)}>
            Réessayer le catalogue
          </button>
        </div>
      )}
      {!catalog && !catalogError && (
        <div className="prevention-empty" role="status">
          <LoaderCircle size={22} className="spin" />
          Chargement du catalogue de prévention…
        </div>
      )}
      {catalog && config && displayedConfig && (
        <>
          <div className="prevention-toolbar">
            <div className="prevention-mode" aria-label="Usage de la prévention">
              <button
                aria-pressed={mode === 'design'}
                className={mode === 'design' ? 'active' : ''}
                onClick={() => setMode('design')}
              >
                <Layers size={14} />
                Scénario avant mission
              </button>
              <button
                aria-pressed={mode === 'replay'}
                className={mode === 'replay' ? 'active' : ''}
                onClick={() => setMode('replay')}
              >
                <Clock3 size={14} />
                Relecture simulée
              </button>
            </div>
            <span>
              {catalog.models.length} modèle{catalog.models.length > 1 ? 's' : ''} de prévention chargé
              {catalog.models.length > 1 ? 's' : ''}
            </span>
          </div>
          <div className="prevention-layout">
            <aside className="panel prevention-settings" aria-label="Paramètres de prévention">
              <div className="panel-heading">
                <div>
                  <SlidersHorizontal size={16} />
                  <h2>Scénario</h2>
                </div>
                <button
                  className="icon-button"
                  disabled={analyzing}
                  aria-label="Rétablir les paramètres de prévention"
                  onClick={() => {
                    setConfig({ ...catalog.defaults });
                    if (config.scene_id !== catalog.defaults.scene_id) {
                      setResult(null);
                      setSelectedId(null);
                    }
                  }}
                >
                  <RotateCcw size={14} />
                </button>
              </div>
              <div className="prevention-settings-body">
                <label className="prevention-scene-label" htmlFor="prevention-scene">
                  Environnement
                </label>
                <select
                  id="prevention-scene"
                  value={config.scene_id}
                  disabled={analyzing}
                  onChange={(event) => {
                    setConfig({ ...config, scene_id: event.target.value });
                    setSelectedId(null);
                    setResult(null);
                    setAnalysisError(null);
                  }}
                >
                  {catalog.scene_ids.map((id) => (
                    <option key={id} value={id}>
                      {scenes.find((entry) => entry.id === id)?.name ?? id}
                    </option>
                  ))}
                </select>
                <p className="prevention-small">
                  {mode === 'design'
                    ? 'Choisissez les hypothèses de fonctionnement et comparez les résultats calculés.'
                    : 'Choisissez le dernier instant accessible au modèle. Les observations futures sont exclues.'}
                </p>
                <fieldset disabled={analyzing}>
                  <legend>Charge & environnement local</legend>
                  {environmentKeys.map((key) => (
                    <Parameter
                      key={key}
                      name={key}
                      config={config}
                      catalog={catalog}
                      disabled={analyzing}
                      onChange={(value) => update(key, value)}
                    />
                  ))}
                </fieldset>
                <fieldset disabled={analyzing}>
                  <legend>Fenêtre de prévision</legend>
                  {timingKeys.map((key) => (
                    <Parameter
                      key={key}
                      name={key}
                      config={config}
                      catalog={catalog}
                      disabled={analyzing}
                      onChange={(value) => update(key, value)}
                    />
                  ))}
                  {mode === 'replay' && catalog.parameters.observation_cutoff_s && (
                    <label className="prevention-replay-label" htmlFor="prevention-replay">
                      Dernier instant observé : {format(config.observation_cutoff_s, 2)} s
                      <input
                        id="prevention-replay"
                        type="range"
                        min={catalog.parameters.observation_cutoff_s.min}
                        max={Math.min(
                          catalog.parameters.observation_cutoff_s.max,
                          config.duration_s - config.horizon_s,
                        )}
                        step={catalog.parameters.observation_cutoff_s.step}
                        value={config.observation_cutoff_s}
                        onChange={(event) => update('observation_cutoff_s', event.target.valueAsNumber)}
                      />
                    </label>
                  )}
                </fieldset>
                <label className="prevention-cutoff">
                  <input
                    type="checkbox"
                    checked={config.cutoff_s !== null}
                    disabled={analyzing}
                    onChange={(event) =>
                      update(
                        'cutoff_s',
                        event.target.checked
                          ? Math.max(
                              catalog.parameters.cutoff_s?.min ?? 0,
                              Math.min(config.duration_s, config.observation_cutoff_s + config.horizon_s),
                            )
                          : null,
                      )
                    }
                  />
                  Coupure électrique programmée
                </label>
                {config.cutoff_s !== null && (
                  <>
                    <Parameter
                      name="cutoff_s"
                      config={config}
                      catalog={catalog}
                      disabled={analyzing}
                      onChange={(value) => update('cutoff_s', value)}
                    />
                    <p className="prevention-small">
                      Une coupure sort du protocole de délai d’allumage. L’échauffement peut rester étudiable.
                    </p>
                  </>
                )}
                {issue && (
                  <p className="prevention-input-issue" role="alert">
                    {issue}
                  </p>
                )}
                <button
                  className="button primary prevention-analyze"
                  disabled={analyzing || !connected || !scene || Boolean(issue)}
                  onClick={() => {
                    void analyze();
                  }}
                >
                  {analyzing ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}
                  {analyzing ? 'Analyse en cours…' : 'Analyser le scénario'}
                </button>
                {analyzing && (
                  <button
                    className="button ghost"
                    onClick={() => {
                      controller.current?.abort();
                      setAnalyzing(false);
                      setAnalysisError('Attente annulée ; le calcul peut encore se terminer sur le poste.');
                    }}
                  >
                    <Square size={12} />
                    Annuler l’attente de l’analyse
                  </button>
                )}
                {!connected && <p className="prevention-small">Le poste de calcul doit être connecté.</p>}
                {analysisError && (
                  <p role="alert" className="prevention-input-issue">
                    {analysisError}
                  </p>
                )}
              </div>
            </aside>
            <div className="prevention-center">
              {stale && (
                <div className="prevention-message prevention-stale" role="status">
                  <TriangleAlert size={16} />
                  Les paramètres ont changé. La carte et les courbes montrent toujours l’analyse{' '}
                  {result?.id.slice(0, 8)}. Relancez le calcul pour les actualiser.
                </div>
              )}
              <section className="panel prevention-scene">
                <div className="panel-heading">
                  <div>
                    <Box size={16} />
                    <h2>{scene?.name ?? config.scene_id}</h2>
                  </div>
                  <button
                    className={`button ghost ${cutaway ? 'active' : ''}`}
                    aria-pressed={cutaway}
                    onClick={() => setCutaway((value) => !value)}
                  >
                    <Layers size={13} />
                    Vue en coupe
                  </button>
                </div>
                <div className="prevention-map-caption">
                  {result
                    ? `Analyse ${result.id.slice(0, 8)} · instant ${format(result.observation_cutoff_s, 2)} s · horizon ${format(result.horizon_s, 2)} s`
                    : 'Sans analyse · composants non évalués'}
                  <span>Emplacements hypothétiques</span>
                </div>
                <Suspense fallback={<div className="prevention-empty">Chargement de la vue 3D…</div>}>
                  <Viewport
                    scene={scene}
                    field="scene"
                    cutaway={cutaway}
                    showSensors={false}
                    showSource={false}
                    slice={false}
                    selectedId={null}
                    onSelect={noObjectSelection}
                    componentMarkers={markers}
                    selectedComponentId={component?.id ?? null}
                    onSelectComponent={setSelectedId}
                  />
                </Suspense>
                <div className="prevention-map-legend">
                  {Object.entries(preventionStates).map(([key, state]) => (
                    <span key={key}>
                      <i style={{ background: state.color }} />
                      {state.label}
                    </span>
                  ))}
                </div>
                <p className="prevention-note">
                  Les repères décrivent des composants, sans interpolation de risque dans la cabine. La
                  vitesse d’air est une hypothèse locale.
                </p>
              </section>
              <section className="panel prevention-components" aria-label="Composants étudiés">
                <div className="panel-heading">
                  <div>
                    <Cable size={16} />
                    <h2>Composants étudiés</h2>
                  </div>
                  <span>{components.length} emplacements</span>
                </div>
                <div className="prevention-component-list">
                  {components.map((entry) => {
                    const entryAssessment = result?.components.find((item) => item.component_id === entry.id);
                    const state = preventionState(entryAssessment);
                    return (
                      <button
                        key={entry.id}
                        data-component-id={entry.id}
                        data-state={state}
                        aria-pressed={entry.id === component?.id}
                        className={entry.id === component?.id ? 'selected' : ''}
                        onClick={() => setSelectedId(entry.id)}
                      >
                        <i style={{ background: preventionStates[state].color }} />
                        <span>
                          <strong>{entry.name}</strong>
                          <small>{preventionStates[state].label}</small>
                        </span>
                        <span>
                          {state !== 'unknown'
                            ? `${format(entryAssessment?.estimate?.ignition_delay_s, 2)} s`
                            : '—'}
                        </span>
                        <ChevronRight size={13} />
                      </button>
                    );
                  })}
                </div>
              </section>
              <PreventionChart
                assessment={assessment}
                cutoff={displayedConfig.observation_cutoff_s}
                horizon={displayedConfig.horizon_s}
                duration={displayedConfig.duration_s}
              />
              {result && (
                <div className="prevention-result-actions">
                  <button
                    className="button secondary"
                    disabled={baseline?.id === result.id}
                    onClick={() => setBaseline(result)}
                  >
                    {baseline?.id === result.id ? <Check size={14} /> : <GitCompareArrows size={14} />}
                    {baseline?.id === result.id
                      ? 'Référence conservée'
                      : 'Conserver cette analyse comme référence'}
                  </button>
                  <a className="button ghost" href={api.preventionExportUrl(result.id)} download>
                    <ArrowDownToLine size={14} />
                    Exporter l’analyse de prévention
                  </a>
                </div>
              )}
              {result && baseline && component && (
                <Comparison
                  result={result}
                  baseline={baseline}
                  componentId={component.id}
                  onClear={() => setBaseline(null)}
                />
              )}
              <details className="panel prevention-details">
                <summary>Provenance & limites de cette étude</summary>
                <ul>
                  {(result?.limitations ?? catalog.limitations).map((limit, index) => (
                    <li key={index}>{limit}</li>
                  ))}
                </ul>
                {result && <pre>{JSON.stringify(result.provenance, null, 2)}</pre>}
                <details className="prevention-component-details">
                  <summary>Modèles chargés & évaluations publiées</summary>
                  <p>
                    Les erreurs d’évaluation décrivent les jeux de test. Elles ne constituent pas un
                    intervalle d’incertitude pour ce composant.
                  </p>
                  <pre>{JSON.stringify(catalog.models, null, 2)}</pre>
                </details>
              </details>
            </div>
            <aside className="prevention-right">
              {component && (
                <>
                  <ComponentInspector
                    component={component}
                    assessment={assessment}
                    result={result}
                    config={displayedConfig}
                  />
                  <PreventionEvidence
                    key={`${result?.id ?? 'unanalysed'}:${component.id}`}
                    componentId={component.id}
                    config={displayedConfig}
                    result={result}
                    stale={stale}
                  />
                </>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
