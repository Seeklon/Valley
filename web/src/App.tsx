import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Box,
  Check,
  ChevronRight,
  CircleDot,
  Cpu,
  Database,
  Expand,
  Eye,
  Flame,
  Gauge,
  Layers,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  ScanLine,
  ShieldCheck,
  SkipBack,
  SlidersHorizontal,
  Square,
  Thermometer,
  TriangleAlert,
  Waves,
  Wind,
  X,
} from 'lucide-react';
import { api, ApiError, messageOf } from './api';
import {
  DEFAULT_CONFIG,
  domainWarnings,
  fieldAvailable,
  finite,
  format,
  nearestByTime,
  usableModel,
} from './data';
import Parameters from './components/Parameters';
import Telemetry, { MetricCards } from './components/Telemetry';
import type { MetricKey } from './components/Telemetry';
import { ModelsView, ScenesView, SourcesView } from './components/Library';
import CampaignPanel from './components/CampaignPanel';
import InsightsPanel from './components/InsightsPanel';
import { ModelConsistency } from './components/ModelDetails';
import type { Catalog, Field, Health, ModelInfo, Run, RunConfig, Source } from './types';

const Viewport = lazy(() => import('./components/Viewport'));
type Tab = 'lab' | 'scenes' | 'models' | 'sources';
const fields: { id: Field; label: string; icon: typeof Box }[] = [
  { id: 'scene', label: 'Géométrie', icon: Box },
  { id: 'temperature', label: 'Température', icon: Thermometer },
  { id: 'airflow', label: 'Airflow', icon: Wind },
  { id: 'smoke', label: 'Fumées', icon: Waves },
  { id: 'oxygen', label: 'Oxygène', icon: CircleDot },
];
const statusLabels: Record<Run['status'], string> = {
  queued: 'En file d’attente',
  running: 'Calcul en cours',
  completed: 'Calcul terminé',
  failed: 'Calcul interrompu',
  cancelled: 'Calcul annulé',
};

function savedRunId(): string | null {
  try {
    return localStorage.getItem('ignis:last-run');
  } catch {
    return null;
  }
}
function saveRunId(id: string): void {
  try {
    localStorage.setItem('ignis:last-run', id);
  } catch {
    /* Browser may disable storage. */
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>('lab');
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [config, setConfig] = useState<RunConfig>({ ...DEFAULT_CONFIG });
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [baseline, setBaseline] = useState<Run | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [field, setField] = useState<Field>('scene');
  const [cutaway, setCutaway] = useState(true);
  const [showSensors, setShowSensors] = useState(true);
  const [slice, setSlice] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [metricKey, setMetricKey] = useState<MetricKey>('temperature_max_c');
  const [showParameters, setShowParameters] = useState(false);
  const initialized = useRef(false);
  const restoreAttempted = useRef(false);
  const launchedRunId = useRef<string | null>(null);
  const scenes = catalog?.scenes ?? [];
  const scene = scenes.find((item) => item.id === config.scene_id);
  const busy = submitting || run?.status === 'queued' || run?.status === 'running';
  const connected = health !== null && !connectionError;
  const loadedModels = models.filter(usableModel);
  const selectedModel = config.model_id
    ? loadedModels.find((model) => model.id === config.model_id)
    : loadedModels[0];
  const warnings = domainWarnings(config, models);
  const sourceModels = health?.capabilities?.source_models ?? [];
  const frames = run?.result?.frames ?? [];
  const metrics = run?.result?.metrics ?? [];
  const maxTime = Math.max(0, ...frames.map((item) => item.time_s), ...metrics.map((item) => item.time_s));
  const frame = nearestByTime(frames, time);
  const metric = nearestByTime(metrics, time);
  const baselineRows = baseline?.result?.metrics ?? [];
  const previousMetric =
    baselineRows.length &&
    time >= baselineRows[0].time_s &&
    time <= baselineRows[baselineRows.length - 1].time_s
      ? nearestByTime(baselineRows, time)
      : undefined;
  const selectedObject = scene?.objects.find((item) => item.id === selectedId);
  const visualizedConfig = run?.result && run.config ? run.config : config;
  const changedSinceRun = Boolean(
    run?.config &&
    (Object.keys(DEFAULT_CONFIG).some(
      (key) => run.config?.[key as keyof RunConfig] !== config[key as keyof RunConfig],
    ) ||
      (run.config.mode === 'prediction' &&
        (run.result?.provenance.model_id ?? run.config.model_id) !== selectedModel?.id)),
  );
  const invalidPower =
    config.ignition_kind === 'resistive' && config.current_a ** 2 * config.resistance_ohm > 10_000;
  const canLaunch =
    connected &&
    health?.worker_available !== false &&
    Boolean(scene) &&
    !busy &&
    (config.mode === 'prediction' || sourceModels.includes(config.source_model)) &&
    config.ignition_duration_s <= config.duration_s &&
    config.ignition_duration_s >= 0.1 &&
    config.ignition_duration_s <= 120 &&
    config.duration_s >= 2 &&
    config.duration_s <= 180 &&
    !invalidPower &&
    (config.mode === 'physics'
      ? health?.capabilities?.physics === true
      : health?.capabilities?.prediction === true && loadedModels.length > 0 && !warnings.length);

  const refresh = useCallback(async () => {
    const responses = await Promise.allSettled([api.health(), api.scenes(), api.models(), api.sources()]);
    const [nextHealth, nextCatalog, nextModels, nextSources] = responses;
    if (nextHealth.status === 'fulfilled') {
      setHealth(nextHealth.value);
      setConnectionError(null);
    } else {
      setConnectionError(messageOf(nextHealth.reason));
    }
    if (nextCatalog.status === 'fulfilled' && Array.isArray(nextCatalog.value.scenes)) {
      setCatalog((previous) =>
        JSON.stringify(previous) === JSON.stringify(nextCatalog.value) ? previous : nextCatalog.value,
      );
      setCatalogError(null);
      if (!initialized.current && nextCatalog.value.scenes.length) {
        const initial =
          nextCatalog.value.scenes.find((item) => item.id === 'habitat') ?? nextCatalog.value.scenes[0];
        setConfig({ ...DEFAULT_CONFIG, ...initial.defaults, scene_id: initial.id });
        initialized.current = true;
      }
    } else if (nextCatalog.status === 'rejected') setCatalogError(messageOf(nextCatalog.reason));
    if (nextModels.status === 'fulfilled') setModels(nextModels.value);
    if (nextSources.status === 'fulfilled') setSources(nextSources.value);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => {
      void refresh();
    }, 30_000);
    return () => clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    if (!catalog || restoreAttempted.current) return;
    restoreAttempted.current = true;
    const id = savedRunId();
    if (id)
      void api
        .run(id)
        .then((previous) => {
          if (!previous.config || !catalog.scenes.some((item) => item.id === previous.config?.scene_id))
            return;
          setRun(previous);
          setConfig(previous.config);
        })
        .catch(() => {
          /* A missing historical run does not prevent a new experiment. */
        });
  }, [catalog]);

  useEffect(() => {
    if (!run || !['queued', 'running'].includes(run.status)) return;
    const id = run.id;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.run(id, controller.signal);
        if (controller.signal.aborted) return;
        setRun(next);
        setPollError(null);
        if (['queued', 'running'].includes(next.status))
          timer = setTimeout(() => {
            void poll();
          }, 1800);
      } catch (reason) {
        if (!controller.signal.aborted) {
          if (reason instanceof ApiError && reason.status === 404) {
            setRun((previous) =>
              previous
                ? {
                    ...previous,
                    status: 'failed',
                    message: 'Ce calcul n’existe plus dans le registre du poste.',
                  }
                : previous,
            );
            return;
          }
          setPollError(messageOf(reason));
          timer = setTimeout(() => {
            void poll();
          }, 4000);
        }
      }
    };
    timer = setTimeout(() => {
      void poll();
    }, 400);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [run?.id, run?.status]);

  useEffect(() => {
    if (run?.status === 'completed') {
      setHistory((previous) => [run, ...previous.filter((item) => item.id !== run.id)].slice(0, 8));
      if (launchedRunId.current === run.id && run.result) {
        launchedRunId.current = null;
        const firstFrame = run.result.frames[0];
        setField(
          fieldAvailable(firstFrame, 'temperature')
            ? 'temperature'
            : fieldAvailable(firstFrame, 'airflow')
              ? 'airflow'
              : 'scene',
        );
        const animate = Boolean(firstFrame) && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        setTime(animate ? 0 : Math.max(0, ...run.result.metrics.map((row) => row.time_s)));
        setPlaying(animate);
      }
    }
  }, [run]);

  useEffect(() => {
    if (!playing || maxTime <= 0) return;
    const interval = setInterval(
      () =>
        setTime((previous) => {
          if (previous >= maxTime) {
            setPlaying(false);
            return maxTime;
          }
          return Math.min(maxTime, previous + Math.max(maxTime / 150, 0.1));
        }),
      100,
    );
    return () => clearInterval(interval);
  }, [playing, maxTime]);

  const changeScene = (id: string) => {
    if (busy) return;
    const next = scenes.find((item) => item.id === id);
    if (!next) return;
    setConfig({ ...DEFAULT_CONFIG, ...next.defaults, mode: config.mode, scene_id: id });
    setRun(null);
    setBaseline(null);
    setSelectedId(null);
    setTime(0);
    setPlaying(false);
    setField('scene');
    setError(null);
  };

  const launch = async () => {
    if (!canLaunch) return;
    setSubmitting(true);
    setError(null);
    setPollError(null);
    setPlaying(false);
    setTime(0);
    try {
      const next = await api.launch(config);
      launchedRunId.current = next.id;
      setRun({ ...next, config: next.config ?? { ...config } });
      saveRunId(next.id);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!run || cancelling) return;
    setCancelling(true);
    try {
      const next = await api.cancel(run.id);
      setRun({ ...run, ...next });
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setCancelling(false);
    }
  };

  const restore = (previous: Run) => {
    if (busy || !previous.config) return;
    setRun(previous);
    setConfig(previous.config);
    setTime(0);
    setPlaying(false);
    setSelectedId(null);
    if (baseline?.config?.scene_id !== previous.config.scene_id) setBaseline(null);
  };

  let unavailableReason = '';
  if (!connected) unavailableReason = 'Le poste de calcul est déconnecté.';
  else if (health?.worker_available === false)
    unavailableReason = 'Le service est connecté, mais le worker de calcul est indisponible.';
  else if (config.mode === 'prediction' && !loadedModels.length)
    unavailableReason = 'Aucun modèle entraîné n’est chargé.';
  else if (config.mode === 'prediction' && warnings.length)
    unavailableReason = 'Ces paramètres sortent du domaine du modèle.';
  else if (config.mode === 'physics' && health?.capabilities?.physics !== true)
    unavailableReason = 'Le moteur physique n’est pas disponible.';
  else if (config.mode === 'prediction' && health?.capabilities?.prediction !== true)
    unavailableReason = 'Le service de prédiction n’est pas disponible.';
  else if (config.ignition_duration_s > config.duration_s)
    unavailableReason = 'L’allumage doit se terminer avant la fin de l’essai.';
  else if (config.duration_s < 2 || config.duration_s > 180)
    unavailableReason = 'La durée de calcul doit être comprise entre 2 et 180 secondes.';
  else if (config.ignition_duration_s < 0.1 || config.ignition_duration_s > 120)
    unavailableReason = 'La durée de la source doit être comprise entre 0,1 et 120 secondes.';
  else if (invalidPower) unavailableReason = 'La puissance résistive dépasse la limite de 10 kW.';

  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          href="#"
          className="brand"
          onClick={(event) => {
            event.preventDefault();
            setTab('lab');
          }}
          aria-label="IGNIS, revenir au laboratoire"
        >
          <span className="brand-mark">
            <Flame size={24} fill="currentColor" />
          </span>
          <span>
            IGNIS<span className="brand-sub">MICROGRAVITY FIRE LAB</span>
          </span>
          <span className="brand-version">3D</span>
        </a>
        <nav className="main-nav" aria-label="Navigation principale">
          {(
            [
              { id: 'lab', label: 'Laboratoire', icon: Activity },
              { id: 'scenes', label: 'Scènes', icon: Box },
              { id: 'models', label: 'Modèles', icon: Cpu },
              { id: 'sources', label: 'Sources NASA', icon: Database },
            ] as const
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={tab === id ? 'active' : ''}
              onClick={() => setTab(id)}
              aria-label={label}
              aria-current={tab === id ? 'page' : undefined}
            >
              <Icon size={16} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="runtime-status">
          <span className={`connection-dot ${connected ? 'connected' : ''} ${loading ? 'pulse' : ''}`} />
          <div>
            <strong>{loading ? 'Connexion…' : connected ? 'Poste connecté' : 'Poste déconnecté'}</strong>
            <span>
              {connected
                ? `${loadedModels.length} modèle${loadedModels.length > 1 ? 's' : ''} chargé${loadedModels.length > 1 ? 's' : ''}`
                : 'Calcul local · Tailscale'}
            </span>
          </div>
          <button
            className="icon-button"
            onClick={() => {
              void refresh();
            }}
            aria-label="Actualiser la connexion"
            title="Actualiser"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </header>

      <main>
        {(connectionError || catalogError) && (
          <div className="connection-banner" role="status">
            <Radio size={16} />
            <span>{connectionError ?? `Catalogue : ${catalogError}`}</span>
            <button
              onClick={() => {
                void refresh();
              }}
            >
              Réessayer <RefreshCw size={13} />
            </button>
          </div>
        )}
        {tab === 'models' && <ModelsView models={models} connected={connected} />}
        {tab === 'sources' && <SourcesView sources={sources} />}
        {tab === 'scenes' && (
          <ScenesView
            scenes={scenes}
            selectedId={config.scene_id}
            onSelect={(id) => {
              changeScene(id);
              setTab('lab');
            }}
          />
        )}
        {tab === 'lab' && (
          <>
            <section className="workspace-heading">
              <div>
                <div className="breadcrumb">
                  ESPACE DE TRAVAIL <ChevronRight size={11} /> COMBUSTION EN MICROGRAVITÉ
                </div>
                <h1>
                  Explorer le feu, <span>au-delà de la gravité.</span>
                </h1>
                <p>
                  Configurez un environnement. Observez son évolution. Confrontez la prédiction aux données.
                </p>
              </div>
              <div className="workspace-meta">
                <span className="status-chip">
                  <span className="status-dot" /> Modèle exploratoire
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
            <div className="workspace-toolbar">
              <div className="scenario-tabs" aria-label="Variantes de scène">
                {scenes.length ? (
                  scenes.map((item, index) => (
                    <button
                      key={item.id}
                      disabled={busy}
                      className={config.scene_id === item.id ? 'active' : ''}
                      onClick={() => changeScene(item.id)}
                    >
                      <span>{String(index + 1).padStart(2, '0')}</span>
                      {item.name}
                    </button>
                  ))
                ) : (
                  <span className="muted">
                    {loading ? 'Chargement des environnements…' : 'Aucune scène disponible'}
                  </span>
                )}
              </div>
              <button
                className="button ghost mobile-parameters"
                onClick={() => setShowParameters(!showParameters)}
              >
                <SlidersHorizontal size={15} /> Paramètres
              </button>
              <button
                className="button ghost"
                onClick={() => {
                  if (scene) {
                    setConfig({
                      ...DEFAULT_CONFIG,
                      ...scene.defaults,
                      scene_id: scene.id,
                      mode: config.mode,
                    });
                  }
                }}
                disabled={!scene || busy}
              >
                <RotateCcw size={14} /> Réinitialiser
              </button>
            </div>
            <div className={`workspace-grid ${showParameters ? 'parameters-visible' : ''}`}>
              <Parameters
                config={config}
                onChange={setConfig}
                scenes={scenes}
                materials={catalog?.materials ?? []}
                onSceneChange={changeScene}
                disabled={busy}
                sourceModels={sourceModels}
              />
              <div className="workspace-center">
                <section className="panel scene-panel">
                  <div className="scene-panel-heading">
                    <div>
                      <span className="scene-title-icon">
                        <Box size={17} />
                      </span>
                      <h2>{scene?.name ?? 'Compartiment spatial'}</h2>
                      <span className="muted small">
                        {scene?.bounds_m.map((value) => format(value, 1)).join(' × ')}
                        {scene ? ' m' : ''}
                      </span>
                    </div>
                    <span className="tiny-label">
                      {visualizedConfig.gravity_g < 0.01 ? 'µg' : '1 g'}
                      <span className="label-divider" />
                      {format(visualizedConfig.oxygen_percent, 1)} % O₂
                    </span>
                  </div>
                  <div className="field-tabs" role="group" aria-label="Champ affiché">
                    {fields.map(({ id, label, icon: Icon }) => (
                      <button
                        key={id}
                        className={field === id ? 'active' : ''}
                        disabled={id !== 'scene' && !fieldAvailable(frame, id)}
                        onClick={() => setField(id)}
                        title={
                          id !== 'scene' && !fieldAvailable(frame, id)
                            ? 'Ce champ sera disponible si le calcul le fournit.'
                            : label
                        }
                      >
                        <Icon size={14} />
                        {label}
                      </button>
                    ))}
                  </div>
                  <Suspense
                    fallback={
                      <div className="viewport-suspense">
                        <LoaderCircle className="spin" /> Initialisation du rendu 3D…
                      </div>
                    }
                  >
                    <Viewport
                      scene={scene}
                      frame={frame}
                      field={field}
                      cutaway={cutaway}
                      showSensors={showSensors}
                      slice={slice}
                      selectedId={selectedId}
                      onSelect={setSelectedId}
                    />
                  </Suspense>
                  <div className="viewport-settings">
                    <div className="view-toggles">
                      <button
                        className={cutaway ? 'active' : ''}
                        onClick={() => setCutaway(!cutaway)}
                        aria-pressed={cutaway}
                      >
                        <Layers size={13} /> Écorché
                      </button>
                      <button
                        className={showSensors ? 'active' : ''}
                        onClick={() => setShowSensors(!showSensors)}
                        aria-pressed={showSensors}
                      >
                        <ScanLine size={13} /> Repères
                      </button>
                      <button
                        disabled={field === 'scene'}
                        className={slice ? 'active' : ''}
                        onClick={() => setSlice(!slice)}
                        aria-pressed={slice}
                      >
                        <Expand size={13} /> Coupe X centrale
                      </button>
                    </div>
                    <span className="field-legend">
                      {field === 'temperature' ? (
                        <>
                          <i className="heat-gradient" />
                          26–800 °C
                        </>
                      ) : field === 'airflow' ? (
                        'Vitesse locale · m/s'
                      ) : field === 'smoke' ? (
                        'Concentration relative au maximum de la frame'
                      ) : field === 'oxygen' ? (
                        <>
                          <i className="oxygen-gradient" />
                          0–30 % vol.
                        </>
                      ) : (
                        <>
                          <i className="sensor-dot" />
                          Capteurs <i className="source-dot" />
                          Allumage
                        </>
                      )}
                    </span>
                  </div>
                  <div className="timeline">
                    <button
                      className="icon-button"
                      aria-label="Revenir au début"
                      onClick={() => {
                        setTime(0);
                        setPlaying(false);
                      }}
                      disabled={!maxTime}
                    >
                      <SkipBack size={15} />
                    </button>
                    <button
                      className="play-timeline"
                      aria-label={playing ? 'Suspendre la lecture' : 'Lire les résultats'}
                      disabled={!maxTime}
                      onClick={() => {
                        if (time >= maxTime) setTime(0);
                        setPlaying(!playing);
                      }}
                    >
                      {playing ? <Pause size={16} /> : <Play size={16} fill="currentColor" />}
                    </button>
                    <span className="time-value">
                      {format(time, 1)}
                      <small> s</small>
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={Math.max(1, maxTime)}
                      step={0.1}
                      value={time}
                      disabled={!maxTime}
                      aria-label="Instant de visualisation"
                      onChange={(event) => {
                        setTime(Number(event.target.value));
                        setPlaying(false);
                      }}
                    />
                    <span className="muted small">{format(maxTime, 0)} s</span>
                    <span className="timeline-caption">
                      {frames.length
                        ? `${frames.length} frames`
                        : metrics.length
                          ? 'Métriques uniquement'
                          : 'Aucun résultat'}
                    </span>
                  </div>
                  {changedSinceRun && run?.result && (
                    <div className="result-context">
                      <TriangleAlert size={13} /> Les paramètres ont changé. La visualisation correspond au
                      dernier essai enregistré.
                    </div>
                  )}
                </section>
                <MetricCards metric={metric} previous={previousMetric} />
                <Telemetry
                  run={run}
                  baseline={baseline}
                  time={time}
                  metricKey={metricKey}
                  onMetricChange={setMetricKey}
                />
              </div>
              <aside className="insights-column">
                <section className="panel execution-panel">
                  <div className="panel-heading">
                    <div>
                      <Cpu size={16} />
                      <h2>Exécution</h2>
                    </div>
                    <span className="eyebrow">LOCAL</span>
                  </div>
                  <div className="execution-content">
                    <div className="segmented mode-switch">
                      <button
                        className={config.mode === 'physics' ? 'active' : ''}
                        disabled={busy}
                        onClick={() => setConfig({ ...config, mode: 'physics' })}
                      >
                        <Flame size={14} /> Physique
                      </button>
                      <button
                        className={config.mode === 'prediction' ? 'active' : ''}
                        disabled={busy}
                        onClick={() => setConfig({ ...config, mode: 'prediction' })}
                      >
                        <Cpu size={14} /> Prédiction
                      </button>
                    </div>
                    <div className="engine-description">
                      <span className={`engine-icon ${config.mode}`}>
                        <Cpu size={21} />
                      </span>
                      <div>
                        <strong>
                          {config.mode === 'physics'
                            ? 'Solveur physique 3D'
                            : (selectedModel?.name ?? 'Modèle de substitution')}
                        </strong>
                        <p>
                          {config.mode === 'physics'
                            ? 'Calcul de l’écoulement et des effets thermiques.'
                            : selectedModel?.kind === 'spatial_mlp'
                              ? 'Prédiction des champs 3D et des métriques.'
                              : selectedModel?.kind === 'scalar_forest'
                                ? 'Prédiction des métriques ; aucun champ 3D.'
                                : 'Inférence avec les poids enregistrés sur le poste.'}
                        </p>
                      </div>
                    </div>
                    {config.mode === 'prediction' &&
                      (loadedModels.length > 1 || (config.model_id && !selectedModel)) && (
                        <label className="model-picker">
                          Modèle chargé
                          <select
                            value={config.model_id ?? loadedModels[0]?.id ?? ''}
                            disabled={busy}
                            onChange={(event) => setConfig({ ...config, model_id: event.target.value })}
                          >
                            {config.model_id && !selectedModel && (
                              <option value={config.model_id} disabled>
                                Modèle indisponible · {config.model_id}
                              </option>
                            )}
                            {loadedModels.map((model) => (
                              <option key={model.id} value={model.id}>
                                {model.name ?? model.id}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                    {config.mode === 'prediction' && (
                      <div
                        className={`model-readiness ${loadedModels.length && !warnings.length ? 'ready' : ''}`}
                      >
                        <ShieldCheck size={14} />
                        <span>
                          {!loadedModels.length
                            ? 'En attente d’un modèle chargé'
                            : !selectedModel
                              ? 'Modèle sélectionné indisponible'
                              : warnings.length
                                ? 'Paramètres hors domaine'
                                : 'Modèle chargé · contrôle final par le serveur'}
                        </span>
                      </div>
                    )}
                    {warnings.length > 0 && (
                      <ul className="domain-warnings">
                        {warnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    )}
                    {config.mode === 'prediction' && selectedModel && (
                      <ModelConsistency model={selectedModel} compact />
                    )}
                    <button
                      className="button primary launch-button"
                      disabled={!canLaunch}
                      onClick={() => {
                        void launch();
                      }}
                    >
                      {submitting ? (
                        <LoaderCircle className="spin" size={17} />
                      ) : (
                        <Play size={16} fill="currentColor" />
                      )}
                      {busy
                        ? 'Exécution en cours'
                        : config.mode === 'physics'
                          ? 'Lancer la simulation'
                          : 'Lancer la prédiction'}
                    </button>
                    {unavailableReason && !busy && <p className="unavailable-reason">{unavailableReason}</p>}
                    {run && (
                      <div className={`job-status ${run.status}`} role="status">
                        <div>
                          <span>
                            {['running', 'queued'].includes(run.status) ? (
                              <LoaderCircle className="spin" size={14} />
                            ) : run.status === 'completed' ? (
                              <Check size={14} />
                            ) : (
                              <TriangleAlert size={14} />
                            )}
                            {statusLabels[run.status]}
                          </span>
                          <code>{run.id.slice(0, 8)}</code>
                        </div>
                        {['queued', 'running'].includes(run.status) && (
                          <>
                            <progress
                              max={1}
                              value={
                                finite(run.progress) ? Math.max(0, Math.min(1, run.progress)) : undefined
                              }
                              aria-label="Progression du calcul"
                            />
                            <button
                              className="text-button"
                              disabled={cancelling}
                              onClick={() => {
                                void cancel();
                              }}
                            >
                              <Square size={10} />
                              {cancelling ? 'Annulation…' : 'Annuler le calcul'}
                            </button>
                          </>
                        )}
                        {run.message && <p>{run.message}</p>}
                        {run.error && <p>{run.error}</p>}
                      </div>
                    )}
                    {(error || pollError) && (
                      <div className="inline-error" role="alert">
                        <TriangleAlert size={15} />
                        <p>
                          {error ?? pollError}
                          {pollError && <span> Le suivi sera réessayé sans relancer le calcul.</span>}
                        </p>
                        <button
                          className="icon-button"
                          aria-label="Fermer le message"
                          onClick={() => {
                            setError(null);
                            setPollError(null);
                          }}
                        >
                          <X size={12} />
                        </button>
                      </div>
                    )}
                  </div>
                </section>
                <section className="panel inspection-panel">
                  <div className="panel-heading">
                    <div>
                      <Eye size={16} />
                      <h2>Inspecteur</h2>
                    </div>
                    {selectedObject && (
                      <button
                        className="icon-button"
                        aria-label="Désélectionner l’objet"
                        onClick={() => setSelectedId(null)}
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                  <div className="inspection-content">
                    {selectedObject ? (
                      <>
                        <span className="eyebrow amber-text">
                          {selectedObject.role === 'fuel'
                            ? 'ÉCHANTILLON COMBUSTIBLE'
                            : selectedObject.role.toUpperCase()}
                        </span>
                        <h3>{selectedObject.name}</h3>
                        <dl className="object-properties">
                          <div>
                            <dt>Matériau</dt>
                            <dd>
                              {catalog?.materials.find((item) => item.id === selectedObject.material_id)
                                ?.name ?? selectedObject.material_id}
                            </dd>
                          </div>
                          <div>
                            <dt>Dimensions</dt>
                            <dd>{selectedObject.size_m.map((value) => format(value, 2)).join(' × ')} m</dd>
                          </div>
                          <div>
                            <dt>Position X / Y / Z</dt>
                            <dd>{selectedObject.center_m.map((value) => format(value, 2)).join(' / ')} m</dd>
                          </div>
                        </dl>
                        <p className="field-help">
                          Propriétés de la scène. Le matériau de l’échantillon est remplacé par le choix de
                          configuration lors du calcul.
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="inspection-symbol">
                          <ScanLine size={27} strokeWidth={1.2} />
                        </div>
                        <h3>Explorez le compartiment</h3>
                        <p>
                          Sélectionnez un équipement dans la scène pour consulter ses propriétés physiques.
                        </p>
                        {scene && (
                          <label className="sr-only" htmlFor="object-select">
                            Sélectionner un objet par son nom
                          </label>
                        )}
                        {scene && (
                          <select
                            id="object-select"
                            value=""
                            onChange={(event) => setSelectedId(event.target.value)}
                          >
                            <option value="">Choisir un objet…</option>
                            {scene.objects
                              .filter((object) => object.role !== 'decoration')
                              .map((object) => (
                                <option key={object.id} value={object.id}>
                                  {object.name}
                                </option>
                              ))}
                          </select>
                        )}
                      </>
                    )}
                  </div>
                </section>
                <section className="panel comparison-panel">
                  <div className="panel-heading">
                    <div>
                      <Gauge size={16} />
                      <h2>Comparaison</h2>
                    </div>
                  </div>
                  <div className="comparison-content">
                    {baseline ? (
                      <div className="baseline-card">
                        <div>
                          <span className="status-dot" />
                          <strong>Référence conservée</strong>
                          <button
                            className="icon-button"
                            aria-label="Retirer la référence"
                            onClick={() => setBaseline(null)}
                          >
                            <X size={12} />
                          </button>
                        </div>
                        <code>
                          {baseline.id.slice(0, 8)} ·{' '}
                          {baseline.config?.mode === 'prediction' ? 'Prédiction' : 'Physique'}
                        </code>
                        <p>
                          {format(baseline.config?.airflow_m_s, 2)} m/s ·{' '}
                          {format(baseline.config?.oxygen_percent, 1)} % O₂
                        </p>
                      </div>
                    ) : (
                      <p>
                        Conservez un essai comme référence, puis changez les conditions pour comparer les
                        courbes.
                      </p>
                    )}
                    <button
                      className="button secondary full-width"
                      disabled={!run?.result || run.status !== 'completed' || busy}
                      onClick={() => setBaseline(run)}
                    >
                      <Plus size={14} /> Définir comme référence
                    </button>
                    {run?.status === 'completed' && (
                      <a
                        className="button ghost full-width export-link"
                        href={api.exportUrl(run.id)}
                        download
                      >
                        <ArrowDownToLine size={14} /> Exporter cet essai
                      </a>
                    )}
                  </div>
                </section>
                {history.length > 0 && (
                  <section className="panel history-panel">
                    <div className="panel-heading">
                      <div>
                        <Activity size={15} />
                        <h2>Essais de la session</h2>
                      </div>
                    </div>
                    <div className="history-list">
                      {history.map((item) => (
                        <button
                          key={item.id}
                          disabled={busy}
                          className={item.id === run?.id ? 'active' : ''}
                          onClick={() => restore(item)}
                        >
                          <span>
                            {item.config?.mode === 'prediction' ? <Cpu size={13} /> : <Flame size={13} />}
                            <code>{item.id.slice(0, 8)}</code>
                          </span>
                          <span>
                            {format(item.config?.airflow_m_s, 2)} m/s <ChevronRight size={12} />
                          </span>
                        </button>
                      ))}
                    </div>
                  </section>
                )}
              </aside>
            </div>
            {run?.result && (
              <section className="result-provenance panel">
                <div>
                  <ShieldCheck size={16} />
                  <strong>Provenance du résultat</strong>
                  <code>
                    {run.result.provenance.engine}
                    {run.result.provenance.engine_version ? ` ${run.result.provenance.engine_version}` : ''}
                  </code>
                  {run.result.provenance.model_id && <code>{run.result.provenance.model_id}</code>}
                </div>
                {run.result.provenance.scientific_status && <p>{run.result.provenance.scientific_status}</p>}
                {run.result.provenance.warnings?.map((warning) => (
                  <p key={warning}>
                    <TriangleAlert size={13} />
                    {warning}
                  </p>
                ))}
                <details className="raw-details">
                  <summary>Métadonnées complètes et configuration de l’essai</summary>
                  <pre>
                    {JSON.stringify(
                      { config: run.config, provenance: run.result.provenance, summary: run.result.summary },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </section>
            )}
            <CampaignPanel
              config={config}
              scenes={scenes}
              available={connected && health?.capabilities?.campaigns === true}
              busy={busy}
            />
            <InsightsPanel
              config={config}
              available={connected && health?.capabilities?.insights !== false}
              busy={busy}
            />
          </>
        )}
      </main>
      <footer className="app-footer">
        <span>
          <Flame size={13} /> IGNIS <span className="footer-divider" /> Laboratoire exploratoire de combustion
        </span>
        <span>
          Sources expérimentales, simulations et prédictions identifiées séparément.
          <button onClick={() => setTab('sources')}>
            Consulter les sources <ArrowRight size={12} />
          </button>
        </span>
      </footer>
    </div>
  );
}
