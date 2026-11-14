import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Box,
  ChevronRight,
  Crosshair,
  Eye,
  Focus,
  Layers,
  LoaderCircle,
  Maximize2,
  PanelRightClose,
  PanelRightOpen,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  SkipBack,
  Thermometer,
  Waves,
  Wind,
  Zap,
} from 'lucide-react';
import { api, messageOf } from '../api';
import { finite, format, nearestByTime } from '../data';
import { componentTemperature, componentTemperatureColor, sceneReplays } from '../mission-state';
import { missionScales, MISSION_TEMPERATURE_GRADIENT } from '../mission-rendering';
import type { MissionCamera, MissionLayer } from '../mission-rendering';
import { preventionConfigIssue, preventionStatusLabels } from '../prevention';
import type {
  PreventionCatalog,
  PreventionConfig,
  PreventionInterpretation,
  PreventionResult,
} from '../prevention';
import type { Run, Scene, ViewportMarker } from '../types';
import type { PreventionSession } from './PreventionView';
import '../mission.css';

const MissionViewport = lazy(() => import('./MissionViewport'));
const EMPTY_FRAMES: NonNullable<Run['result']>['frames'] = [];
type MissionMode = 'propagation' | 'prevention';

const layers: { id: MissionLayer; name: string; icon: typeof Box }[] = [
  { id: 'thermal-smoke', name: 'Fumée thermique', icon: Layers },
  { id: 'smoke', name: 'Fumée', icon: Waves },
  { id: 'temperature', name: 'Température', icon: Thermometer },
  { id: 'airflow', name: 'Ventilation', icon: Wind },
  { id: 'scene', name: 'Cabine seule', icon: Box },
];

function MiniTrace({
  points,
  time,
  duration,
  label,
}: {
  points: { time_s: number; value: number | undefined }[];
  time: number;
  duration: number;
  label: string;
}) {
  const values = points.map((row) => row.value).filter(finite);
  if (!values.length) return null;
  const low = Math.min(...values);
  const high = Math.max(low + 1, ...values);
  let pen = false;
  const path = points
    .map((row) => {
      if (!finite(row.value)) {
        pen = false;
        return '';
      }
      const command = pen ? 'L' : 'M';
      pen = true;
      return `${command}${(row.time_s / duration) * 240},${48 - ((row.value - low) / (high - low)) * 40}`;
    })
    .join(' ');
  return (
    <div className="mission-trace">
      <div>
        <span>{label}</span>
        <span>{format(high, 0)} °C</span>
      </div>
      <svg viewBox="0 0 240 54" role="img" aria-label={label}>
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.8" />
        <line
          x1={(time / duration) * 240}
          x2={(time / duration) * 240}
          y1="0"
          y2="54"
          stroke="#e8f0ed"
          strokeWidth="1"
        />
      </svg>
    </div>
  );
}

export default function MissionView({
  scenes,
  connected,
  session,
  onSessionChange,
  onOpenPrevention,
  onOpenLab,
}: {
  scenes: Scene[];
  connected: boolean;
  session: PreventionSession | null;
  onSessionChange: (session: PreventionSession) => void;
  onOpenPrevention: (session?: PreventionSession) => void;
  onOpenLab: (sceneId: string, run: Run | null) => void;
}) {
  const [sceneId, setSceneId] = useState(session?.config?.scene_id ?? 'soyuz');
  const [mode, setMode] = useState<MissionMode>(session?.config ? 'prevention' : 'propagation');
  const [camera, setCamera] = useState<MissionCamera>('pov');
  const [layer, setLayer] = useState<MissionLayer>('thermal-smoke');
  const [opacity, setOpacity] = useState(0.72);
  const [cutaway, setCutaway] = useState(session?.cutaway ?? true);
  const [resetToken, setResetToken] = useState(0);
  const [railOpen, setRailOpen] = useState(true);
  const [runs, setRuns] = useState<Run[]>([]);
  const [nonSpatialRunIds, setNonSpatialRunIds] = useState<string[]>([]);
  const [runId, setRunId] = useState('');
  const [run, setRun] = useState<Run | null>(null);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [time, setTime] = useState(session?.config?.observation_cutoff_s ?? 0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [catalog, setCatalog] = useState<PreventionCatalog | null>(null);
  const [config, setConfig] = useState<PreventionConfig | null>(session?.config ?? null);
  const [analysis, setAnalysis] = useState<PreventionResult | null>(session?.result ?? null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(session?.selectedId ?? null);
  const [interpretation, setInterpretation] = useState<PreventionInterpretation | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const analysisController = useRef<AbortController | null>(null);
  const interpretationController = useRef<AbortController | null>(null);

  const scene = scenes.find((item) => item.id === sceneId);
  const replays = useMemo(
    () => sceneReplays(runs, sceneId).filter((item) => !nonSpatialRunIds.includes(item.id)),
    [runs, sceneId, nonSpatialRunIds],
  );
  const frames = mode === 'propagation' ? (run?.result?.frames ?? EMPTY_FRAMES) : EMPTY_FRAMES;
  const scales = useMemo(() => missionScales(frames), [frames]);
  const activeAnalysis =
    analysis &&
    config &&
    Object.keys(config).every(
      (key) => config[key as keyof PreventionConfig] === analysis.config[key as keyof PreventionConfig],
    )
      ? analysis
      : null;
  const components = useMemo(
    () => catalog?.components.filter((item) => item.scene_id === sceneId) ?? [],
    [catalog, sceneId],
  );
  const selected = components.find((item) => item.id === selectedId) ?? components[0];
  const assessment = activeAnalysis?.components.find((item) => item.component_id === selected?.id);
  const cutoff = activeAnalysis?.observation_cutoff_s ?? config?.observation_cutoff_s ?? 0;
  const componentValue = componentTemperature(assessment, time, cutoff);
  const maxTime =
    mode === 'propagation'
      ? Math.max(0, ...frames.map((item) => item.time_s))
      : activeAnalysis
        ? activeAnalysis.observation_cutoff_s + activeAnalysis.horizon_s
        : 0;
  const firstTime = mode === 'propagation' ? (frames[0]?.time_s ?? 0) : 0;
  const metric = mode === 'propagation' ? nearestByTime(run?.result?.metrics ?? [], time) : undefined;
  const isFds = run?.config?.mode === 'physics';
  const isCoupled = run?.config?.source_model === 'coupled_combustion';
  const isResistive = run?.config?.ignition_kind === 'resistive';
  const sourcePower =
    isResistive && run?.config
      ? run.config.current_a ** 2 * run.config.resistance_ohm
      : run?.config?.ignition_power_w;
  const sourceLabel = isCoupled ? 'Combustion couplée' : 'Source imposée';
  const evidence = activeAnalysis?.evidence_snapshots_by_component?.[selected?.id ?? '']?.findings ?? [];
  const ignitionEvidence = assessment?.estimate
    ? evidence.find((item) => item.is_nasa_source === false)
    : undefined;
  const configIssue = config && catalog ? preventionConfigIssue(config, catalog) : null;
  const markers = useMemo<ViewportMarker[]>(
    () =>
      mode === 'prevention'
        ? components.map((item) => {
            const row = activeAnalysis?.components.find((entry) => entry.component_id === item.id);
            const temperature = componentTemperature(row, time, cutoff);
            return {
              ...item,
              object_id: item.object_id ?? undefined,
              color: componentTemperatureColor(temperature?.value),
            };
          })
        : [],
    [mode, components, activeAnalysis, time, cutoff],
  );

  useEffect(() => {
    if (mode !== 'prevention' || !config) return;
    onSessionChange({
      config,
      result: activeAnalysis,
      selectedId,
      mode: 'design',
      cutaway,
      baseline: session?.baseline ?? null,
    });
  }, [mode, config, activeAnalysis, selectedId, cutaway, onSessionChange, session?.baseline]);

  useEffect(() => {
    if (scenes.length && !scenes.some((item) => item.id === sceneId)) setSceneId(scenes[0].id);
  }, [scenes, sceneId]);

  useEffect(() => {
    const controller = new AbortController();
    void api
      .runs(controller.signal)
      .then(setRuns)
      .catch((error) => {
        if (!controller.signal.aborted) setRunError(messageOf(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setRunsLoading(false);
      });
    void api
      .preventionCatalog(controller.signal)
      .then((next) => {
        setCatalog(next);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setAnalysisError(messageOf(error));
      });
    return () => controller.abort();
  }, [connected]);

  useEffect(() => {
    if (!catalog) return;
    setConfig((previous) =>
      previous?.scene_id === sceneId ? previous : { ...(previous ?? catalog.defaults), scene_id: sceneId },
    );
  }, [catalog, sceneId]);

  useEffect(() => {
    setRunId(replays[0]?.id ?? '');
  }, [replays]);

  useEffect(() => {
    setRun(null);
    setPlaying(false);
    if (modeRef.current === 'propagation') setTime(0);
    if (!runId) {
      setRunLoading(false);
      return;
    }
    const controller = new AbortController();
    setRunLoading(true);
    setRunError(null);
    void api
      .run(runId, controller.signal)
      .then((next) => {
        if (controller.signal.aborted || next.config?.scene_id !== sceneId) return;
        const all = next.result?.frames ?? [];
        if (!all.length) {
          setNonSpatialRunIds((previous) => (previous.includes(next.id) ? previous : [...previous, next.id]));
          return;
        }
        setRun(next);
        // Open at an actual saved frame so the spatial phenomenon is immediately visible.
        const peak = all.reduce(
          (best, frame) => {
            const density =
              frame.smoke_kg_m3?.reduce<number>(
                (sum, value, index) =>
                  frame.valid_mask?.[index] !== false && finite(value) ? sum + value : sum,
                0,
              ) ?? 0;
            return density > best.density ? { time: frame.time_s, density } : best;
          },
          { time: all[0]?.time_s ?? 0, density: 0 },
        );
        if (modeRef.current === 'propagation') setTime(peak.time);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setRunError(messageOf(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setRunLoading(false);
      });
    return () => controller.abort();
  }, [runId, sceneId]);

  useEffect(() => {
    if (!playing || maxTime <= firstTime) return;
    let raf = 0;
    let previous = performance.now();
    let accumulated = 0;
    const tick = (now: number) => {
      accumulated += document.hidden ? 0 : (now - previous) / 1000;
      previous = now;
      if (accumulated >= 1 / 24) {
        const step = accumulated * speed;
        accumulated = 0;
        setTime((value) => Math.min(maxTime, value + step));
      }
      raf = requestAnimationFrame(tick);
    };
    const visibilityChanged = () => {
      previous = performance.now();
      accumulated = 0;
    };
    document.addEventListener('visibilitychange', visibilityChanged);
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  }, [playing, speed, maxTime, firstTime]);
  useEffect(() => {
    if (time >= maxTime) setPlaying(false);
  }, [time, maxTime]);
  useEffect(() => {
    interpretationController.current?.abort();
    setInterpretation(null);
    setInterpretError(null);
    setInterpreting(false);
  }, [selectedId, activeAnalysis?.id]);
  useEffect(
    () => () => {
      analysisController.current?.abort();
      interpretationController.current?.abort();
    },
    [],
  );

  const changeScene = (id: string) => {
    analysisController.current?.abort();
    setAnalysisLoading(false);
    setAnalysisError(null);
    setSceneId(id);
    setConfig((previous) => (previous ? { ...previous, scene_id: id } : previous));
    setAnalysis(null);
    setSelectedId(null);
    setPlaying(false);
    setTime(0);
  };
  const changeMode = (next: MissionMode) => {
    if (next === 'propagation') {
      analysisController.current?.abort();
      setAnalysisLoading(false);
    }
    setMode(next);
    setPlaying(false);
    setTime(next === 'prevention' ? cutoff : (run?.result?.frames[0]?.time_s ?? 0));
  };
  const analyze = async () => {
    if (!config || !catalog || configIssue || analysisLoading) return;
    const controller = new AbortController();
    analysisController.current?.abort();
    analysisController.current = controller;
    setAnalysisLoading(true);
    setAnalysisError(null);
    try {
      const next = await api.preventionAnalyze({ ...config, scene_id: sceneId }, controller.signal);
      if (controller.signal.aborted) return;
      setAnalysis(next);
      if (modeRef.current === 'prevention') setTime(next.observation_cutoff_s);
      setPlaying(false);
    } catch (error) {
      if (!controller.signal.aborted) setAnalysisError(messageOf(error));
    } finally {
      if (!controller.signal.aborted) setAnalysisLoading(false);
    }
  };
  const interpret = async () => {
    if (!activeAnalysis || !selected || interpreting) return;
    const controller = new AbortController();
    interpretationController.current = controller;
    setInterpreting(true);
    setInterpretError(null);
    try {
      const next = await api.preventionInterpret(activeAnalysis.id, selected.id, '', controller.signal);
      if (!controller.signal.aborted) setInterpretation(next);
    } catch (error) {
      if (!controller.signal.aborted) setInterpretError(messageOf(error));
    } finally {
      if (!controller.signal.aborted) setInterpreting(false);
    }
  };
  const details = () =>
    onOpenPrevention(
      config
        ? {
            config,
            result: activeAnalysis,
            selectedId: selected?.id ?? null,
            mode: 'design',
            cutaway,
            baseline: session?.baseline ?? null,
          }
        : undefined,
    );
  const activeScale =
    mode === 'prevention'
      ? { min: 20, max: 300, unit: '°C' }
      : layer === 'smoke'
        ? scales.smoke
        : layer === 'airflow'
          ? scales.airflow
          : scales.temperature;
  const scaleMultiplier = mode === 'propagation' && layer === 'smoke' ? 1_000_000 : 1;
  const unit = mode === 'propagation' && layer === 'smoke' ? 'mg/m³' : activeScale.unit;
  const selectedLayer = layers.find((item) => item.id === layer);
  const sourceText =
    mode === 'prevention'
      ? 'Prévision sur composants'
      : isFds
        ? 'Relecture FDS'
        : run
          ? 'Relecture du modèle ML'
          : 'Simulation enregistrée';

  return (
    <div className={`mission ${railOpen ? '' : 'mission-rail-closed'}`} ref={root}>
      <div className="mission-toolbar">
        <div className="mission-location">
          <span className="mission-eyebrow">ENVIRONNEMENT</span>
          <select
            aria-label="Environnement de mission"
            value={sceneId}
            onChange={(event) => changeScene(event.target.value)}
          >
            {scenes.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="mission-mode" aria-label="Type d’analyse">
          <button
            className={mode === 'prevention' ? 'active' : ''}
            aria-pressed={mode === 'prevention'}
            onClick={() => changeMode('prevention')}
          >
            <ShieldCheck size={15} /> Avant allumage
          </button>
          <button
            className={mode === 'propagation' ? 'active' : ''}
            aria-pressed={mode === 'propagation'}
            onClick={() => changeMode('propagation')}
          >
            <Waves size={15} /> Fumée & chaleur
          </button>
        </div>
        <button
          className="mission-icon"
          aria-label={railOpen ? 'Masquer le panneau' : 'Afficher le panneau'}
          title={railOpen ? 'Masquer le panneau' : 'Afficher le panneau'}
          onClick={() => setRailOpen(!railOpen)}
        >
          {railOpen ? <PanelRightClose size={19} /> : <PanelRightOpen size={19} />}
        </button>
      </div>

      <div className="mission-body">
        <section className="mission-stage" aria-label="Vue immersive de la cabine">
          <Suspense fallback={<div className="mission-render-status">Chargement de la vue 3D…</div>}>
            <MissionViewport
              scene={scene}
              frames={frames}
              time={time}
              cameraMode={camera}
              layer={mode === 'prevention' ? 'scene' : layer}
              opacity={opacity}
              cutaway={cutaway}
              markers={markers}
              selectedComponentId={selected?.id}
              onSelectComponent={setSelectedId}
              resetToken={resetToken}
            />
          </Suspense>

          <div className="mission-stage-top">
            <div className="mission-view-title">
              <span className="mission-eyebrow">
                {camera === 'pov' ? 'À BORD' : camera === 'top' ? 'VUE DE DESSUS' : 'VUE D’ENSEMBLE'}{' '}
                <span className="mission-dot" /> {sceneId.toUpperCase()}
              </span>
              <h1>{mode === 'prevention' ? 'Échauffement des composants' : 'Propagation dans la cabine'}</h1>
              <span className="mission-provenance">
                <i />
                {sourceText}
                {run && mode === 'propagation' ? ` · ${run.id.slice(0, 8)}` : ''}
              </span>
            </div>
            <div className="mission-camera" aria-label="Caméra">
              {(
                [
                  ['pov', 'POV équipage', Eye],
                  ['orbit', 'Vue orbitale', Box],
                  ['top', 'Vue de dessus', Focus],
                ] as const
              ).map(([id, label, Icon]) => (
                <button
                  key={id}
                  className={camera === id ? 'active' : ''}
                  aria-label={label}
                  aria-pressed={camera === id}
                  title={label}
                  onClick={() => setCamera(id)}
                >
                  <Icon size={17} />
                  <span>{id === 'pov' ? 'POV' : id === 'orbit' ? 'Orbite' : 'Dessus'}</span>
                </button>
              ))}
              <button
                aria-label="Recentrer la vue mission"
                title="Recentrer"
                onClick={() => setResetToken((value) => value + 1)}
              >
                <RotateCcw size={15} />
              </button>
              <button
                aria-label="Mission en plein écran"
                title="Plein écran"
                onClick={() => {
                  void root.current?.requestFullscreen?.().catch(() => {});
                }}
              >
                <Maximize2 size={16} />
              </button>
            </div>
          </div>

          {mode === 'propagation' && (
            <div className="mission-layers" aria-label="Champs visualisés">
              {layers.map(({ id, name, icon: Icon }) => (
                <button
                  key={id}
                  className={layer === id ? 'active' : ''}
                  title={name}
                  aria-label={name}
                  aria-pressed={layer === id}
                  onClick={() => setLayer(id)}
                >
                  <Icon size={19} />
                  <span>{name}</span>
                </button>
              ))}
            </div>
          )}

          {mode === 'prevention' && (
            <div className="mission-component-map" aria-label="Composants dans la cabine">
              {components.map((item, index) => {
                const temperature = componentTemperature(
                  activeAnalysis?.components.find((row) => row.component_id === item.id),
                  time,
                  cutoff,
                );
                return (
                  <button
                    key={item.id}
                    data-mission-component={item.id}
                    className={selected?.id === item.id ? 'active' : ''}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <span style={{ color: componentTemperatureColor(temperature?.value) }}>
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span>
                      {item.name}
                      <small>
                        {temperature ? `${format(temperature.value, 1)} °C` : 'Non estimé à cet instant'}
                      </small>
                    </span>
                    <ChevronRight size={13} />
                  </button>
                );
              })}
            </div>
          )}

          {(runLoading || runsLoading) && mode === 'propagation' && (
            <div className="mission-loading" role="status">
              <LoaderCircle size={18} className="spin" />
              Chargement d’une simulation enregistrée…
            </div>
          )}
          {runError && mode === 'propagation' && (
            <div className="mission-loading mission-error" role="alert">
              {runError}
              <button onClick={() => onOpenLab(sceneId, run)}>Ouvrir le laboratoire</button>
            </div>
          )}
          {!runLoading && !runsLoading && !run && !runError && mode === 'propagation' && (
            <div className="mission-loading">
              Aucune relecture disponible pour cette scène.
              <button onClick={() => onOpenLab(sceneId, run)}>
                Créer une simulation <ArrowUpRight size={14} />
              </button>
            </div>
          )}

          <div className="mission-stage-bottom">
            <div className="mission-legend-row">
              <span className="mission-coordinate">
                <Crosshair size={13} />
                {mode === 'prevention'
                  ? 'Emplacements de composants hypothétiques'
                  : 'Champ spatial interpolé entre instants enregistrés'}
              </span>
              {(mode === 'prevention' || (frames.length > 0 && layer !== 'scene')) && (
                <div
                  className={`mission-scale ${layer === 'smoke' && mode === 'propagation' ? 'smoke' : layer === 'airflow' ? 'airflow' : ''}`}
                  aria-label="Échelle fixe de la visualisation"
                >
                  <span>
                    {mode === 'prevention'
                      ? 'Isolant · couleur des repères'
                      : layer === 'thermal-smoke'
                        ? 'Couleur : température du gaz'
                        : selectedLayer?.name}
                  </span>
                  <div
                    style={
                      (layer !== 'smoke' && layer !== 'airflow') || mode === 'prevention'
                        ? { background: MISSION_TEMPERATURE_GRADIENT }
                        : undefined
                    }
                  />
                  <div className="mission-scale-values">
                    <span>
                      {mode === 'prevention' ? '≤ ' : ''}
                      {format(activeScale.min * scaleMultiplier, 0)}
                    </span>
                    <span>
                      {mode === 'prevention' ? '≥ ' : ''}
                      {format(
                        activeScale.max * scaleMultiplier,
                        mode === 'propagation' && layer === 'airflow' ? 2 : 0,
                      )}{' '}
                      {unit}
                    </span>
                  </div>
                </div>
              )}
            </div>
            <div className="mission-timeline">
              <div className="mission-play-controls">
                <button
                  aria-label="Revenir au début"
                  disabled={maxTime <= 0}
                  onClick={() => {
                    setTime(firstTime);
                    setPlaying(false);
                  }}
                >
                  <SkipBack size={17} />
                </button>
                <button
                  className="mission-play"
                  aria-label={playing ? 'Mettre la lecture en pause' : 'Lire la scène'}
                  disabled={maxTime <= firstTime}
                  onClick={() => {
                    if (time >= maxTime) setTime(firstTime);
                    setPlaying(!playing);
                  }}
                >
                  {playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" />}
                </button>
                <span className="mission-time" aria-label="Instant affiché">
                  {format(time, 1)}
                  <small> / {format(maxTime, 1)} s</small>
                </span>
              </div>
              <div className="mission-scrubber">
                <div className="mission-time-labels">
                  <span>
                    {mode === 'prevention' ? 'HISTORIQUE → PRÉVISION ML' : 'RELECTURE DE PROPAGATION'}
                  </span>
                  <span>
                    {mode === 'prevention'
                      ? 'Aucune fumée déduite de la température'
                      : `${sourceLabel} dans ce calcul`}
                  </span>
                </div>
                <input
                  type="range"
                  aria-label="Temps de la scène"
                  min={firstTime}
                  max={Math.max(maxTime, firstTime + 0.001)}
                  step="0.01"
                  value={time}
                  disabled={maxTime <= firstTime}
                  onChange={(event) => {
                    setTime(Number(event.target.value));
                    setPlaying(false);
                  }}
                />
                <div className="mission-ruler">
                  {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
                    <span key={fraction}>{format(firstTime + fraction * (maxTime - firstTime), 0)}s</span>
                  ))}
                </div>
              </div>
              <select
                aria-label="Vitesse de lecture"
                value={speed}
                onChange={(event) => setSpeed(Number(event.target.value))}
              >
                {[0.5, 1, 2, 4].map((value) => (
                  <option key={value} value={value}>
                    ×{value}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {railOpen && (
          <aside className="mission-inspector" aria-label="Inspection de la mission">
            <div className="mission-inspector-heading">
              <span className="mission-eyebrow">
                {mode === 'prevention' ? 'PRÉVENTION' : 'CHAMP DE PROPAGATION'}
              </span>
              <span className="mission-inspector-badge">
                {mode === 'prevention' ? 'ML' : isFds ? 'FDS' : 'ML'}
              </span>
            </div>
            {mode === 'propagation' ? (
              <>
                <h2>{selectedLayer?.name}</h2>
                <p className="mission-description">
                  {layer === 'thermal-smoke'
                    ? 'La densité de fumée règle l’opacité. Sa couleur révèle la température du gaz au même endroit.'
                    : layer === 'smoke'
                      ? 'La fumée occupe le volume calculé. Son déplacement dépend des résultats de ventilation et de gravité.'
                      : layer === 'airflow'
                        ? 'Direction et intensité des vitesses calculées dans la cabine.'
                        : layer === 'temperature'
                          ? 'Distribution de la température du gaz dans le volume échantillonné.'
                          : 'Explorez la géométrie et les équipements de la cabine.'}
                </p>
                <label className="mission-range-label">
                  Intensité visuelle <span>{Math.round(opacity * 100)} %</span>
                  <input
                    aria-label="Intensité visuelle"
                    type="range"
                    min="0.1"
                    max="1"
                    step="0.05"
                    value={opacity}
                    onChange={(event) => setOpacity(Number(event.target.value))}
                  />
                </label>
                <p className="mission-microcopy">Réglage de rendu, sans modifier les valeurs physiques.</p>
                <div className="mission-readout">
                  <span>Maximum global du gaz</span>
                  <strong>
                    {format(metric?.temperature_max_c, 1)}
                    <small> °C</small>
                  </strong>
                  <span>Échantillon à {format(metric?.time_s, 2)} s</span>
                </div>
                <MiniTrace
                  points={(run?.result?.metrics ?? []).map((row) => ({
                    time_s: row.time_s,
                    value: row.temperature_max_c,
                  }))}
                  time={time}
                  duration={maxTime || 1}
                  label="Maximum global · distinct du champ affiché"
                />
                <dl className="mission-facts">
                  <div>
                    <dt>Gravité</dt>
                    <dd>{format(run?.config?.gravity_g, run?.config?.gravity_g === 1 ? 0 : 4)} g</dd>
                  </div>
                  <div>
                    <dt>Ventilation imposée</dt>
                    <dd>{format(run?.config?.airflow_m_s, 2)} m/s</dd>
                  </div>
                  <div>
                    <dt>
                      {isResistive
                        ? 'Chauffage électrique I²R'
                        : isCoupled
                          ? 'Allumeur thermique'
                          : 'Source thermique'}
                    </dt>
                    <dd>{format(sourcePower, 0)} W</dd>
                  </div>
                  <div>
                    <dt>Fumée moyenne</dt>
                    <dd>
                      {format(
                        finite(metric?.smoke_mean_kg_m3) ? metric.smoke_mean_kg_m3 * 1_000_000 : undefined,
                        2,
                      )}{' '}
                      mg/m³
                    </dd>
                  </div>
                </dl>
                <label className="mission-field-label">
                  Simulation enregistrée
                  <select
                    aria-label="Simulation enregistrée"
                    value={runId}
                    disabled={runLoading}
                    onChange={(event) => setRunId(event.target.value)}
                  >
                    {replays.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.config?.mode === 'physics' ? 'FDS' : 'ML'} · {item.config?.duration_s}s ·{' '}
                        {item.config?.gravity_g === 1 ? '1 g' : 'µg'} · {item.id.slice(0, 6)}
                      </option>
                    ))}
                  </select>
                </label>
                {run && (
                  <a className="mission-text-link" href={api.exportUrl(run.id)}>
                    <ArrowDownToLine size={14} />
                    Exporter les champs
                  </a>
                )}
                <button className="mission-secondary" onClick={() => onOpenLab(sceneId, run)}>
                  Modifier le scénario <ArrowUpRight size={14} />
                </button>
                <details className="mission-disclosure">
                  <summary>Origine et portée des champs</summary>
                  <p>
                    {String(run?.result?.provenance.engine ?? 'Aucun résultat chargé')}
                    {run?.result?.provenance.engine_version
                      ? ` · ${run.result.provenance.engine_version}`
                      : ''}
                    .{' '}
                    {isFds
                      ? `Calcul exploratoire : ${sourceLabel.toLowerCase()} ; la convergence du maillage reste à établir.`
                      : 'Champ prédit par un modèle de transport, entraîné sur des simulations.'}{' '}
                    La carte représente des grandeurs physiques, pas une probabilité de départ de feu.
                    L’aspect lissé ne crée pas de résolution physique supplémentaire.
                  </p>
                </details>
              </>
            ) : (
              <>
                <h2>{selected?.name ?? 'Composants électriques'}</h2>
                <p className="mission-description">
                  Localisez l’échauffement estimé avant un éventuel départ de feu. Les repères gris indiquent
                  une prévision indisponible.
                </p>
                {config && catalog && (
                  <div className="mission-prevention-controls">
                    <label className="mission-field-label">
                      Courant de référence <span>A</span>
                      <input
                        aria-label="Courant de référence"
                        type="number"
                        min={catalog.parameters.current_a.min}
                        max={catalog.parameters.current_a.max}
                        step={catalog.parameters.current_a.step}
                        value={finite(config.current_a) ? config.current_a : ''}
                        disabled={analysisLoading}
                        onChange={(event) => setConfig({ ...config, current_a: event.target.valueAsNumber })}
                      />
                    </label>
                    <label className="mission-field-label">
                      Ventilation locale <span>m/s</span>
                      <input
                        aria-label="Ventilation locale"
                        type="number"
                        min={catalog.parameters.airflow_m_s.min}
                        max={catalog.parameters.airflow_m_s.max}
                        step={catalog.parameters.airflow_m_s.step}
                        value={finite(config.airflow_m_s) ? config.airflow_m_s : ''}
                        disabled={analysisLoading}
                        onChange={(event) =>
                          setConfig({ ...config, airflow_m_s: event.target.valueAsNumber })
                        }
                      />
                    </label>
                    <button
                      className="mission-primary"
                      onClick={() => {
                        void analyze();
                      }}
                      disabled={!connected || analysisLoading || !!configIssue}
                    >
                      {analysisLoading ? <LoaderCircle size={16} className="spin" /> : <Zap size={16} />}
                      {analysisLoading ? 'Calcul des prévisions…' : 'Calculer la prévision'}
                    </button>
                    {(analysisError || configIssue) && (
                      <p className="mission-error" role="alert">
                        {analysisError ?? configIssue}
                      </p>
                    )}
                    {analysis && !activeAnalysis && (
                      <p className="mission-microcopy">Paramètres modifiés : recalculez la prévision.</p>
                    )}
                  </div>
                )}
                {!catalog && (
                  <p className="mission-microcopy" role="status">
                    {analysisError ?? 'Chargement des composants…'}
                  </p>
                )}
                <div className="mission-readout">
                  <span>
                    {componentValue?.kind === 'history'
                      ? 'Historique thermique simulé'
                      : 'Température d’isolant · ML'}
                  </span>
                  <strong>
                    {format(componentValue?.value, 1)}
                    <small> °C</small>
                  </strong>
                  <span>
                    {componentValue
                      ? `À ${format(time, 2)} s`
                      : 'Aucune température disponible à cet instant'}
                  </span>
                </div>
                <dl className="mission-facts">
                  <div>
                    <dt>Délai d’allumage estimé</dt>
                    <dd>
                      {assessment?.status === 'available' && assessment.estimate
                        ? `${format(assessment.estimate.ignition_delay_s, 2)} s`
                        : 'Non estimé'}
                    </dd>
                  </div>
                  <div>
                    <dt>Incertitude du délai</dt>
                    <dd>Non quantifiée</dd>
                  </div>
                  <div>
                    <dt>Probabilité réelle de feu</dt>
                    <dd>Non quantifiée</dd>
                  </div>
                  <div>
                    <dt>Horizon de prévision</dt>
                    <dd>{format(activeAnalysis?.horizon_s ?? config?.horizon_s, 1)} s</dd>
                  </div>
                </dl>
                <p className="mission-microcopy">
                  {assessment
                    ? preventionStatusLabels[assessment.status]
                    : 'Choisissez un composant puis calculez le scénario.'}{' '}
                  {assessment?.estimate
                    ? 'Délai depuis la mise sous courant, limité au protocole du fil NiCr/LDPE étudié.'
                    : ''}
                </p>
                {assessment?.reasons[0] && <p className="mission-microcopy">{assessment.reasons[0]}</p>}
                <button className="mission-secondary" onClick={details}>
                  Paramètres & courbes détaillées <ArrowUpRight size={14} />
                </button>
                {activeAnalysis && (
                  <>
                    <div className="mission-evidence">
                      <h3>Conclusions & conditions</h3>
                      {ignitionEvidence && (
                        <a href={ignitionEvidence.source.url} target="_blank" rel="noreferrer">
                          <span>SOURCE DU DÉLAI · HORS NASA</span>
                          {ignitionEvidence.title}
                          <ArrowUpRight size={12} />
                        </a>
                      )}
                      {evidence
                        .filter((item) => item.is_nasa_source !== false)
                        .slice(0, 3)
                        .map((item) => (
                          <a key={item.id} href={item.source.url} target="_blank" rel="noreferrer">
                            <span>{item.is_nasa_source === false ? 'ÉTUDE COMPLÉMENTAIRE' : 'NASA'}</span>
                            {item.title}
                            <ArrowUpRight size={12} />
                            <small>
                              {item.relevance}
                              {item.reasons[0] ? ` · ${item.reasons[0]}` : ''}
                            </small>
                          </a>
                        ))}
                    </div>
                    <button
                      className="mission-secondary"
                      onClick={() => {
                        void interpret();
                      }}
                      disabled={interpreting}
                    >
                      {interpreting ? <LoaderCircle size={14} className="spin" /> : <ShieldCheck size={14} />}
                      Interpréter avec Codex
                    </button>
                    {interpretError && (
                      <p role="alert" className="mission-error">
                        {interpretError}
                      </p>
                    )}
                    {interpretation && (
                      <p className="mission-interpretation">
                        {interpretation.summary}
                        <small>
                          {interpretation.method.startsWith('codex')
                            ? 'Interprétation Codex sourcée'
                            : 'Synthèse extractive des preuves'}
                        </small>
                      </p>
                    )}
                    <a className="mission-text-link" href={api.preventionExportUrl(activeAnalysis.id)}>
                      <ArrowDownToLine size={14} />
                      Exporter l’analyse
                    </a>
                  </>
                )}
                <details className="mission-disclosure">
                  <summary>Ce que la vue permet d’estimer</summary>
                  <p>
                    Les températures proviennent d’historiques simulés et d’un modèle appris sur ces
                    simulations. Le délai utilise une étude expérimentale complémentaire. Les positions 3D
                    sont hypothétiques ; le couplage avec la ventilation de la cabine reste à réaliser. Aucun
                    capteur réel n’est connecté.
                  </p>
                </details>
              </>
            )}
            <label className="mission-cutaway">
              <input
                type="checkbox"
                checked={cutaway}
                onChange={(event) => setCutaway(event.target.checked)}
              />
              Ouvrir la coque en vue extérieure
            </label>
          </aside>
        )}
      </div>
      <footer className="mission-statusline">
        <span>
          <span className={`mission-dot ${connected ? 'connected' : ''}`} />
          {connected ? 'PC Windows connecté' : 'Poste déconnecté'}
        </span>
        <span>
          {mode === 'prevention'
            ? 'Composants hypothétiques · risque non calibré'
            : `Résultats enregistrés · ${sourceLabel.toLowerCase()} · échelle fixe`}
        </span>
        <button onClick={() => onOpenPrevention()}>
          Prévention & preuves NASA <ArrowUpRight size={12} />
        </button>
      </footer>
    </div>
  );
}
