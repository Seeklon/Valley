import { useEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { ArrowLeft, Crosshair, Eye, Maximize2, Pause, Play, RotateCcw, Wind } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { format } from '../data';
import { HOTSPOT_COLORS } from '../hotspot-poc';
import {
  assertIssSceneBinding,
  decodeIssCase,
  issCaseUrl,
  issFrameMetrics,
  issGeometryKey,
  issInteriorPose,
  issNearestFrame,
  issPeakFrame,
  issProbeSpacing,
  issSampleState,
  issToWorld,
  issVentilationGroupKey,
  issVentilationQuartet,
  ISS_SPLIT_LABELS,
  parseIssIndex,
} from '../iss-poc';
import type { IssCase, IssChannel, IssDisplay, IssFrame, IssIndex, IssModel, IssScene } from '../iss-poc';
import type { Vec3 } from '../types';
import type { PocSplit } from '../hotspot-poc';
import { createIssStationWorld } from '../iss-station';
import '../iss-poc.css';

type CameraMode = 'inside' | 'overview';
export interface IssOverlayOptions {
  display: IssDisplay;
  heat: boolean;
  smoke: boolean;
}
const number = (value: number | null | undefined, digits = 2) =>
  value == null ? '—' : format(value, digits);
const percent = (value: number | null | undefined) => (value == null ? '—' : `${format(value * 100, 1)} %`);
const incident = (value: string) =>
  ({
    overheating: 'Surchauffe',
    arc: 'Arc électrique',
    flaming: 'Feu électrique',
    smoldering: 'Couvaison',
    battery: 'Incident batterie',
    none: 'Témoin',
  })[value] ?? value;
const moduleName = (value: string) =>
  ({
    lab: 'Laboratoire',
    node: 'Nœud de jonction',
    technical: 'Compartiment technique',
    'iss-lab': 'Laboratoire',
    'iss-laboratory': 'Laboratoire',
    'iss-service': 'Compartiment technique',
    'iss-node': 'Nœud de jonction',
    'iss-technical': 'Compartiment technique',
    'habitat-cargo': 'Module cargo',
    'habitat-capsule': 'Capsule habitée',
    'habitat-central-racks': 'Équipements centraux',
    laboratory: 'Laboratoire',
    technical_bay: 'Compartiment technique',
  })[value] ?? value.replaceAll('_', ' ');

/**
 * Portable THREE group for the existing website. The caller supplies its physical
 * scene descriptor: a merely similar GLB is deliberately insufficient.
 * Glyphs have fixed spatial support; smoke opacity is not a physical density.
 */
export function createIssPocOverlay(data: IssCase, model: IssModel, physicalScene: IssScene) {
  assertIssSceneBinding(data, physicalScene);
  const group = new THREE.Group();
  group.name = `iss-poc:${data.id}`;
  group.userData = {
    case_id: data.id,
    weights_sha256: model.weights_sha256,
    dataset_sha256: model.dataset_sha256,
    mode: 'recorded-inference',
  };
  const spacing = issProbeSpacing(data);
  const count = data.sample_positions_m.length;
  const positions = new Float32Array(data.sample_positions_m.flatMap(issToWorld));
  const channels = (['smoke', 'heat'] as const).map((channel) => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions.slice(), 3));
    geometry.setAttribute(
      'glyphColor',
      new THREE.BufferAttribute(new Float32Array(count * 3), 3).setUsage(THREE.DynamicDrawUsage),
    );
    geometry.setAttribute(
      'glyphAlpha',
      new THREE.BufferAttribute(new Float32Array(count), 1).setUsage(THREE.DynamicDrawUsage),
    );
    const material = new THREE.ShaderMaterial({
      uniforms: {
        radius: { value: spacing * (channel === 'heat' ? 0.3 : 0.85) },
        viewportHeight: { value: 800 },
        smokeTexture: { value: channel === 'smoke' ? 1 : 0 },
      },
      vertexShader: `
        attribute vec3 glyphColor;
        attribute float glyphAlpha;
        uniform float radius;
        uniform float viewportHeight;
        varying vec3 pointColor;
        varying float pointAlpha;
        void main() {
          vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
          pointColor = glyphColor;
          pointAlpha = glyphAlpha;
          gl_Position = projectionMatrix * viewPosition;
          gl_PointSize = clamp(radius * projectionMatrix[1][1] * viewportHeight / max(0.01, -viewPosition.z), 1.0, 240.0);
        }
      `,
      fragmentShader: `
        uniform float smokeTexture;
        varying vec3 pointColor;
        varying float pointAlpha;
        void main() {
          float r = length(gl_PointCoord - vec2(0.5)) * 2.0;
          if (r > 1.0 || pointAlpha <= 0.0) discard;
          float falloff = exp(-4.0 * r * r) * (1.0 - smoothstep(0.75, 1.0, r));
          // Static glyph texture only: no transport or additional samples.
          float detail = 0.87 + 0.13 * sin(gl_PointCoord.x * 19.0 + sin(gl_PointCoord.y * 13.0)) * cos(gl_PointCoord.y * 17.0);
          falloff *= mix(1.0, detail, smokeTexture);
          gl_FragColor = vec4(pointColor, pointAlpha * falloff);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }
      `,
      transparent: true,
      depthWrite: false,
      depthTest: true,
    });
    const points = new THREE.Points(geometry, material);
    points.name = channel;
    points.frustumCulled = false;
    points.renderOrder = channel === 'heat' ? 3 : 2;
    group.add(points);
    return { channel, points, geometry, material };
  });
  const color = new THREE.Color();
  return {
    group,
    setViewportHeight(height: number) {
      channels.forEach(({ material }) => {
        material.uniforms.viewportHeight.value = Math.max(1, height);
      });
    },
    setFrame(frame: IssFrame, options: IssOverlayOptions) {
      channels.forEach(({ channel, points, geometry }) => {
        points.visible = options[channel];
        const colors = geometry.getAttribute('glyphColor') as THREE.BufferAttribute;
        const alphas = geometry.getAttribute('glyphAlpha') as THREE.BufferAttribute;
        for (let point = 0; point < count; point++) {
          const state = issSampleState(frame, point, channel, data.conditions.ambient_temperature_c, model);
          const visible =
            state &&
            (options.display === 'reference'
              ? state.truth
              : options.display === 'errors'
                ? state.truth || state.predicted
                : state.predicted);
          color.set(
            options.display === 'errors' && state
              ? HOTSPOT_COLORS[state.kind]
              : channel === 'heat'
                ? '#ff8d3a'
                : '#465766',
          );
          colors.setXYZ(point, color.r, color.g, color.b);
          alphas.setX(point, visible ? (channel === 'heat' ? 0.95 : 0.72) : 0);
        }
        colors.needsUpdate = true;
        alphas.needsUpdate = true;
      });
    },
    dispose() {
      group.removeFromParent();
      channels.forEach(({ geometry, material }) => {
        geometry.dispose();
        material.dispose();
      });
      group.clear();
    },
  };
}

function disposeWorld(world: THREE.Scene) {
  const geometry = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  world.traverse((object) => {
    if (object instanceof THREE.InstancedMesh) object.dispose();
    if (object instanceof THREE.Light) (object as THREE.DirectionalLight).shadow?.dispose();
    const mesh = object as THREE.Mesh;
    if (mesh.geometry) geometry.add(mesh.geometry);
    if (mesh.material)
      (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((material) =>
        materials.add(material),
      );
  });
  geometry.forEach((item) => item.dispose());
  const textures = new Set<THREE.Texture>();
  materials.forEach((item) => {
    Object.values(item).forEach((value) => {
      if (value instanceof THREE.Texture) textures.add(value);
    });
    item.dispose();
  });
  textures.forEach((texture) => texture.dispose());
}

interface IssCameraSnapshot {
  key: string;
  geometry: string;
  mode: CameraMode;
  reset: number;
  position: Vec3;
  direction: Vec3;
  target: Vec3;
}

interface ViewportProps extends IssOverlayOptions {
  data: IssCase;
  frame: IssFrame;
  model: IssModel;
  cameraMode: CameraMode;
  reset: number;
  cameraKey?: string | null;
  cameraMemory?: RefObject<IssCameraSnapshot | null>;
}

export function IssPocViewport(props: ViewportProps) {
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const live = useRef<{
    overlay: ReturnType<typeof createIssPocOverlay>;
    configure: () => void;
    invalidate: () => void;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    setError(null);
    setSelected(null);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    } catch {
      setError('WebGL est indisponible. Les mesures restent consultables sous la vue.');
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    const canvas = renderer.domElement;
    canvas.tabIndex = 0;
    canvas.setAttribute(
      'aria-label',
      'Module spatial en 3D. Vue intérieure : glisser pour regarder, flèches ou ZQSD pour avancer. Cliquer sur une zone pour inspecter une sonde.',
    );
    element.appendChild(canvas);
    const station = createIssStationWorld(props.data);
    const world = station.world;
    const overlay = createIssPocOverlay(props.data, props.model, props.data.scene);
    world.add(overlay.group);
    const camera = new THREE.PerspectiveCamera(61, 1, 0.025, 200);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    const [x, y, z] = props.data.scene.bounds_m;
    const span = Math.max(x, y, z);
    let dirty = true,
      alive = true,
      raf = 0,
      width = 1,
      height = 1;
    const invalidate = () => {
      dirty = true;
    };
    const direction = new THREE.Vector3(),
      right = new THREE.Vector3(),
      up = new THREE.Vector3(0, 1, 0);
    let yaw = 0,
      pitch = 0;
    // Vent roles may swap within a quartet; walls and equipment must stay identical.
    const cameraGeometry = issGeometryKey({
      ...props.data.scene,
      vents: props.data.scene.vents.map((vent) => ({ ...vent, role: 'inlet' })),
    });
    let configuredMode = props.cameraMode,
      configuredReset = props.reset;
    const look = () => {
      direction.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
      camera.lookAt(camera.position.clone().add(direction));
      invalidate();
    };
    const configure = () => {
      configuredMode = latest.current.cameraMode;
      configuredReset = latest.current.reset;
      controls.enabled = latest.current.cameraMode === 'overview';
      station.setCutaway(controls.enabled);
      if (controls.enabled) {
        controls.target.set(x / 2, z * 0.42, -y / 2);
        camera.position.set(x / 2 + span * 0.65, z + span * 0.45, span * 0.35);
        controls.minDistance = span * 0.2;
        controls.maxDistance = span * 4;
        camera.lookAt(controls.target);
        controls.update();
      } else {
        const pose = issInteriorPose(latest.current.data);
        camera.position.set(...issToWorld(pose.position_m));
        direction
          .set(...issToWorld(pose.target_m))
          .sub(camera.position)
          .normalize();
        yaw = Math.atan2(direction.x, -direction.z);
        pitch = Math.asin(direction.y);
        look();
      }
      const saved = props.cameraMemory?.current;
      if (
        saved &&
        saved.key === props.cameraKey &&
        saved.geometry === cameraGeometry &&
        saved.mode === configuredMode &&
        saved.reset === configuredReset
      ) {
        camera.position.set(...saved.position);
        if (controls.enabled) {
          controls.target.set(...saved.target);
          controls.update();
        } else {
          direction.set(...saved.direction).normalize();
          yaw = Math.atan2(direction.x, -direction.z);
          pitch = Math.asin(THREE.MathUtils.clamp(direction.y, -1, 1));
          look();
        }
      }
      invalidate();
    };
    const rememberCamera = () => {
      if (props.cameraMemory)
        props.cameraMemory.current = props.cameraKey
          ? {
              key: props.cameraKey,
              geometry: cameraGeometry,
              mode: configuredMode,
              reset: configuredReset,
              position: camera.position.toArray() as Vec3,
              direction: camera.getWorldDirection(new THREE.Vector3()).toArray() as Vec3,
              target: controls.target.toArray() as Vec3,
            }
          : null;
    };
    live.current = { overlay, configure, invalidate };
    const resize = () => {
      width = Math.max(1, element.clientWidth);
      height = Math.max(1, element.clientHeight);
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      overlay.setViewportHeight(height * renderer.getPixelRatio());
      invalidate();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    configure();
    overlay.setFrame(latest.current.frame, latest.current);
    controls.addEventListener('change', invalidate);
    const render = () => {
      if (!alive) return;
      if (controls.enabled) controls.update();
      if (dirty) {
        canvas.dataset.cameraPosition = camera.position
          .toArray()
          .map((n) => n.toFixed(6))
          .join(',');
        canvas.dataset.cameraDirection = camera
          .getWorldDirection(new THREE.Vector3())
          .toArray()
          .map((n) => n.toFixed(6))
          .join(',');
        canvas.dataset.sourceNdc = new THREE.Vector3(...issToWorld(props.data.conditions.source_position_m))
          .project(camera)
          .toArray()
          .map((n) => n.toFixed(6))
          .join(',');
        renderer.render(world, camera);
        canvas.dataset.drawCalls = String(renderer.info.render.calls);
        canvas.dataset.triangles = String(renderer.info.render.triangles);
        rememberCamera();
        dirty = false;
      }
      raf = requestAnimationFrame(render);
    };
    render();
    let down: { x: number; y: number; lastX: number; lastY: number; id: number } | null = null;
    const pointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      down = {
        x: event.clientX,
        y: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        id: event.pointerId,
      };
      canvas.focus({ preventScroll: true });
      if (!controls.enabled) canvas.setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent) => {
      if (!down || controls.enabled) return;
      yaw -= (event.clientX - down.lastX) * 0.004;
      pitch = THREE.MathUtils.clamp(pitch - (event.clientY - down.lastY) * 0.004, -1.35, 1.35);
      down.lastX = event.clientX;
      down.lastY = event.clientY;
      look();
    };
    const raycaster = new THREE.Raycaster();
    const source = new THREE.Vector3();
    const pointerUp = (event: PointerEvent) => {
      const start = down;
      down = null;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
      const rect = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((event.clientX - rect.left) / width) * 2 - 1,
          1 - ((event.clientY - rect.top) / height) * 2,
        ),
        camera,
      );
      let point: number | null = null,
        distance = Infinity;
      const radius = issProbeSpacing(latest.current.data) * 0.6;
      latest.current.data.sample_positions_m.forEach((position, index) => {
        const visible = (['heat', 'smoke'] as IssChannel[]).some((channel) => {
          if (!latest.current[channel]) return false;
          const state = issSampleState(
            latest.current.frame,
            index,
            channel,
            latest.current.data.conditions.ambient_temperature_c,
            latest.current.model,
          );
          return (
            state &&
            (latest.current.display === 'reference'
              ? state.truth
              : latest.current.display === 'errors'
                ? state.truth || state.predicted
                : state.predicted)
          );
        });
        if (!visible) return;
        source.set(...issToWorld(position));
        const d = raycaster.ray.distanceSqToPoint(source);
        if (
          d < radius * radius &&
          d < distance &&
          source.clone().sub(camera.position).dot(raycaster.ray.direction) > 0
        ) {
          point = index;
          distance = d;
        }
      });
      setSelected(point);
    };
    const cancelPointer = () => {
      down = null;
    };
    const keyDown = (event: KeyboardEvent) => {
      if (controls.enabled || event.altKey || event.ctrlKey || event.metaKey) return;
      const key = event.key.toLowerCase();
      const forward = ['arrowup', 'w', 'z'].includes(key) ? 1 : ['arrowdown', 's'].includes(key) ? -1 : 0;
      const side = ['arrowright', 'd'].includes(key) ? 1 : ['arrowleft', 'a', 'q'].includes(key) ? -1 : 0;
      if (!forward && !side) return;
      event.preventDefault();
      camera.getWorldDirection(direction);
      direction.y = 0;
      direction.normalize();
      right.crossVectors(direction, up).normalize();
      const next = camera.position
        .clone()
        .addScaledVector(direction, forward * 0.15)
        .addScaledVector(right, side * 0.15);
      next.x = THREE.MathUtils.clamp(next.x, 0.1, x - 0.1);
      next.z = THREE.MathUtils.clamp(next.z, -y + 0.1, -0.1);
      const blocked = props.data.scene.objects.some((object) => {
        if (object.role === 'decoration') return false;
        const [cx, cz, cy] = issToWorld(object.center_m);
        return (
          Math.abs(next.x - cx) < object.size_m[0] / 2 + 0.1 &&
          Math.abs(next.y - cz) < object.size_m[2] / 2 + 0.1 &&
          Math.abs(next.z - cy) < object.size_m[1] / 2 + 0.1
        );
      });
      if (!blocked) {
        camera.position.copy(next);
        look();
      }
    };
    const contextLost = (event: Event) => {
      event.preventDefault();
      setError('Le contexte 3D a été interrompu. Rechargez la vue.');
    };
    canvas.addEventListener('pointerdown', pointerDown);
    canvas.addEventListener('pointermove', pointerMove);
    canvas.addEventListener('pointerup', pointerUp);
    canvas.addEventListener('pointercancel', cancelPointer);
    canvas.addEventListener('keydown', keyDown);
    canvas.addEventListener('webglcontextlost', contextLost);
    return () => {
      rememberCamera();
      alive = false;
      cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      canvas.removeEventListener('pointerdown', pointerDown);
      canvas.removeEventListener('pointermove', pointerMove);
      canvas.removeEventListener('pointerup', pointerUp);
      canvas.removeEventListener('pointercancel', cancelPointer);
      canvas.removeEventListener('keydown', keyDown);
      canvas.removeEventListener('webglcontextlost', contextLost);
      overlay.dispose();
      disposeWorld(world);
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
      live.current = null;
    };
  }, [props.data, props.model, props.cameraKey, props.cameraMemory]);
  useEffect(() => {
    live.current?.overlay.setFrame(props.frame, props);
    live.current?.invalidate();
  }, [props.frame, props.display, props.heat, props.smoke]);
  useEffect(() => {
    live.current?.configure();
  }, [props.cameraMode, props.reset]);
  return (
    <div className="iss-stage">
      <div className="iss-canvas" ref={host} />
      <div className="iss-stage-label">
        <span>
          {props.display === 'reference'
            ? 'Référence · simulation FDS'
            : props.display === 'errors'
              ? 'Comparaison · erreurs ML'
              : 'Prédiction · modèle entraîné'}
        </span>
        <strong>{props.data.scene.name ?? 'Environnement spatial'}</strong>
      </div>
      <div className="iss-legend" aria-label="Légende des couches">
        {props.display === 'errors' ? (
          <>
            <span>
              <i style={{ background: HOTSPOT_COLORS.tp }} />
              Détecté
            </span>
            <span>
              <i style={{ background: HOTSPOT_COLORS.fp }} />
              Fausse alerte
            </span>
            <span>
              <i style={{ background: HOTSPOT_COLORS.fn }} />
              Manqué
            </span>
          </>
        ) : (
          <>
            <span>
              <i className="iss-heat-dot" />
              Zone chaude
            </span>
            <span>
              <i className="iss-smoke-dot" />
              Présence de fumée
            </span>
          </>
        )}
        <small>◇ Source électrique conditionnelle</small>
      </div>
      <div className="iss-camera-hint">
        {props.cameraMode === 'inside'
          ? 'Glisser pour regarder · flèches ou ZQSD pour se déplacer'
          : 'Glisser pour tourner · molette pour zoomer'}{' '}
        · cliquer pour inspecter
      </div>
      {error && (
        <div className="iss-error" role="alert">
          {error}
        </div>
      )}
      {selected !== null && (
        <div className="iss-probe" role="status">
          <button type="button" aria-label="Fermer la sonde" onClick={() => setSelected(null)}>
            ×
          </button>
          <strong>Sonde {selected + 1}</strong>
          <small>{props.data.sample_positions_m[selected].map((n) => number(n)).join(' / ')} m</small>
          {(['heat', 'smoke'] as IssChannel[]).map((channel) => {
            const state = issSampleState(
              props.frame,
              selected,
              channel,
              props.data.conditions.ambient_temperature_c,
              props.model,
            );
            return (
              <div key={channel}>
                <span>{channel === 'heat' ? 'Chaleur' : 'Fumée'}</span>
                <b>Score ML {number(state?.score, 4)}</b>
                <small>
                  FDS{' '}
                  {state
                    ? channel === 'heat'
                      ? `${number(state.value)} °C`
                      : `${state.value.toExponential(3)} kg/m³`
                    : 'indisponible'}
                </small>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

async function readJson(url: string, signal: AbortSignal) {
  const response = await fetch(url, { signal, cache: 'no-store' });
  if (response.status === 404 || !response.headers.get('content-type')?.includes('json'))
    throw new Error('L’export du modèle ISS n’est pas encore disponible.');
  if (!response.ok) throw new Error(`Lecture impossible (${response.status}).`);
  return response.json() as Promise<unknown>;
}

export default function IssPocView({
  onOpenSources,
  onBack,
  indexUrl = '/poc/iss/index.json',
}: {
  onOpenSources?: () => void;
  onBack?: () => void;
  indexUrl?: string;
}) {
  const [index, setIndex] = useState<IssIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [module, setModule] = useState('all');
  const [split, setSplit] = useState<PocSplit>('validation');
  const [caseId, setCaseId] = useState('');
  const [loaded, setLoaded] = useState<IssCase | null>(null);
  const [caseError, setCaseError] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [display, setDisplay] = useState<IssDisplay>('prediction');
  const [heat, setHeat] = useState(true),
    [smoke, setSmoke] = useState(true);
  const [cameraMode, setCameraMode] = useState<CameraMode>('inside');
  const [reset, setReset] = useState(0);
  const root = useRef<HTMLElement>(null);
  const cache = useRef(new Map<string, IssCase>());
  const cameraMemory = useRef<IssCameraSnapshot | null>(null);
  const comparisonAnchor = useRef<{ key: string; time_s: number } | null>(null);
  const [comparisonTime, setComparisonTime] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setPlaying(false);
    setIndex(null);
    setLoaded(null);
    comparisonAnchor.current = null;
    cameraMemory.current = null;
    setComparisonTime(null);
    cache.current.clear();
    void readJson(indexUrl, controller.signal)
      .then(parseIssIndex)
      .then((next) => {
        if (controller.signal.aborted) return;
        setIndex(next);
        const initial =
          next.cases.find((item) => item.id === next.default_case_id) ??
          next.cases.find((item) => item.split === 'validation') ??
          next.cases[0];
        setSplit(initial.split);
        setModule(initial.module_id);
        setCaseId(initial.id);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : 'Export indisponible.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [indexUrl, reload]);
  const modules = useMemo(() => [...new Set(index?.cases.map((item) => item.module_id) ?? [])], [index]);
  const cases = useMemo(
    () =>
      index?.cases.filter(
        (item) => item.split === split && (module === 'all' || item.module_id === module),
      ) ?? [],
    [index, split, module],
  );
  const selected = cases.find((item) => item.id === caseId) ?? cases[0];
  const quartet = useMemo(() => issVentilationQuartet(index?.cases ?? [], selected), [index, selected]);
  const groupKey = quartet.length ? issVentilationGroupKey(selected) : null;
  const data = loaded?.id === selected?.id ? loaded : null;
  const frame = data?.frames[Math.min(frameIndex, data.frames.length - 1)];
  const selectCase = (id: string) => {
    if (id === selected?.id) return;
    if (groupKey && quartet.some((entry) => entry.id === id)) {
      const time =
        comparisonAnchor.current?.key === groupKey ? comparisonAnchor.current.time_s : frame?.time_s;
      comparisonAnchor.current = time === undefined ? null : { key: groupKey, time_s: time };
    } else comparisonAnchor.current = null;
    setCaseId(id);
    setPlaying(false);
  };
  const releaseComparisonTime = () => {
    comparisonAnchor.current = null;
    setComparisonTime(null);
  };
  useEffect(() => {
    setLoaded(null);
    setPlaying(false);
    setCaseError(null);
    setFrameIndex(0);
    if (comparisonAnchor.current?.key !== groupKey) comparisonAnchor.current = null;
    const target = comparisonAnchor.current?.time_s ?? null;
    setComparisonTime(target);
    if (!selected) return;
    const controller = new AbortController();
    const apply = (next: IssCase) => {
      if (!controller.signal.aborted) {
        setLoaded(next);
        setFrameIndex(target === null ? issPeakFrame(next) : issNearestFrame(next, target));
      }
    };
    const cached = cache.current.get(selected.id);
    if (cached) apply(cached);
    else if (index)
      void fetch(issCaseUrl(selected.url), { signal: controller.signal, cache: 'no-store' })
        .then(async (response) => {
          if (!response.ok) throw new Error(`Scénario indisponible (${response.status}).`);
          return decodeIssCase(await response.arrayBuffer(), selected, index.model);
        })
        .then((next) => {
          if (controller.signal.aborted) return;
          cache.current.set(next.id, next);
          if (cache.current.size > 4) cache.current.delete(cache.current.keys().next().value as string);
          apply(next);
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted)
            setCaseError(reason instanceof Error ? reason.message : 'Scénario indisponible.');
        });
    return () => controller.abort();
  }, [selected, index, groupKey]);
  useEffect(() => {
    if (!playing || !data || !frame) return;
    const next = data.frames[frameIndex + 1];
    if (!next) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(
      () => setFrameIndex((value) => value + 1),
      Math.max(60, ((next.time_s - frame.time_s) * 1000) / speed),
    );
    return () => window.clearTimeout(timer);
  }, [playing, frameIndex, data, frame, speed]);
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void root.current?.requestFullscreen?.().catch(() => {});
  };
  return (
    <section
      className="iss-poc"
      data-iss-poc
      data-case-id={data?.id ?? ''}
      data-time-s={frame?.time_s ?? ''}
      data-display={display}
      data-ventilation-group={selected?.ventilation_group_id ?? ''}
      data-comparison-time-s={comparisonTime ?? ''}
      ref={root}
    >
      <header className="iss-header">
        <div>
          {onBack && (
            <button type="button" className="iss-icon" onClick={onBack} aria-label="Retour à la station">
              <ArrowLeft size={18} />
            </button>
          )}
          <div>
            <span className="iss-eyebrow">IGNIS / STATION</span>
            <h1>Explorer la propagation</h1>
          </div>
        </div>
        <div className="iss-header-actions">
          <span className="iss-recorded">Inférence enregistrée</span>
          {onOpenSources && (
            <button type="button" onClick={onOpenSources}>
              Sources NASA
            </button>
          )}
          <button type="button" className="iss-icon" onClick={fullscreen} aria-label="Plein écran">
            <Maximize2 size={17} />
          </button>
        </div>
      </header>
      {loading ? (
        <div className="iss-empty" role="status">
          Chargement des sorties du modèle…
        </div>
      ) : error ? (
        <div className="iss-empty" role="alert">
          <strong>{error}</strong>
          <p>La vue affichera les sorties du modèle entraîné dès leur export.</p>
          <button type="button" onClick={() => setReload((value) => value + 1)}>
            Recharger
          </button>
        </div>
      ) : (
        index && (
          <>
            <div className="iss-controls">
              <div className="iss-modules" aria-label="Environnements de la station">
                {modules.map((id) => (
                  <button
                    type="button"
                    key={id}
                    data-iss-module={id}
                    aria-pressed={module === id}
                    onClick={() => {
                      setModule(id);
                      const example = index.example_cases?.modules?.[id];
                      if (split === 'validation' && example) setCaseId(example);
                      setPlaying(false);
                    }}
                  >
                    {moduleName(id)}
                  </button>
                ))}
              </div>
              <label>
                Évaluation
                <select
                  aria-label="Partition ISS"
                  value={split}
                  onChange={(event) => setSplit(event.target.value as PocSplit)}
                >
                  {(['validation', 'test', 'train'] as PocSplit[]).map((item) => (
                    <option key={item} value={item}>
                      {ISS_SPLIT_LABELS[item]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Départ conditionnel
                <select
                  aria-label="Scénario ISS"
                  value={selected?.id ?? ''}
                  onChange={(event) => selectCase(event.target.value)}
                >
                  {cases.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.incident_type ? incident(item.incident_type) : item.id} ·{' '}
                      {item.gravity_g < 0.01 ? 'microgravité' : 'Terre'} · {item.id}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {quartet.length > 0 && (
              <div className="iss-ventilation" aria-label="Comparaison de ventilation">
                <div>
                  <strong>
                    <Wind size={14} /> Ventilation · axe {selected?.ventilation_axis?.toUpperCase()}
                  </strong>
                  <span>Même départ, mêmes équipements · caméra conservée</span>
                </div>
                <div className="iss-ventilation-states">
                  {quartet.map((entry) => (
                    <button
                      type="button"
                      key={entry.id}
                      data-iss-ventilation={entry.ventilation_state}
                      aria-pressed={selected?.id === entry.id}
                      onClick={() => selectCase(entry.id)}
                    >
                      {entry.ventilation_state === 'still'
                        ? `Sans débit · ${number(entry.airflow_m_s)} m/s`
                        : entry.ventilation_state === 'slow'
                          ? `Lent · ${number(entry.airflow_m_s)} m/s`
                          : entry.ventilation_state === 'fast'
                            ? `Rapide · ${number(entry.airflow_m_s)} m/s`
                            : `Sens inversé · ${number(entry.airflow_m_s)} m/s`}
                    </button>
                  ))}
                </div>
                <small>
                  {comparisonTime === null
                    ? 'Changer le débit conserve le temps visé, au relevé disponible le plus proche.'
                    : `Temps visé ${number(comparisonTime, 2)} s · relevé affiché ${number(frame?.time_s, 2)} s`}
                </small>
              </div>
            )}
            <div className="iss-viewbar">
              <div className="iss-segments" aria-label="Données affichées">
                {(
                  [
                    ['prediction', 'Prédiction ML'],
                    ['reference', 'Référence FDS'],
                    ['errors', 'Erreurs'],
                  ] as [IssDisplay, string][]
                ).map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    aria-pressed={display === value}
                    onClick={() => setDisplay(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="iss-layers">
                <label>
                  <input
                    type="checkbox"
                    checked={heat}
                    onChange={(event) => setHeat(event.target.checked)}
                    aria-label="Couche chaleur"
                  />
                  Chaleur
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={smoke}
                    onChange={(event) => setSmoke(event.target.checked)}
                    aria-label="Couche fumée"
                  />
                  Fumée
                </label>
              </div>
              <div className="iss-camera-controls">
                <button
                  type="button"
                  aria-pressed={cameraMode === 'inside'}
                  onClick={() => setCameraMode('inside')}
                >
                  <Eye size={15} />
                  Intérieur
                </button>
                <button
                  type="button"
                  aria-pressed={cameraMode === 'overview'}
                  onClick={() => setCameraMode('overview')}
                >
                  <Crosshair size={15} />
                  Ensemble
                </button>
                <button
                  type="button"
                  className="iss-icon"
                  aria-label="Recentrer la caméra"
                  onClick={() => setReset((value) => value + 1)}
                >
                  <RotateCcw size={15} />
                </button>
              </div>
            </div>
            {caseError ? (
              <div className="iss-empty" role="alert">
                {caseError}
              </div>
            ) : !selected ? (
              <div className="iss-empty">Aucun scénario dans cette sélection.</div>
            ) : !data || !frame ? (
              <div className="iss-empty" role="status">
                Chargement du scénario…
              </div>
            ) : (
              <>
                <IssPocViewport
                  data={data}
                  frame={frame}
                  model={index.model}
                  display={display}
                  heat={heat}
                  smoke={smoke}
                  cameraMode={cameraMode}
                  reset={reset}
                  cameraKey={groupKey ? `${index.model.weights_sha256}:${reload}:${groupKey}` : null}
                  cameraMemory={cameraMemory}
                />
                <div className="iss-timeline">
                  <button
                    type="button"
                    className="iss-play"
                    aria-label={playing ? 'Pause ISS' : 'Lire le scénario ISS'}
                    onClick={() => {
                      releaseComparisonTime();
                      if (!playing && frameIndex >= data.frames.length - 1) setFrameIndex(0);
                      setPlaying(!playing);
                    }}
                  >
                    {playing ? <Pause size={18} /> : <Play size={18} />}
                  </button>
                  <strong>
                    {number(frame.time_s, 1)}
                    <small> s</small>
                  </strong>
                  <input
                    type="range"
                    aria-label="Instant ISS"
                    min={0}
                    max={data.frames.length - 1}
                    step={1}
                    value={frameIndex}
                    onChange={(event) => {
                      releaseComparisonTime();
                      setPlaying(false);
                      setFrameIndex(Number(event.target.value));
                    }}
                  />
                  <span>{number(data.frames.at(-1)?.time_s, 0)} s</span>
                  <select
                    aria-label="Vitesse de lecture ISS"
                    value={speed}
                    onChange={(event) => setSpeed(Number(event.target.value))}
                  >
                    <option value={1}>×1</option>
                    <option value={2}>×2</option>
                    <option value={4}>×4</option>
                  </select>
                </div>
                <div className="iss-conditions">
                  <span>
                    <Wind size={14} />
                    {number(data.conditions.airflow_m_s)} m/s
                  </span>
                  <span>
                    {data.conditions.gravity_g < 0.01 ? 'Microgravité' : 'Gravité terrestre'} ·{' '}
                    {number(data.conditions.gravity_g, 4)} g
                  </span>
                  <span>
                    {incident(data.conditions.incident_type)}
                    {data.conditions.power_w !== undefined
                      ? ` · ${number(data.conditions.power_w, 0)} W`
                      : ''}
                  </span>
                  <span>{data.scene.bounds_m.map((value) => number(value, 1)).join(' × ')} m</span>
                  <span>
                    Chaud ≥ {number(data.conditions.ambient_temperature_c + index.model.heat_delta_c, 0)} °C
                  </span>
                </div>
                <div className="iss-bottom">
                  <p>
                    Propagation conditionnelle à une source électrique. Géométries d’habitats spatiaux,
                    données synthétiques FDS. Les halos représentent des classes prédites aux sondes : ni
                    probabilité de départ de feu, ni température ou densité de fumée prédite.
                  </p>
                  <details>
                    <summary>Mesures et provenance</summary>
                    <div className="iss-metrics">
                      {(['heat', 'smoke'] as IssChannel[]).map((channel) => {
                        const current = issFrameMetrics(data, frame, index.model, channel);
                        return (
                          <div key={channel}>
                            <strong>{channel === 'heat' ? 'Chaleur' : 'Fumée'}</strong>
                            <span>
                              À cet instant · IoU {percent(current.iou)} · rappel {percent(current.recall)}
                            </span>
                            <span>
                              Ce scénario (t &gt; 0) · IoU {percent(selected.metrics[channel].iou)} · rappel{' '}
                              {percent(selected.metrics[channel].recall)}
                            </span>
                            <span>
                              {ISS_SPLIT_LABELS[split]} · IoU {percent(index.metrics[split]?.[channel].iou)}
                            </span>
                            <small>
                              Seuil du score {number(index.model.score_thresholds[channel], 6)} · score non
                              calibré
                            </small>
                          </div>
                        );
                      })}
                    </div>
                    <p>
                      Fumée : suie FDS ≥ {index.model.smoke_threshold_kg_m3.toExponential()} kg/m³. Les
                      masques chaleur et fumée sont indépendants ; aucune mesure manquante n’est convertie en
                      point froid. La vue initiale montre le pic de chaleur FDS, ou le pic de suie pour un
                      scénario sans zone chaude. Les halos sont des glyphes fixes, sans déplacement
                      artificiel.
                    </p>
                    <p>
                      Modèle {index.model.name ?? index.model.id} ·{' '}
                      {index.model.device ?? 'matériel non renseigné'}
                      {index.model.training_seconds !== undefined
                        ? ` · ${number(index.model.training_seconds, 0)} s d’apprentissage`
                        : ''}
                    </p>
                    <code>
                      Poids {index.model.weights_sha256}
                      <br />
                      Données {index.model.dataset_sha256}
                    </code>
                    {index.limitations?.map((item) => (
                      <p key={item}>{item}</p>
                    ))}
                  </details>
                </div>
              </>
            )}
          </>
        )
      )}
    </section>
  );
}
