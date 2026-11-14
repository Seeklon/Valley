import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  Box,
  ChevronDown,
  Cpu,
  Eye,
  Flame,
  Focus,
  Layers,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SlidersHorizontal,
  Square,
  Thermometer,
  Waves,
  Wind,
  Zap,
} from 'lucide-react';
import { api, ApiError, messageOf } from '../api';
import { fieldAvailable, finite, format } from '../data';
import { missionScales, MISSION_TEMPERATURE_GRADIENT } from '../mission-rendering';
import type { MissionCamera, MissionLayer } from '../mission-rendering';
import {
  CONSEQUENCE_GRADIENT,
  consequenceColor,
  consequenceMetrics,
  consequencesOf,
  consequenceValue,
  incidentSourcePosition,
  predictionMatches,
  propagationConfigIssue,
  propagationKey,
  simulationConfig,
  simulationMatches,
} from '../propagation';
import type { ConsequenceMetric, IncidentsCatalog, PropagationSession } from '../propagation';
import type { Frame, Health, Result, RunConfig, Scene } from '../types';
import IncidentCampaignPanel from './IncidentCampaignPanel';
import '../mission.css';
import '../propagation.css';

const MissionViewport = lazy(() => import('./MissionViewport'));
const EMPTY_FRAMES: Frame[] = [];
const layers: { id: MissionLayer; name: string; icon: typeof Box }[] = [
  { id: 'thermal-smoke', name: 'Fumée thermique', icon: Layers },
  { id: 'temperature', name: 'Température', icon: Thermometer },
  { id: 'smoke', name: 'Fumée', icon: Waves },
  { id: 'airflow', name: 'Ventilation', icon: Wind },
  { id: 'scene', name: 'Cabine seule', icon: Box },
];
const controls: {
  key: keyof RunConfig;
  name: string;
  unit: string;
  min: number;
  max: number;
  step: number;
}[] = [
  { key: 'gravity_g', name: 'Gravité', unit: 'g', min: 0, max: 1, step: 0.0001 },
  { key: 'airflow_m_s', name: 'Ventilation', unit: 'm/s', min: 0, max: 1, step: 0.01 },
  { key: 'oxygen_percent', name: 'Oxygène', unit: '% vol', min: 15, max: 30, step: 0.1 },
  { key: 'ignition_power_w', name: 'Puissance du départ', unit: 'W', min: 0, max: 10000, step: 10 },
  { key: 'ignition_duration_s', name: 'Durée du départ', unit: 's', min: 0.1, max: 120, step: 0.1 },
  { key: 'duration_s', name: 'Durée étudiée', unit: 's', min: 2, max: 180, step: 1 },
];

function Consequences({ result }: { result: Result | null }) {
  const values = consequencesOf(result);
  const tiles = [
    ['Pic de température', values?.heat_peak_c, '°C', 1],
    ['Pic de fumée', values?.smoke_peak_mg_m3, 'mg/m³', 1],
    ['Équipements exposés', values?.exposed_equipment_count, '', 0],
    ['Dont critiques', values?.critical_exposed_count, '', 0],
  ] as const;
  return (
    <>
      <div className="propagation-metrics">
        {tiles.map(([label, value, unit, decimals]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>
              {format(value, decimals)}
              <small>{unit}</small>
            </strong>
          </div>
        ))}
      </div>
      <dl className="propagation-facts">
        <div>
          <dt>Volume chaud maximal</dt>
          <dd>{format(values?.hot_volume_peak_m3, 2)} m³</dd>
        </div>
        <div>
          <dt>Volume enfumé maximal</dt>
          <dd>{format(values?.smoky_volume_peak_m3, 2)} m³</dd>
        </div>
        <div>
          <dt>Passages exposés</dt>
          <dd>{format(values?.passages_exposed_count, 0)}</dd>
        </div>
        <div>
          <dt>Première exposition</dt>
          <dd>
            {values?.first_exposure_s === null &&
            (finite(values.heat_peak_c) || finite(values.smoke_peak_mg_m3))
              ? 'Non observée dans la durée'
              : finite(values?.first_exposure_s)
                ? `${format(values.first_exposure_s, 2)} s`
                : 'Non renseignée'}
          </dd>
        </div>
      </dl>
      {values && (
        <p className="propagation-note">
          Exposition évaluée à {format(values.thresholds?.temperature_c, 0)} °C et{' '}
          {format(values.thresholds?.smoke_mg_m3, 0)} mg/m³. Un équipement exposé n’est pas nécessairement
          allumé. Les valeurs absentes restent inconnues. {values.basis}
        </p>
      )}
    </>
  );
}

export default function PropagationView({
  page,
  scenes,
  health,
  connected,
  session,
  onSessionChange,
  onOpenSimulation,
}: {
  page: 'prediction' | 'simulation';
  scenes: Scene[];
  health: Health | null;
  connected: boolean;
  session: PropagationSession;
  onSessionChange: Dispatch<SetStateAction<PropagationSession>>;
  onOpenSimulation: () => void;
}) {
  const { config, assessment, simulation } = session;
  const [catalog, setCatalog] = useState<IncidentsCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [predicting, setPredicting] = useState(false);
  const [predictionError, setPredictionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [criterion, setCriterion] = useState<ConsequenceMetric>('heat_peak_c');
  const [camera, setCamera] = useState<MissionCamera>('orbit');
  const [cutaway, setCutaway] = useState(true);
  const [resetToken, setResetToken] = useState(0);
  const [layer, setLayer] = useState<MissionLayer>('thermal-smoke');
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [opacity, setOpacity] = useState(0.72);
  const configRef = useRef(config);
  configRef.current = config;
  const predictionController = useRef<AbortController | null>(null);
  const launchController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const scene = scenes.find((entry) => entry.id === config?.scene_id);
  const components = useMemo(
    () => catalog?.components.filter((entry) => entry.scene_id === config?.scene_id) ?? [],
    [catalog, config?.scene_id],
  );
  const component = components.find((entry) => entry.id === config?.component_id) ?? components[0];
  const incident = catalog?.incidents.find((entry) => entry.id === config?.incident_type);
  const activeAssessment = predictionMatches(assessment, config) ? assessment : null;
  const prediction = activeAssessment?.components.find((entry) => entry.component_id === component?.id);
  const matchingSimulation = simulationMatches(simulation, config);
  const displayedResult =
    page === 'prediction'
      ? (prediction?.result ?? null)
      : matchingSimulation && simulation?.status === 'completed'
        ? (simulation.result ?? null)
        : null;
  const frames = displayedResult?.frames ?? EMPTY_FRAMES;
  const scales = useMemo(() => missionScales(frames), [frames]);
  const hasFields = useMemo(
    () => ({
      scene: true,
      temperature: frames.some((frame) => fieldAvailable(frame, 'temperature')),
      smoke: frames.some((frame) => fieldAvailable(frame, 'smoke')),
      airflow: frames.some((frame) => fieldAvailable(frame, 'airflow')),
      'thermal-smoke': frames.some(
        (frame) => fieldAvailable(frame, 'smoke') && fieldAvailable(frame, 'temperature'),
      ),
    }),
    [frames],
  );
  const shownLayer = hasFields[layer] ? layer : 'scene';
  const firstTime = frames[0]?.time_s ?? 0;
  const lastTime = frames.at(-1)?.time_s ?? 0;
  const busy = submitting || simulation?.status === 'queued' || simulation?.status === 'running';
  const issue = config && catalog ? propagationConfigIssue(config, catalog) : null;
  const mapScale = consequenceMetrics.find((entry) => entry.id === criterion)!;
  const fieldScale =
    shownLayer === 'airflow' ? scales.airflow : shownLayer === 'smoke' ? scales.smoke : scales.temperature;
  const fieldUnit = shownLayer === 'smoke' ? 'mg/m³' : fieldScale.unit;
  const fieldMultiplier = shownLayer === 'smoke' ? 1_000_000 : 1;
  const markers = useMemo(
    () =>
      components.map((entry) => {
        const result =
          page === 'prediction'
            ? activeAssessment?.components.find((item) => item.component_id === entry.id)?.result
            : entry.id === component?.id
              ? displayedResult
              : null;
        return {
          id: entry.id,
          name: entry.name,
          position_m: incidentSourcePosition(result) ?? entry.position_m,
          object_id: entry.object_id ?? undefined,
          color:
            page === 'prediction'
              ? consequenceColor(consequenceValue(result, criterion), criterion)
              : entry.id === component?.id
                ? '#dcea93'
                : '#7e8d9a',
        };
      }),
    [components, page, activeAssessment, criterion, component?.id, displayedResult],
  );

  useEffect(() => {
    const controller = new AbortController();
    setCatalogError(null);
    void api
      .incidentsCatalog(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setCatalog(value);
        onSessionChange((previous) => {
          if (previous.config) return previous;
          const initialScene = value.components.some((entry) => entry.scene_id === 'soyuz')
            ? 'soyuz'
            : value.defaults.scene_id;
          return {
            ...previous,
            config: {
              ...value.defaults,
              scene_id: initialScene,
              component_id: value.components.find((entry) => entry.scene_id === initialScene)?.id,
              incident_type: value.defaults.incident_type ?? value.incidents[0]?.id,
            },
          };
        });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setCatalogError(messageOf(error));
      });
    return () => controller.abort();
  }, [retry, connected, onSessionChange]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      predictionController.current?.abort();
      launchController.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!simulation || !['queued', 'running'].includes(simulation.status)) return;
    const id = simulation.id;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.run(id, controller.signal);
        if (controller.signal.aborted) return;
        setPollError(null);
        onSessionChange((previous) =>
          previous.simulation?.id === id
            ? { ...previous, simulation: { ...next, config: next.config ?? previous.simulation.config } }
            : previous,
        );
        if (['queued', 'running'].includes(next.status))
          timer = setTimeout(() => {
            void poll();
          }, 1500);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          onSessionChange((previous) =>
            previous.simulation?.id === id
              ? {
                  ...previous,
                  simulation: {
                    ...previous.simulation,
                    status: 'failed',
                    message: 'Ce calcul n’est plus disponible sur le poste.',
                  },
                }
              : previous,
          );
        } else {
          setPollError(messageOf(error));
          timer = setTimeout(() => {
            void poll();
          }, 4000);
        }
      }
    };
    timer = setTimeout(() => {
      void poll();
    }, 300);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [simulation?.id, simulation?.status, onSessionChange]);

  useEffect(() => {
    setTime(firstTime);
    setPlaying(frames.length > 1 && !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    if (displayedResult)
      setLayer(
        hasFields['thermal-smoke']
          ? 'thermal-smoke'
          : hasFields.temperature
            ? 'temperature'
            : hasFields.smoke
              ? 'smoke'
              : 'scene',
      );
  }, [displayedResult, firstTime, frames.length, hasFields]);
  useEffect(() => {
    if (!playing || lastTime <= firstTime) return;
    let animation = 0;
    let previous = performance.now();
    let elapsed = 0;
    const tick = (now: number) => {
      elapsed += document.hidden ? 0 : (now - previous) / 1000;
      previous = now;
      if (elapsed >= 1 / 24) {
        const step = elapsed * speed;
        elapsed = 0;
        setTime((current) => Math.min(lastTime, current + step));
      }
      animation = requestAnimationFrame(tick);
    };
    animation = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animation);
  }, [playing, speed, firstTime, lastTime]);
  useEffect(() => {
    if (time >= lastTime) setPlaying(false);
  }, [time, lastTime]);

  const updateConfig = (patch: Partial<RunConfig>) => {
    if (!configRef.current) return;
    const next = { ...configRef.current, ...patch };
    if (propagationKey(next) !== propagationKey(configRef.current)) {
      predictionController.current?.abort();
      setPredicting(false);
      setPredictionError(null);
    }
    configRef.current = next;
    setPlaying(false);
    onSessionChange((previous) => ({ ...previous, config: next }));
  };
  const selectComponent = (id: string | null) => {
    if (id && components.some((entry) => entry.id === id)) updateConfig({ component_id: id });
  };
  const predict = async () => {
    if (!config || !catalog?.model?.available || predicting || issue) return;
    const controller = new AbortController();
    predictionController.current?.abort();
    predictionController.current = controller;
    const snapshot = { ...config, mode: 'prediction' as const, model_id: catalog.model.id };
    const key = propagationKey(snapshot);
    setPredicting(true);
    setPredictionError(null);
    try {
      const next = await api.predictIncidents(snapshot, controller.signal);
      if (controller.signal.aborted || !configRef.current || propagationKey(configRef.current) !== key)
        return;
      if (propagationKey(next.config) !== key)
        throw new Error('La réponse ne correspond pas aux conditions demandées. Relancez la carte.');
      onSessionChange((previous) =>
        previous.config && propagationKey(previous.config) === key
          ? { ...previous, assessment: next }
          : previous,
      );
    } catch (error) {
      if (!controller.signal.aborted) setPredictionError(messageOf(error));
    } finally {
      if (predictionController.current === controller && mounted.current) setPredicting(false);
    }
  };
  const launch = async () => {
    if (!config || !component || issue || busy) return;
    const snapshot = simulationConfig(config, component.id);
    const controller = new AbortController();
    launchController.current = controller;
    setSubmitting(true);
    setSimulationError(null);
    setPollError(null);
    setPlaying(false);
    try {
      const run = await api.launch(snapshot, controller.signal);
      if (!controller.signal.aborted)
        onSessionChange((previous) => ({
          ...previous,
          simulation: { ...run, config: run.config ?? snapshot },
        }));
    } catch (error) {
      if (!controller.signal.aborted) setSimulationError(messageOf(error));
    } finally {
      if (mounted.current) setSubmitting(false);
    }
  };
  const cancel = async () => {
    if (!simulation || cancelling) return;
    const id = simulation.id;
    setCancelling(true);
    try {
      const next = await api.cancel(id);
      if (mounted.current)
        onSessionChange((previous) =>
          previous.simulation?.id === id
            ? { ...previous, simulation: { ...previous.simulation, ...next } }
            : previous,
        );
    } catch (error) {
      if (mounted.current) setSimulationError(messageOf(error));
    } finally {
      if (mounted.current) setCancelling(false);
    }
  };
  const transfer = () => {
    if (!config || !component) return;
    updateConfig(simulationConfig(config, component.id));
    onOpenSimulation();
  };
  const exportPrediction = () => {
    if (!activeAssessment) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(activeAssessment, null, 2)], { type: 'application/json' }),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = `ignis-propagation-${activeAssessment.config.scene_id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const incidentProvenance = displayedResult?.provenance.incident;
  const appliedPosition = incidentSourcePosition(displayedResult);

  return (
    <div className="mission propagation" data-propagation-page={page}>
      <div className="mission-toolbar propagation-toolbar">
        <div className="mission-location">
          <label className="mission-eyebrow" htmlFor="propagation-scene">
            ENVIRONNEMENT
          </label>
          <select
            id="propagation-scene"
            value={config?.scene_id ?? ''}
            disabled={!catalog || submitting}
            onChange={(event) =>
              updateConfig({
                scene_id: event.target.value,
                component_id: catalog?.components.find((entry) => entry.scene_id === event.target.value)?.id,
              })
            }
          >
            {scenes.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </select>
        </div>
        <p className="propagation-purpose">
          {page === 'prediction'
            ? 'Si le feu démarre ici, quelles conséquences dans la cabine ?'
            : 'Reproduire le départ sélectionné avec le moteur physique.'}
        </p>
        <button
          className="mission-primary propagation-main-action"
          onClick={() => {
            void (page === 'prediction' ? predict() : launch());
          }}
          disabled={
            !connected ||
            !catalog ||
            !component ||
            Boolean(issue) ||
            (page === 'prediction'
              ? predicting || !catalog.model?.available
              : busy || health?.worker_available === false || health?.capabilities?.physics !== true)
          }
        >
          {page === 'prediction' ? (
            predicting ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Cpu size={16} />
            )
          ) : busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <Flame size={16} />
          )}
          {page === 'prediction'
            ? predicting
              ? 'Calcul de la carte…'
              : 'Calculer la carte'
            : busy
              ? 'Calcul physique en cours…'
              : 'Calculer avec FDS'}
        </button>
      </div>
      <IncidentCampaignPanel />
      {catalogError && (
        <div className="propagation-banner" role="alert">
          {catalogError}
          <button onClick={() => setRetry((value) => value + 1)}>Réessayer le catalogue</button>
        </div>
      )}
      {!catalog && !catalogError && (
        <div className="propagation-banner" role="status">
          <LoaderCircle size={14} className="spin" />
          Chargement des départs potentiels…
        </div>
      )}
      <div className="mission-body propagation-body">
        <div className="propagation-stage-column">
          <section className="mission-stage" aria-label="Carte 3D des départs potentiels">
            <Suspense fallback={<div className="mission-render-status">Chargement de la vue 3D…</div>}>
              <MissionViewport
                scene={scene}
                frames={frames}
                time={time}
                cameraMode={camera}
                layer={shownLayer}
                opacity={opacity}
                cutaway={cutaway}
                markers={markers}
                selectedComponentId={component?.id}
                onSelectComponent={selectComponent}
                resetToken={resetToken}
              />
            </Suspense>
            <div className="mission-stage-top">
              <div className="mission-view-title">
                <span className="mission-eyebrow">
                  {page === 'prediction' ? 'PRÉDICTION · CONSÉQUENCES' : 'SIMULATION · POINT DE DÉPART'}
                </span>
                <h1>{component?.name ?? 'Choisissez un départ potentiel'}</h1>
                <span className="mission-provenance">
                  <i />
                  {displayedResult
                    ? page === 'prediction'
                      ? 'Champs prédits par le modèle ML'
                      : `Calcul FDS · ${simulation?.id.slice(0, 8)}`
                    : 'Géométrie · aucun champ affiché'}
                </span>
              </div>
              <div className="mission-camera" aria-label="Caméra">
                {(
                  [
                    ['orbit', 'Vue orbitale', Box],
                    ['pov', 'POV équipage', Eye],
                    ['top', 'Vue de dessus', Focus],
                  ] as const
                ).map(([id, title, Icon]) => (
                  <button
                    key={id}
                    className={camera === id ? 'active' : ''}
                    aria-label={title}
                    aria-pressed={camera === id}
                    title={title}
                    onClick={() => setCamera(id)}
                  >
                    <Icon size={17} />
                    <span>{id === 'pov' ? 'POV' : id === 'orbit' ? 'Orbite' : 'Dessus'}</span>
                  </button>
                ))}
                <button
                  aria-label="Recentrer la vue"
                  title="Recentrer"
                  onClick={() => setResetToken((value) => value + 1)}
                >
                  <RotateCcw size={16} />
                </button>
              </div>
            </div>
            <div className="mission-layers propagation-layers" aria-label="Champs de propagation">
              {layers.map(({ id, name, icon: Icon }) => (
                <button
                  key={id}
                  className={shownLayer === id ? 'active' : ''}
                  aria-label={name}
                  aria-pressed={shownLayer === id}
                  disabled={!hasFields[id]}
                  title={hasFields[id] ? name : `${name} : champ indisponible pour ce résultat`}
                  onClick={() => setLayer(id)}
                >
                  <Icon size={18} />
                  <span>{name}</span>
                </button>
              ))}
            </div>
            <div className="propagation-map-overlays">
              {page === 'prediction' && (
                <div className="propagation-map-scale">
                  <span>COULEUR DES POINTS · {mapScale.name}</span>
                  <div style={{ background: CONSEQUENCE_GRADIENT }} />
                  <div className="propagation-scale-ticks">
                    <span>{format(mapScale.min, 0)}</span>
                    <span>
                      ≥ {format(mapScale.max, 0)} {mapScale.unit}
                    </span>
                  </div>
                  <small>Échelle fixe · gris : non estimé</small>
                </div>
              )}
              {shownLayer !== 'scene' && (
                <div
                  className={`mission-scale ${shownLayer === 'smoke' ? 'smoke' : shownLayer === 'airflow' ? 'airflow' : ''}`}
                >
                  <span>
                    CHAMP ·{' '}
                    {shownLayer === 'airflow'
                      ? 'Vitesse'
                      : shownLayer === 'smoke'
                        ? 'Fumée'
                        : 'Température du gaz'}
                  </span>
                  <div
                    style={
                      shownLayer === 'temperature' || shownLayer === 'thermal-smoke'
                        ? { background: MISSION_TEMPERATURE_GRADIENT }
                        : undefined
                    }
                  />
                  <div className="mission-scale-values">
                    <span>{format(fieldScale.min * fieldMultiplier, 1)}</span>
                    <span>
                      {format(fieldScale.max * fieldMultiplier, 1)} {fieldUnit}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </section>
          <div className="propagation-playback">
            <button
              aria-label="Revenir au début de la propagation"
              disabled={!frames.length}
              onClick={() => {
                setPlaying(false);
                setTime(firstTime);
              }}
            >
              <SkipBack size={17} />
            </button>
            <button
              className="propagation-play"
              aria-label={playing ? 'Mettre la propagation en pause' : 'Lire la propagation'}
              disabled={lastTime <= firstTime}
              onClick={() => {
                if (time >= lastTime) setTime(firstTime);
                setPlaying((value) => !value);
              }}
            >
              {playing ? <Pause size={17} /> : <Play size={17} />}
            </button>
            <span>
              {format(time, 1)}
              <small> / {format(lastTime, 1)} s</small>
            </span>
            <input
              aria-label="Instant de propagation"
              type="range"
              min={firstTime}
              max={lastTime || 1}
              step="0.05"
              value={time}
              disabled={!frames.length}
              onChange={(event) => {
                setPlaying(false);
                setTime(event.target.valueAsNumber);
              }}
            />
            <select
              aria-label="Vitesse de lecture"
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
            >
              <option value={0.5}>×0,5</option>
              <option value={1}>×1</option>
              <option value={2}>×2</option>
              <option value={5}>×5</option>
            </select>
          </div>
          <div className="propagation-caption">
            {page === 'prediction'
              ? 'Les points comparent des départs alternatifs. Le champ représente uniquement le point sélectionné.'
              : 'Le champ anime les observations enregistrées du calcul physique sélectionné.'}{' '}
            {frames.length
              ? `${frames.length} instants enregistrés · lissage visuel entre observations.`
              : 'Aucune propagation calculée pour les paramètres affichés.'}
          </div>
        </div>
        <aside className="mission-inspector propagation-inspector">
          {page === 'prediction' && catalog?.model?.quality_note && (
            <p className="propagation-warning" role="note">
              {catalog.model.quality_note}
            </p>
          )}
          <details className="propagation-settings" open>
            <summary>
              <SlidersHorizontal size={15} />
              Conditions du scénario
              <ChevronDown size={14} />
            </summary>
            {config && catalog && (
              <div>
                <label className="propagation-field" htmlFor="propagation-incident">
                  Type de départ
                  <select
                    id="propagation-incident"
                    value={config.incident_type ?? ''}
                    disabled={submitting}
                    onChange={(event) => {
                      const next = catalog.incidents.find((entry) => entry.id === event.target.value);
                      if (next) updateConfig({ incident_type: next.id, ...next.defaults });
                    }}
                  >
                    {catalog.incidents.map((entry) => (
                      <option key={entry.id} value={entry.id}>
                        {entry.name}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="propagation-note">{incident?.description}</p>
                <div className="propagation-input-grid">
                  {controls.map(({ key, name, unit, min, max, step }) => (
                    <label key={key} htmlFor={`propagation-${key}`}>
                      <span>
                        {name}
                        <small>{unit}</small>
                      </span>
                      <input
                        id={`propagation-${key}`}
                        type="number"
                        min={min}
                        max={max}
                        step={step}
                        disabled={submitting}
                        value={finite(config[key]) ? (config[key] as number) : ''}
                        onChange={(event) => updateConfig({ [key]: event.target.valueAsNumber })}
                      />
                    </label>
                  ))}
                </div>
                <details className="propagation-details">
                  <summary>Matériau & répétabilité</summary>
                  <label className="propagation-field">
                    Combustible de référence
                    <select
                      value={config.material_id}
                      onChange={(event) => updateConfig({ material_id: event.target.value })}
                    >
                      <option value="cellulose">Cellulose générique</option>
                      <option value="pmma">PMMA générique</option>
                    </select>
                  </label>
                  <p className="propagation-note">
                    Graine : {config.seed} · maille de référence : {format(config.mesh_cell_m ?? 0.2, 2)} m.
                    Les familles de départ sont des scénarios équivalents documentés.
                  </p>
                </details>
              </div>
            )}
          </details>
          {issue && (
            <p className="propagation-warning" role="alert">
              {issue}
            </p>
          )}
          {page === 'prediction' && (
            <>
              {!catalog?.model?.available && catalog && (
                <div className="propagation-warning">
                  <Cpu size={16} />
                  <p>
                    Le modèle de propagation n’est pas disponible sur le poste. Les points restent non
                    estimés. Vous pouvez simuler un départ avec FDS.
                  </p>
                </div>
              )}
              {assessment && !activeAssessment && (
                <p className="propagation-warning" role="status">
                  Conditions modifiées : la carte précédente est invalidée. Recalculez pour ces paramètres.
                </p>
              )}
              {predictionError && (
                <p className="propagation-warning" role="alert">
                  {predictionError}
                </p>
              )}
              {predicting && (
                <button
                  className="mission-secondary"
                  onClick={() => {
                    predictionController.current?.abort();
                    setPredicting(false);
                    setPredictionError('Attente annulée ; la requête peut encore se terminer sur le poste.');
                  }}
                >
                  <Square size={13} />
                  Annuler l’attente
                </button>
              )}
              <label className="propagation-field propagation-criterion" htmlFor="propagation-criterion">
                Comparer les conséquences
                <select
                  id="propagation-criterion"
                  value={criterion}
                  onChange={(event) => setCriterion(event.target.value as ConsequenceMetric)}
                >
                  {consequenceMetrics.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name} · {entry.unit}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <section className="propagation-components" aria-label="Départs potentiels">
            <div className="propagation-section-heading">
              <h2>Départs potentiels</h2>
              <span>{components.length} points</span>
            </div>
            {components.map((entry, index) => {
              const row = activeAssessment?.components.find((item) => item.component_id === entry.id);
              const value = consequenceValue(row?.result, criterion);
              return (
                <button
                  key={entry.id}
                  data-propagation-component={entry.id}
                  data-estimated={value !== null}
                  className={component?.id === entry.id ? 'selected' : ''}
                  aria-pressed={component?.id === entry.id}
                  onClick={() => selectComponent(entry.id)}
                >
                  <i
                    style={{
                      background:
                        page === 'prediction'
                          ? consequenceColor(value, criterion)
                          : entry.id === component?.id
                            ? '#dcea93'
                            : '#7e8d9a',
                    }}
                  />
                  <span>
                    <strong>
                      {String(index + 1).padStart(2, '0')} · {entry.name}
                    </strong>
                    <small>
                      {entry.critical ? 'Équipement critique' : entry.kind}
                      {row?.error && page === 'prediction' ? ' · non estimé' : ''}
                    </small>
                  </span>
                  {page === 'prediction' && (
                    <b>
                      {format(value, mapScale.decimals)}
                      <small>{value === null ? '' : mapScale.unit}</small>
                    </b>
                  )}
                </button>
              );
            })}
          </section>
          {component && (
            <section className="propagation-selection">
              <div className="propagation-section-heading">
                <h2>{component.name}</h2>
                <Zap size={16} />
              </div>
              <p className="propagation-note">
                Conséquences sur {format(config?.duration_s, 0)} s si ce départ survient ici. La probabilité
                de panne n’est pas estimée.
              </p>
              {page === 'prediction' && prediction?.error && (
                <p className="propagation-warning">{prediction.error}</p>
              )}
              <Consequences result={displayedResult} />
              {page === 'prediction' && (
                <button
                  className="mission-primary propagation-transfer"
                  onClick={transfer}
                  disabled={Boolean(issue) || submitting}
                >
                  Simuler ce départ <ArrowRight size={16} />
                </button>
              )}
              {page === 'simulation' && (
                <>
                  {!connected ||
                  health?.worker_available === false ||
                  health?.capabilities?.physics !== true ? (
                    <p className="propagation-warning">
                      Le moteur FDS n’est pas disponible sur le poste connecté.
                    </p>
                  ) : null}
                  {simulation && (
                    <div className={`propagation-job ${simulation.status}`} data-run-id={simulation.id}>
                      <strong>
                        {simulation.status === 'queued'
                          ? 'En file d’attente'
                          : simulation.status === 'running'
                            ? 'Calcul FDS en cours'
                            : simulation.status === 'completed'
                              ? 'Calcul FDS terminé'
                              : simulation.status === 'cancelled'
                                ? 'Calcul annulé'
                                : 'Calcul interrompu'}{' '}
                        · {simulation.id.slice(0, 8)}
                      </strong>
                      {['queued', 'running'].includes(simulation.status) && (
                        <progress value={simulation.progress ?? 0} max="1" />
                      )}
                      <p>{simulation.message ?? simulation.error}</p>
                      {!matchingSimulation && (
                        <p>
                          Ce calcul porte sur d’autres paramètres ou un autre point. Ses champs sont masqués.
                        </p>
                      )}
                      {['queued', 'running'].includes(simulation.status) && (
                        <button
                          className="mission-secondary"
                          disabled={cancelling}
                          onClick={() => {
                            void cancel();
                          }}
                        >
                          <Square size={13} />
                          {cancelling ? 'Annulation…' : 'Annuler le calcul FDS'}
                        </button>
                      )}
                    </div>
                  )}
                  {(simulationError || pollError) && (
                    <p className="propagation-warning" role="alert">
                      {simulationError ?? pollError}
                    </p>
                  )}
                  {matchingSimulation && simulation?.status === 'completed' && (
                    <a
                      className="mission-secondary propagation-export"
                      href={api.exportUrl(simulation.id)}
                      download
                    >
                      <ArrowDownToLine size={14} />
                      Exporter le calcul FDS
                    </a>
                  )}
                </>
              )}
              {page === 'prediction' && activeAssessment && (
                <button className="mission-secondary propagation-export" onClick={exportPrediction}>
                  <ArrowDownToLine size={14} />
                  Exporter la carte et les champs
                </button>
              )}
              <details className="propagation-details">
                <summary>Origine & limites</summary>
                <p>{component.provenance}</p>
                <p>
                  Position annotée : {component.position_m.map((value) => format(value, 2)).join(' / ')} m
                  (X/Y/Z).
                </p>
                {appliedPosition && (
                  <p>
                    Source appliquée : {appliedPosition.map((value) => format(value, 2)).join(' / ')} m
                    (X/Y/Z). Le marqueur suit cette position dans le maillage du résultat.
                  </p>
                )}
                {Boolean(incidentProvenance) && (
                  <details>
                    <summary>Provenance du départ</summary>
                    <pre>{JSON.stringify(incidentProvenance, null, 2)}</pre>
                  </details>
                )}
                {displayedResult?.provenance.warnings?.map((warning, index) => (
                  <p key={index}>{warning}</p>
                ))}
                {incident?.limitations.map((limit, index) => (
                  <p key={`i-${index}`}>{limit}</p>
                ))}
                {page === 'prediction' && catalog?.model && (
                  <>
                    <p>
                      Modèle : {activeAssessment?.model_id ?? catalog.model.id}. {catalog.model.name}
                    </p>
                    {catalog.model.limitations.map((limit, index) => (
                      <p key={`m-${index}`}>{limit}</p>
                    ))}
                    {(catalog.model.metrics || catalog.model.domain) && (
                      <details>
                        <summary>Évaluation et domaine du modèle</summary>
                        <pre>
                          {JSON.stringify(
                            { metrics: catalog.model.metrics, domain: catalog.model.domain },
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    )}
                  </>
                )}
              </details>
            </section>
          )}
          <details className="propagation-details">
            <summary>Affichage 3D</summary>
            <label className="propagation-check">
              <input
                type="checkbox"
                checked={cutaway}
                onChange={(event) => setCutaway(event.target.checked)}
              />
              Cabine en coupe
            </label>
            <label className="propagation-field">
              Opacité des champs
              <input
                aria-label="Opacité des champs"
                type="range"
                min="0.1"
                max="1"
                step="0.05"
                value={opacity}
                onChange={(event) => setOpacity(event.target.valueAsNumber)}
              />
            </label>
            <p>Réglages visuels ; les valeurs calculées restent inchangées.</p>
          </details>
          <p className="propagation-footer-note">
            Les couleurs décrivent une exposition simulée. Les feux issus d’arcs, de batteries et des autres
            familles sont représentés par leurs scénarios équivalents.
          </p>
        </aside>
      </div>
    </div>
  );
}
