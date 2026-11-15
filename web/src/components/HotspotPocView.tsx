import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  Box,
  Check,
  Database,
  Eye,
  Focus,
  Info,
  LoaderCircle,
  Maximize2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ScanLine,
  SkipBack,
  Thermometer,
  Wind,
} from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { format, toWorld } from '../data';
import {
  aggregateHotspotMetrics,
  hotspotBaselineRows,
  HOTSPOT_COLORS,
  hotspotCaseUrl,
  hotspotColdCaseAlarms,
  hotspotClass,
  hotspotFrameMetrics,
  parseHotspotCase,
  parseHotspotIndex,
  peakHotspotFrame,
  SPLIT_LABELS,
} from '../hotspot-poc';
import type {
  HotspotCase,
  HotspotClass,
  HotspotFrame,
  HotspotIndex,
  HotspotMetrics,
  PocSplit,
} from '../hotspot-poc';
import '../hotspot-poc.css';

type CameraMode = 'orbit' | 'top';
interface ViewProps {
  data: HotspotCase;
  frame: HotspotFrame;
  delta: number;
  threshold: number;
  cameraMode: CameraMode;
  reset: number;
  showCold: boolean;
  showErrors: boolean;
}
interface RenderState {
  worlds: THREE.Scene[];
  points: THREE.InstancedMesh[];
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  configure: () => void;
  invalidate: () => void;
}

const percent = (value: number | null | undefined) => (value == null ? '—' : `${format(value * 100, 1)} %`);
const integer = (value: number | undefined) => (value == null ? '—' : format(value, 0));
const scoreText = (value: number | null | undefined) =>
  value == null ? '—' : new Intl.NumberFormat('fr-FR', { maximumSignificantDigits: 7 }).format(value);
const incidentName = (value: string) =>
  ({
    overheating: 'Surchauffe',
    arc: 'Arc électrique',
    flaming: 'Flamme prescrite',
    smoldering: 'Couvaison',
    battery: 'Incident batterie',
    none: 'Sans dépassement observé',
    quiet: 'Sans dépassement observé',
  })[value] ?? value;

function releaseScenes(worlds: THREE.Scene[]) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  worlds.forEach((world) =>
    world.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (mesh.geometry) geometries.add(mesh.geometry);
      if (mesh.material)
        (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((material) =>
          materials.add(material),
        );
    }),
  );
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

function makeWorld(data: HotspotCase) {
  const world = new THREE.Scene();
  world.add(new THREE.HemisphereLight('#d9eaf2', '#16212d', 2.5));
  const key = new THREE.DirectionalLight('#fff5df', 2);
  key.position.set(3, 8, 4);
  world.add(key);
  const [x, y, z] = data.scene.bounds_m;
  const span = Math.max(x, y, z);
  const box = new THREE.BoxGeometry(x, z, y);
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(box),
    new THREE.LineBasicMaterial({ color: '#3c515d', transparent: true, opacity: 0.55 }),
  );
  box.dispose();
  outline.position.set(x / 2, z / 2, -y / 2);
  world.add(outline);
  const floor = new THREE.GridHelper(span * 1.2, 12, '#263c48', '#162630');
  floor.position.set(x / 2, -0.025, -y / 2);
  world.add(floor);
  for (const object of data.scene.objects) {
    if (object.role === 'decoration') continue;
    const wall = object.role === 'wall';
    const combustible =
      Boolean(object.combustible_material_id) ||
      object.role === 'fuel' ||
      ['cellulose', 'pmma'].includes(object.material_id);
    const geometry = new THREE.BoxGeometry(object.size_m[0], object.size_m[2], object.size_m[1]);
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: combustible ? '#a79174' : '#68828c',
        roughness: 0.85,
        transparent: true,
        opacity: wall ? 0.025 : 0.2,
        depthWrite: false,
      }),
    );
    mesh.position.set(...toWorld(object.center_m));
    world.add(mesh);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({
        color: combustible ? '#8c795f' : '#425b68',
        transparent: true,
        opacity: wall ? 0.1 : 0.5,
      }),
    );
    edges.position.copy(mesh.position);
    world.add(edges);
  }
  for (const vent of data.scene.vents) {
    const color = vent.role === 'inlet' ? '#86d5bd' : '#a5a1e4';
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(
        Math.max(0.025, vent.size_m[0]),
        Math.max(0.025, vent.size_m[2]),
        Math.max(0.025, vent.size_m[1]),
      ),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.32, depthWrite: false }),
    );
    mesh.position.set(...toWorld(vent.center_m));
    world.add(mesh);
    const direction = new THREE.Vector3(...toWorld(vent.normal));
    if (direction.lengthSq() > 0)
      world.add(
        new THREE.ArrowHelper(
          direction.normalize(),
          mesh.position,
          span * 0.08,
          color,
          span * 0.02,
          span * 0.012,
        ),
      );
  }
  const source = new THREE.Mesh(
    new THREE.OctahedronGeometry(span * 0.018),
    new THREE.MeshBasicMaterial({ color: '#e1e9ed', wireframe: true, depthTest: false }),
  );
  source.position.set(...toWorld(data.conditions.source_position_m));
  source.renderOrder = 4;
  world.add(source);
  const points = new THREE.InstancedMesh(
    new THREE.SphereGeometry(1, 10, 8),
    new THREE.MeshBasicMaterial({ vertexColors: false }),
    data.sample_positions_m.length,
  );
  points.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  points.frustumCulled = false;
  world.add(points);
  return { world, points };
}

function updatePoints(state: RenderState, props: ViewProps) {
  const { data, frame, delta, threshold, showCold, showErrors } = props;
  const radius = Math.max(...data.scene.bounds_m) * 0.0085;
  const matrix = new THREE.Matrix4();
  const rotation = new THREE.Quaternion();
  const color = new THREE.Color();
  const position = new THREE.Vector3();
  const scale = new THREE.Vector3();
  data.sample_positions_m.forEach((sample, point) => {
    const kind = hotspotClass(frame, point, data.conditions.ambient_temperature_c, delta, threshold);
    const truth = kind === 'tp' || kind === 'fn';
    const predicted = kind === 'tp' || kind === 'fp';
    position.set(...toWorld(sample));
    state.points.forEach((mesh, view) => {
      const hot = view === 0 ? truth : predicted;
      const visible = kind !== null && (showCold || hot || (view === 1 && showErrors && kind === 'fn'));
      const size = visible ? radius * (hot || (showErrors && kind === 'fn') ? 1 : 0.4) : 0;
      matrix.compose(position, rotation, scale.setScalar(size));
      mesh.setMatrixAt(point, matrix);
      if (view === 1 && showErrors && kind) color.set(HOTSPOT_COLORS[kind]);
      else if (view === 0 && truth) {
        const rise = (frame.temperature_c[point] ?? 0) - data.conditions.ambient_temperature_c;
        color.setHSL(0.095 - Math.min(1, Math.max(0, rise - delta) / 100) * 0.075, 0.92, 0.65);
      } else if (view === 1 && predicted) {
        color.setHSL(0.11 - (frame.hotspot_score[point] ?? 0) * 0.075, 0.88, 0.66);
      } else color.set(HOTSPOT_COLORS.tn);
      mesh.setColorAt(point, color);
    });
  });
  state.points.forEach((mesh) => {
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  state.invalidate();
}

function ComparisonViewport(props: ViewProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<RenderState | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    setSelected(null);
    setError(null);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance',
      });
    } catch {
      setError('La comparaison 3D nécessite WebGL. Les mesures restent consultables ci-dessous.');
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setClearColor('#09141c');
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const canvas = renderer.domElement;
    canvas.setAttribute(
      'aria-label',
      'Comparaison 3D FDS et ML. Glisser pour tourner les deux vues ; cliquer sur une sonde pour ses valeurs.',
    );
    canvas.tabIndex = 0;
    element.appendChild(canvas);
    const builds = [makeWorld(props.data), makeWorld(props.data)];
    const worlds = builds.map((item) => item.world);
    const points = builds.map((item) => item.points);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 300);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    const [x, y, z] = props.data.scene.bounds_m;
    const span = Math.max(x, y, z);
    controls.minDistance = span * 0.18;
    controls.maxDistance = span * 7;
    let dirty = true;
    let alive = true;
    let raf = 0;
    let width = 1;
    let height = 1;
    let stacked = false;
    const invalidate = () => {
      dirty = true;
    };
    const configure = () => {
      const top = latest.current.cameraMode === 'top';
      controls.enableRotate = !top;
      controls.target.set(x / 2, z * 0.45, -y / 2);
      camera.up.set(0, top ? 0 : 1, top ? -1 : 0);
      const fit = Math.max(1, 0.9 / camera.aspect);
      if (top) camera.position.set(x / 2, z + span * 1.5 * fit, -y / 2 + 0.001);
      else
        camera.position.set(x / 2 + span * 0.95 * fit, z * 0.5 + span * 0.8 * fit, -y / 2 + span * 1.2 * fit);
      camera.lookAt(controls.target);
      controls.update();
      invalidate();
    };
    const state: RenderState = { worlds, points, camera, controls, configure, invalidate };
    view.current = state;
    const resize = () => {
      width = Math.max(1, element.clientWidth);
      height = Math.max(1, element.clientHeight);
      const nextStacked = width < 650;
      const changed = stacked !== nextStacked;
      stacked = nextStacked;
      renderer.setSize(width, height);
      camera.aspect = stacked ? width / (height / 2) : width / 2 / height;
      camera.updateProjectionMatrix();
      if (changed) configure();
      invalidate();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    configure();
    updatePoints(state, latest.current);
    controls.addEventListener('change', invalidate);
    const render = () => {
      if (!alive) return;
      controls.update();
      if (dirty) {
        renderer.setScissorTest(true);
        worlds.forEach((world, index) => {
          const vx = stacked ? 0 : (index * width) / 2;
          const vy = stacked ? ((1 - index) * height) / 2 : 0;
          const vw = stacked ? width : width / 2;
          const vh = stacked ? height / 2 : height;
          renderer.setViewport(vx, vy, vw, vh);
          renderer.setScissor(vx, vy, vw, vh);
          renderer.render(world, camera);
        });
        dirty = false;
      }
      raf = requestAnimationFrame(render);
    };
    render();
    const raycaster = new THREE.Raycaster();
    let down = { x: 0, y: 0 };
    const pointerDown = (event: PointerEvent) => {
      down = { x: event.clientX, y: event.clientY };
    };
    const pointerUp = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return;
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      const index = stacked ? (py >= height / 2 ? 1 : 0) : px >= width / 2 ? 1 : 0;
      const nx = stacked ? px / width : (px - (index * width) / 2) / (width / 2);
      const ny = stacked ? (py - (index * height) / 2) / (height / 2) : py / height;
      raycaster.setFromCamera(new THREE.Vector2(nx * 2 - 1, 1 - ny * 2), camera);
      const match = raycaster.intersectObject(points[index]).find((hit) => {
        if (hit.instanceId === undefined) return false;
        const current = latest.current;
        const kind = hotspotClass(
          current.frame,
          hit.instanceId,
          current.data.conditions.ambient_temperature_c,
          current.delta,
          current.threshold,
        );
        if (!kind) return false;
        return (
          current.showCold ||
          (index === 0
            ? kind === 'tp' || kind === 'fn'
            : kind === 'tp' || kind === 'fp' || (current.showErrors && kind === 'fn'))
        );
      });
      setSelected(match?.instanceId ?? null);
    };
    canvas.addEventListener('pointerdown', pointerDown);
    canvas.addEventListener('pointerup', pointerUp);
    const contextLost = (event: Event) => {
      event.preventDefault();
      setError('Le contexte 3D a été interrompu. Rechargez la vue pour le rétablir.');
    };
    canvas.addEventListener('webglcontextlost', contextLost);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      canvas.removeEventListener('pointerdown', pointerDown);
      canvas.removeEventListener('pointerup', pointerUp);
      canvas.removeEventListener('webglcontextlost', contextLost);
      releaseScenes(worlds);
      renderer.dispose();
      canvas.remove();
      view.current = null;
    };
  }, [props.data]);

  useEffect(() => {
    if (view.current) updatePoints(view.current, props);
  }, [props.frame, props.delta, props.threshold, props.showCold, props.showErrors]);

  useEffect(() => {
    view.current?.configure();
  }, [props.cameraMode, props.reset]);

  const kind =
    selected === null
      ? null
      : hotspotClass(
          props.frame,
          selected,
          props.data.conditions.ambient_temperature_c,
          props.delta,
          props.threshold,
        );
  return (
    <div className="poc-stage">
      <div className="poc-canvas" ref={host} />
      <div className="poc-panes">
        <div data-poc-view="reference" className="poc-pane">
          <div className="poc-pane-title">
            <span>01 / Référence</span>
            <h2>Simulation FDS</h2>
            <p>Chaud à partir de {format(props.data.conditions.ambient_temperature_c + props.delta)} °C</p>
          </div>
          <div className="poc-pane-foot">
            <i className="poc-dot hot" /> Température mesurée aux sondes du calcul
          </div>
        </div>
        <div data-poc-view="prediction" className="poc-pane">
          <div className="poc-pane-title">
            <span>02 / Modèle appris</span>
            <h2>{props.showErrors ? 'Où le modèle se trompe' : 'Points chauds prédits'}</h2>
            <p>
              {props.threshold > 1
                ? 'Aucune alerte au seuil retenu'
                : `Score de classe ≥ ${scoreText(props.threshold)}`}
            </p>
          </div>
          <div className="poc-pane-foot">
            <i className="poc-dot model" />{' '}
            {props.showErrors
              ? 'Détecté · manqué · fausse alerte'
              : 'Score non calibré · aucune température prédite'}
          </div>
        </div>
      </div>
      {error && (
        <div className="poc-render-error" role="alert">
          {error}
        </div>
      )}
      {selected !== null && (
        <div className="poc-probe" role="status">
          <strong>Sonde {selected + 1}</strong>
          <span>{props.data.sample_positions_m[selected].map((n) => format(n, 2)).join(' / ')} m</span>
          <span>
            FDS {format(props.frame.temperature_c[selected])} °C · score{' '}
            {scoreText(props.frame.hotspot_score[selected])}
          </span>
          <span>
            {kind
              ? {
                  tp: 'Point chaud détecté',
                  fn: 'Point chaud manqué',
                  fp: 'Fausse alerte',
                  tn: 'Point froid',
                }[kind]
              : 'Mesure exclue ou indisponible à cet instant'}
          </span>
        </div>
      )}
      <div className="poc-orbit-hint">
        <Focus size={13} /> Caméras liées · glisser pour tourner · molette pour zoomer
      </div>
    </div>
  );
}

function MetricStrip({ metrics, label }: { metrics: HotspotMetrics | null; label: string }) {
  return (
    <div className="poc-metric-group">
      <div className="poc-section-label">{label}</div>
      <div className="poc-metrics">
        <div>
          <span>Rappel des points chauds</span>
          <strong>{percent(metrics?.recall)}</strong>
          <small>Chaud correctement repéré / chaud réel</small>
        </div>
        <div>
          <span>Précision des alertes</span>
          <strong>{percent(metrics?.precision)}</strong>
          <small>Chaud réel / points signalés</small>
        </div>
        <div>
          <span>Recouvrement · IoU</span>
          <strong>{percent(metrics?.iou)}</strong>
          <small>Intersection / union des points chauds</small>
        </div>
        <div>
          <span>Fausses alertes</span>
          <strong>{percent(metrics?.false_positive_rate)}</strong>
          <small>{integer(metrics?.fp)} faux positifs / points froids</small>
        </div>
      </div>
    </div>
  );
}

async function readJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { signal, cache: 'no-store' });
  if (response.status === 404) throw new Error('pending');
  if (!response.ok) throw new Error(`Lecture impossible (${response.status}).`);
  if (!response.headers.get('content-type')?.includes('json')) throw new Error('pending');
  return response.json();
}

export default function HotspotPocView({ onOpenSources }: { onOpenSources: () => void }) {
  const [index, setIndex] = useState<HotspotIndex | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [split, setSplit] = useState<PocSplit | 'all'>('validation');
  const [caseId, setCaseId] = useState('');
  const [loaded, setLoaded] = useState<HotspotCase | null>(null);
  const [caseError, setCaseError] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [cameraMode, setCameraMode] = useState<CameraMode>('orbit');
  const [reset, setReset] = useState(0);
  const [showCold, setShowCold] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const cache = useRef(new Map<string, HotspotCase>());
  const root = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setIndexError(null);
    setPlaying(false);
    cache.current.clear();
    void readJson('/poc/hotspots.json', controller.signal)
      .then(parseHotspotIndex)
      .then((next) => {
        if (controller.signal.aborted) return;
        cache.current.clear();
        setLoaded(null);
        setIndex(next);
        setCaseId((previous) =>
          next.cases.some((item) => item.id === previous)
            ? previous
            : (next.default_case_id ?? next.cases[0]?.id ?? ''),
        );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setIndex(null);
          setIndexError(error instanceof Error ? error.message : 'Export indisponible.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reload]);

  const cases = useMemo(
    () => index?.cases.filter((item) => split === 'all' || item.split === split) ?? [],
    [index, split],
  );
  const selected = cases.find((item) => item.id === caseId) ?? cases[0];
  const data = loaded?.id === selected?.id ? loaded : null;
  const frame = data?.frames[Math.min(frameIndex, data.frames.length - 1)];
  const aggregate = useMemo(() => aggregateHotspotMetrics(cases), [cases]);
  const coldCaseAlarms = useMemo(() => hotspotColdCaseAlarms(cases), [cases]);
  const baselineRows = index ? hotspotBaselineRows(index, split) : [];
  const currentMetrics =
    frame && data && index
      ? hotspotFrameMetrics(
          frame,
          data.conditions.ambient_temperature_c,
          index.model.heat_delta_c,
          index.model.score_threshold,
        )
      : null;

  useEffect(() => {
    if (!selected) {
      setLoaded(null);
      return;
    }
    const controller = new AbortController();
    setCaseError(null);
    setLoaded(null);
    setPlaying(false);
    setFrameIndex(0);
    const cached = cache.current.get(selected.id);
    if (cached) {
      setLoaded(cached);
      setFrameIndex(peakHotspotFrame(cached.frames));
      return () => controller.abort();
    }
    void readJson(hotspotCaseUrl(selected.url), controller.signal)
      .then((raw) => parseHotspotCase(raw, selected.id))
      .then((next) => {
        if (controller.signal.aborted) return;
        cache.current.set(next.id, next);
        if (cache.current.size > 3) cache.current.delete(cache.current.keys().next().value as string);
        setLoaded(next);
        setFrameIndex(peakHotspotFrame(next.frames));
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setCaseError(error instanceof Error ? error.message : 'Cas indisponible.');
      });
    return () => controller.abort();
  }, [selected]);

  useEffect(() => {
    if (!playing || !data || !frame) return;
    const next = data.frames[frameIndex + 1];
    if (!next) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(
      () => setFrameIndex((previous) => previous + 1),
      Math.max(50, ((next.time_s - frame.time_s) * 1000) / speed),
    );
    return () => window.clearTimeout(timer);
  }, [playing, data, frame, frameIndex, speed]);

  const chooseCase = (id: string) => {
    setPlaying(false);
    setFrameIndex(0);
    setCaseId(id);
  };
  const chooseExample = (id: string | undefined) => {
    if (!id) return;
    setSplit(index?.cases.find((item) => item.id === id)?.split ?? 'validation');
    chooseCase(id);
  };
  const changeSplit = (value: PocSplit | 'all') => {
    setPlaying(false);
    setSplit(value);
  };
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void root.current?.requestFullscreen?.().catch(() => {});
  };

  return (
    <section
      className="hotspot-poc"
      data-hotspot-poc
      data-case-id={selected?.id ?? ''}
      data-time-s={frame?.time_s ?? ''}
      ref={root}
    >
      <header className="poc-header">
        <div>
          <div className="poc-eyebrow">
            <ScanLine size={14} /> POC · prédictions enregistrées
          </div>
          <h1>Points chauds · FDS / modèle ML</h1>
          <p>Une simulation FDS et les prédictions du modèle, aux mêmes positions et au même instant.</p>
        </div>
        <div className="poc-header-actions">
          <button onClick={onOpenSources}>
            <Database size={15} /> Sources NASA <ArrowRight size={13} />
          </button>
          <button
            className="poc-square"
            onClick={() => setReload((value) => value + 1)}
            aria-label="Actualiser les résultats du POC"
          >
            <RefreshCw size={16} className={loading ? 'poc-spin' : ''} />
          </button>
          <button className="poc-square" onClick={fullscreen} aria-label="Agrandir la comparaison">
            <Maximize2 size={16} />
          </button>
        </div>
      </header>

      {!index ? (
        <div className="poc-waiting" role="status">
          {loading ? <LoaderCircle size={28} className="poc-spin" /> : <ScanLine size={34} />}
          <h2>
            {loading
              ? 'Lecture des résultats…'
              : indexError === 'pending'
                ? 'La comparaison attend ses résultats.'
                : 'Les résultats ne peuvent pas être ouverts.'}
          </h2>
          <p>
            {loading
              ? 'Chargement de l’index des cas enregistrés.'
              : indexError === 'pending'
                ? 'Les cas simulés, les scores du modèle et leurs mesures apparaîtront ici dès que l’export sera disponible.'
                : indexError}
          </p>
          {!loading && (
            <button onClick={() => setReload((value) => value + 1)}>
              <RefreshCw size={15} /> Vérifier la disponibilité
            </button>
          )}
          <small>Cette vue relit des résultats enregistrés. Elle ne lance aucun calcul.</small>
        </div>
      ) : (
        <>
          <div className="poc-selection">
            <label>
              <span>Jeu de données</span>
              <select
                value={split}
                onChange={(event) => changeSplit(event.target.value as PocSplit | 'all')}
                aria-label="Partition des données"
              >
                <option value="all">Tous les cas · {index.cases.length}</option>
                <option value="train">Entraînement</option>
                <option value="validation">Validation</option>
                <option value="test">Test historique déjà consulté</option>
              </select>
            </label>
            <label className="poc-case-select">
              <span>Scénario · {cases.length} cas disponibles</span>
              <select
                aria-label="Scénario du POC"
                value={selected?.id ?? ''}
                onChange={(event) => chooseCase(event.target.value)}
                disabled={!cases.length}
              >
                {!cases.length && <option value="">Aucun cas dans cette partition</option>}
                {cases.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} · {incidentName(item.incident_type)} ·{' '}
                    {item.gravity_g < 0.01 ? 'µg' : `${format(item.gravity_g, 2)} g`}
                  </option>
                ))}
              </select>
            </label>
            {index.example_cases && (
              <div className="poc-examples">
                <span>Explorer les résultats</span>
                <div>
                  <button
                    disabled={!index.example_cases.representative}
                    onClick={() => chooseExample(index.example_cases?.representative)}
                  >
                    Représentatif
                  </button>
                  <button
                    disabled={!index.example_cases.failure}
                    onClick={() => chooseExample(index.example_cases?.failure)}
                  >
                    Échec observé
                  </button>
                  <button
                    disabled={!index.example_cases.cold_control}
                    onClick={() => chooseExample(index.example_cases?.cold_control)}
                  >
                    Témoin froid
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="poc-workspace">
            <div className="poc-comparison">
              <div className="poc-view-toolbar">
                <div className="poc-camera">
                  <button
                    aria-pressed={cameraMode === 'orbit'}
                    className={cameraMode === 'orbit' ? 'active' : ''}
                    onClick={() => setCameraMode('orbit')}
                  >
                    <Box size={14} /> Orbite
                  </button>
                  <button
                    aria-pressed={cameraMode === 'top'}
                    className={cameraMode === 'top' ? 'active' : ''}
                    onClick={() => setCameraMode('top')}
                  >
                    <Eye size={14} /> Dessus
                  </button>
                  <button onClick={() => setReset((value) => value + 1)} aria-label="Recentrer les deux vues">
                    <RotateCcw size={14} />
                  </button>
                  <button
                    disabled={!data}
                    onClick={() => {
                      setPlaying(false);
                      if (data) setFrameIndex(peakHotspotFrame(data.frames));
                    }}
                    title="Instant du maximum de température FDS aux sondes"
                  >
                    <Thermometer size={14} /> Pic FDS
                  </button>
                </div>
                <div className="poc-layers">
                  <label>
                    <input
                      type="checkbox"
                      checked={showErrors}
                      onChange={(event) => setShowErrors(event.target.checked)}
                    />{' '}
                    Erreurs ML
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={showCold}
                      onChange={(event) => setShowCold(event.target.checked)}
                    />{' '}
                    Points froids
                  </label>
                </div>
              </div>
              {data && frame ? (
                <ComparisonViewport
                  data={data}
                  frame={frame}
                  delta={index.model.heat_delta_c}
                  threshold={index.model.score_threshold}
                  cameraMode={cameraMode}
                  reset={reset}
                  showCold={showCold}
                  showErrors={showErrors}
                />
              ) : (
                <div className="poc-stage poc-loading-stage" role="status">
                  {caseError ? (
                    <>
                      <Info size={22} />
                      <p>{caseError === 'pending' ? 'Ce cas attend encore son export.' : caseError}</p>
                      <button onClick={() => setReload((value) => value + 1)}>Réessayer</button>
                    </>
                  ) : selected ? (
                    <>
                      <LoaderCircle size={23} className="poc-spin" />
                      <p>Chargement de la géométrie et des mesures…</p>
                    </>
                  ) : (
                    <p>Aucun cas disponible.</p>
                  )}
                </div>
              )}
              <div className="poc-timeline">
                <button
                  onClick={() => {
                    setPlaying(false);
                    setFrameIndex(0);
                  }}
                  disabled={!data}
                  aria-label="Revenir au premier instant"
                >
                  <SkipBack size={16} />
                </button>
                <button
                  className="poc-play"
                  disabled={!data || data.frames.length < 2}
                  aria-label={playing ? 'Mettre en pause' : 'Lire la comparaison'}
                  onClick={() => {
                    if (data && frameIndex >= data.frames.length - 1) setFrameIndex(0);
                    setPlaying((value) => !value);
                  }}
                >
                  {playing ? <Pause size={17} /> : <Play size={17} />}
                </button>
                <strong>
                  {format(frame?.time_s, 1)} <small>s</small>
                </strong>
                <input
                  type="range"
                  aria-label="Instant de comparaison"
                  min={0}
                  max={Math.max(0, (data?.frames.length ?? 1) - 1)}
                  step={1}
                  value={data ? Math.min(frameIndex, data.frames.length - 1) : 0}
                  disabled={!data || data.frames.length < 2}
                  onChange={(event) => {
                    setPlaying(false);
                    setFrameIndex(Number(event.target.value));
                  }}
                />
                <span>{format(data?.frames.at(-1)?.time_s, 1)} s</span>
                <select
                  aria-label="Vitesse de lecture"
                  value={speed}
                  onChange={(event) => setSpeed(Number(event.target.value))}
                >
                  <option value={1}>×1</option>
                  <option value={5}>×5</option>
                  <option value={10}>×10</option>
                </select>
              </div>
              <div className="poc-legend">
                {showErrors ? (
                  (['tp', 'fn', 'fp'] as HotspotClass[]).map((kind) => (
                    <span key={kind}>
                      <i style={{ background: HOTSPOT_COLORS[kind] }} />
                      {{ tp: 'Chaud détecté', fn: 'Chaud manqué', fp: 'Fausse alerte', tn: 'Froid' }[kind]}
                    </span>
                  ))
                ) : (
                  <span>
                    <i style={{ background: HOTSPOT_COLORS.tp }} /> Points au-dessus du seuil de chaque vue
                  </span>
                )}
                <span className="poc-support-note">Sondes discrètes · pas de champ interpolé</span>
              </div>
            </div>

            <aside className="poc-inspector">
              <div className="poc-section-label">Scénario sélectionné</div>
              {selected ? (
                <>
                  <span className={`poc-split ${selected.split}`}>{SPLIT_LABELS[selected.split]}</span>
                  <h2>{incidentName(selected.incident_type)}</h2>
                  <p className="poc-layout-name">{data?.scene.name ?? selected.family}</p>
                  <code>{selected.layout_id}</code>
                  <dl className="poc-conditions">
                    <div>
                      <dt>Gravité</dt>
                      <dd>
                        {selected.gravity_g < 0.01 ? 'Microgravité' : 'Gravité terrestre'}{' '}
                        <small>{format(selected.gravity_g, selected.gravity_g < 0.01 ? 4 : 2)} g</small>
                      </dd>
                    </div>
                    <div>
                      <dt>
                        <Wind size={12} /> Ventilation
                      </dt>
                      <dd>{format(selected.airflow_m_s, 2)} m/s</dd>
                    </div>
                    <div>
                      <dt>
                        <Thermometer size={12} /> Ambiante
                      </dt>
                      <dd>{format(selected.ambient_temperature_c)} °C</dd>
                    </div>
                    {data?.conditions.oxygen_percent !== undefined && (
                      <div>
                        <dt>Oxygène</dt>
                        <dd>{format(data.conditions.oxygen_percent)} %</dd>
                      </div>
                    )}
                    {data && (
                      <div>
                        <dt>Source · x / y / z</dt>
                        <dd>{data.conditions.source_position_m.map((n) => format(n, 2)).join(' / ')} m</dd>
                      </div>
                    )}
                    {data?.conditions.power_w !== undefined && (
                      <div>
                        <dt>Puissance imposée</dt>
                        <dd>{format(data.conditions.power_w, 0)} W</dd>
                      </div>
                    )}
                    {data?.conditions.source_duration_s !== undefined && (
                      <div>
                        <dt>Durée de la source</dt>
                        <dd>{format(data.conditions.source_duration_s)} s</dd>
                      </div>
                    )}
                    <div>
                      <dt>Pic FDS enregistré</dt>
                      <dd>{format(selected.peak_temperature_c)} °C</dd>
                    </div>
                  </dl>
                  {data && (
                    <div className="poc-materials">
                      <span className="poc-section-label">Matériaux des proxies</span>
                      <p>
                        {[
                          ...new Set(
                            data.scene.objects
                              .filter((item) => item.role !== 'decoration')
                              .map((item) =>
                                item.combustible_material_id
                                  ? `${item.material_id} / ${item.combustible_material_id}`
                                  : item.material_id,
                              ),
                          ),
                        ].join(' · ') || 'Aucun matériau renseigné'}
                      </p>
                      <small>
                        Contours : géométrie physique. Flèches : orientation des bouches, pas un champ d’air
                        calculé.
                      </small>
                    </div>
                  )}
                  <div className="poc-current">
                    <span className="poc-section-label">
                      À cet instant {frame?.time_s === 0 && '· t = 0 exclu des métriques'}
                    </span>
                    <div>
                      <span>
                        <i style={{ background: HOTSPOT_COLORS.tp }} /> Détectés
                      </span>
                      <strong>{integer(currentMetrics?.tp)}</strong>
                    </div>
                    <div>
                      <span>
                        <i style={{ background: HOTSPOT_COLORS.fn }} /> Manqués
                      </span>
                      <strong>{integer(currentMetrics?.fn)}</strong>
                    </div>
                    <div>
                      <span>
                        <i style={{ background: HOTSPOT_COLORS.fp }} /> Fausses alertes
                      </span>
                      <strong>{integer(currentMetrics?.fp)}</strong>
                    </div>
                    <small>{integer(currentMetrics?.n_valid)} sondes comparables</small>
                  </div>
                </>
              ) : (
                <p>Aucun scénario exporté.</p>
              )}
            </aside>
          </div>

          <MetricStrip
            metrics={selected?.metrics ?? null}
            label="Ce scénario · tous les instants après t = 0"
          />
          <MetricStrip
            metrics={aggregate}
            label={`${split === 'all' ? 'Ensemble affiché · entraînement, validation et test réunis' : SPLIT_LABELS[split]} · ${cases.length} cas · métriques regroupées par point et instant`}
          />
          <p className="poc-metric-note">
            Cas sans dépassement thermique observé ayant au moins une fausse alerte :{' '}
            <strong>
              {coldCaseAlarms.total ? `${coldCaseAlarms.alerted} / ${coldCaseAlarms.total}` : '— (aucun cas)'}
            </strong>
            . Ce comptage par cas complète le taux de faux positifs par point. Un « témoin froid » signifie
            sans dépassement observé aux sondes après t = 0.
          </p>
          {baselineRows.length > 0 && (
            <section className="poc-baseline" aria-label="Comparaison F1 avec la proximité de la source">
              <div>
                <h2>Le modèle face à une règle simple</h2>
                <p>
                  F1 : équilibre entre précision et rappel, de 0 à 1. Valeurs rapportées sur cette partition.
                </p>
              </div>
              <table>
                <caption>Comparaison par gravité</caption>
                <thead>
                  <tr>
                    <th scope="col">Gravité</th>
                    <th scope="col">Modèle ML · F1</th>
                    <th scope="col">Proximité source · F1</th>
                  </tr>
                </thead>
                <tbody>
                  {baselineRows.map((row) => (
                    <tr key={row.gravity}>
                      <th scope="row">{row.label}</th>
                      <td>{format(row.model_f1, 3)}</td>
                      <td>{format(row.proximity_f1, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <small>
                Mêmes cas et instants, seuil de chaque méthode fixé sur validation. La règle de proximité est
                indépendante du temps.
              </small>
            </section>
          )}
          <p className="poc-metric-note">
            Une valeur « — » indique un ratio non défini, par exemple aucun point chaud réel. Les points et
            instants d’un même scénario sont corrélés. Les résultats d’entraînement ne mesurent pas la
            généralisation.
          </p>

          <div className="poc-evidence-row">
            <div>
              <Check size={17} />
              <div>
                <strong>{index.model.name}</strong>
                <p>
                  {index.model.device ? `${index.model.device} · ` : ''}
                  {index.model.training_seconds !== undefined
                    ? `${format(index.model.training_seconds, 1)} s d’entraînement · `
                    : ''}
                  seuil fixé sur la validation : {scoreText(index.model.score_threshold)}
                </p>
              </div>
            </div>
            <div>
              <Info size={17} />
              <p>
                Le score ML indique l’appartenance à la classe « température ≥ ambiante +{' '}
                {format(index.model.heat_delta_c)} °C ». Il n’est pas une probabilité d’incendie. Ce POC ne
                prédit pas la fumée.
              </p>
            </div>
          </div>
          <details className="poc-limitations">
            <summary>Provenance, limites et protocole de comparaison</summary>
            <div>
              <p>
                Référence : simulations FDS. Cette comparaison évalue la reproduction des points chauds du
                simulateur ; elle ne constitue pas une validation expérimentale NASA. Le test historique a
                déjà été consulté et n’est pas un test vierge.
              </p>
              <ul>
                {index.limitations.map((limit, i) => (
                  <li key={i}>{limit}</li>
                ))}
              </ul>
              {data?.notes?.length ? (
                <ul>
                  {data.notes.map((note, i) => (
                    <li key={i}>{note}</li>
                  ))}
                </ul>
              ) : null}
              <p>
                Modèle : <code>{index.model.id}</code> · export {index.generated_at}
              </p>
              {index.model.weights_sha256 && (
                <p>
                  Empreinte des poids : <code>{index.model.weights_sha256}</code>
                </p>
              )}
              {index.model.dataset_sha256 && (
                <p>
                  Empreinte du jeu de données : <code>{index.model.dataset_sha256}</code>
                </p>
              )}
              <button onClick={onOpenSources}>
                Consulter les ressources NASA <ArrowRight size={13} />
              </button>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
