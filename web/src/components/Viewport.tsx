import { useEffect, useRef, useState } from 'react';
import { Box, Crosshair, LoaderCircle, Maximize2, RotateCcw, TriangleAlert } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { finite, toWorld, voxelPosition } from '../data';
import type { Field, Frame, Scene as LabScene, Vec3, ViewportMarker } from '../types';

interface Props {
  scene?: LabScene;
  frame?: Frame;
  field: Field;
  cutaway: boolean;
  showSensors: boolean;
  showSource?: boolean;
  slice: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  componentMarkers?: ViewportMarker[];
  selectedComponentId?: string | null;
  onSelectComponent?: (id: string | null) => void;
}

interface ViewState {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  renderer: THREE.WebGLRenderer;
  model: THREE.Group;
  overlay: THREE.Group;
  markers: THREE.Group;
  components: THREE.Group;
  selection: THREE.Group;
  fit: () => void;
  invalidate: () => void;
}

function disposeTree(root: THREE.Object3D): void {
  root.traverse((node) => {
    const mesh = node as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const material of materials) {
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose();
      material.dispose();
    }
  });
}

function clearGroup(group: THREE.Group): void {
  for (const child of [...group.children]) {
    group.remove(child);
    disposeTree(child);
  }
}

function annotationId(node: THREE.Object3D, key = 'object_id'): string | null {
  let current: THREE.Object3D | null = node;
  while (current) {
    if (typeof current.userData[key] === 'string') return current.userData[key];
    current = current.parent;
  }
  return null;
}

function fallbackGeometry(scene: LabScene, group: THREE.Group): void {
  for (const object of scene.objects.filter((item) => item.role !== 'decoration')) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(object.size_m[0], object.size_m[2], object.size_m[1]),
      new THREE.MeshStandardMaterial({
        color: object.role === 'fuel' ? '#ba805a' : '#425268',
        roughness: 0.8,
        transparent: true,
        opacity: object.role === 'wall' ? 0.16 : 0.75,
      }),
    );
    mesh.position.set(...toWorld(object.center_m));
    mesh.userData.object_id = object.id;
    mesh.name = object.name;
    group.add(mesh);
  }
}

function addMarker(group: THREE.Group, position: Vec3, color: string, radius: number): THREE.Group {
  const annotation = new THREE.Group();
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 12, 8),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.92, depthTest: false }),
  );
  marker.position.set(...toWorld(position));
  marker.renderOrder = 5;
  annotation.add(marker);
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(radius * 1.8, radius * 0.11, 6, 24),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.65, depthTest: false }),
  );
  ring.rotation.x = Math.PI / 2;
  ring.position.copy(marker.position);
  ring.renderOrder = 5;
  annotation.add(ring);
  group.add(annotation);
  return annotation;
}

function scalarColor(value: number, field: Field, maximum: number): THREE.Color {
  const color = new THREE.Color();
  if (field === 'temperature') {
    const t = Math.min(1, Math.max(0, (value - 20) / 780));
    return color.setHSL(0.6 * (1 - t), 0.9, 0.42 + t * 0.2);
  }
  if (field === 'oxygen') return color.setHSL(0.05 + Math.min(1, value / 30) * 0.5, 0.8, 0.55);
  const t = Math.min(1, value / Math.max(maximum, 1e-9));
  return color.setRGB(0.38 + t * 0.47, 0.43 + t * 0.42, 0.52 + t * 0.36);
}

function createOverlay(group: THREE.Group, frame: Frame, field: Field, slice: boolean): void {
  const count = frame.shape[0] * frame.shape[1] * frame.shape[2];
  if (!count || count > 5_000_000) return;
  const step = Math.max(1, Math.ceil(count / (field === 'airflow' ? 260 : 12_000)));
  const scalar =
    field === 'temperature'
      ? frame.temperature_c
      : field === 'oxygen'
        ? frame.oxygen_percent
        : frame.smoke_kg_m3;
  let maximum = 0;
  if (field === 'smoke' && scalar)
    for (const value of scalar) if (finite(value)) maximum = Math.max(maximum, value);
  const positions: number[] = [];
  const colors: number[] = [];
  for (let index = 0; index < count; index += step) {
    if (frame.valid_mask?.[index] === false) continue;
    const physical = frame.sample_positions_m?.[index] ?? voxelPosition(index, frame.shape, frame.bounds_m);
    if (
      slice &&
      Math.abs(physical[0] - frame.bounds_m[0] / 2) > frame.bounds_m[0] / Math.min(8, frame.shape[0])
    )
      continue;
    const position = new THREE.Vector3(...toWorld(physical));
    if (field === 'airflow') {
      const values = frame.velocity_m_s;
      const vx = values?.[index * 3];
      const vy = values?.[index * 3 + 1];
      const vz = values?.[index * 3 + 2];
      if (!finite(vx) || !finite(vy) || !finite(vz)) continue;
      const direction = new THREE.Vector3(vx, vz, -vy);
      const speed = direction.length();
      if (speed < 0.005 || !Number.isFinite(speed)) continue;
      const arrow = new THREE.ArrowHelper(
        direction.normalize(),
        position,
        Math.min(0.8, Math.max(0.07, speed * 0.7)),
        '#68e0e1',
        0.07,
        0.04,
      );
      group.add(arrow);
    } else if (scalar) {
      const value = scalar[index];
      if (!finite(value)) continue;
      if (field === 'smoke' && value < Math.max(maximum * 0.025, 1e-10)) continue;
      if (field === 'temperature' && value < 26) continue;
      positions.push(position.x, position.y, position.z);
      const color = scalarColor(value, field, maximum);
      colors.push(color.r, color.g, color.b);
    }
  }
  if (positions.length) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({
      size: field === 'smoke' ? 0.23 : 0.17,
      vertexColors: true,
      transparent: true,
      opacity: field === 'smoke' ? 0.3 : 0.68,
      depthWrite: false,
      sizeAttenuation: true,
    });
    group.add(new THREE.Points(geometry, material));
  }
}

export default function Viewport(props: Props) {
  const {
    scene,
    frame,
    field,
    cutaway,
    showSensors,
    showSource = true,
    slice,
    selectedId,
    onSelect,
    componentMarkers,
    selectedComponentId,
    onSelectComponent,
  } = props;
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<ViewState | null>(null);
  const selectRef = useRef(onSelect);
  const sceneRef = useRef(scene);
  const componentsRef = useRef(componentMarkers);
  const componentSelectRef = useRef(onSelectComponent);
  const [ready, setReady] = useState(false);
  const [assetStatus, setAssetStatus] = useState<'loading' | 'loaded' | 'fallback' | 'empty'>('empty');
  const [renderError, setRenderError] = useState<string | null>(null);
  selectRef.current = onSelect;
  sceneRef.current = scene;
  componentsRef.current = componentMarkers;
  componentSelectRef.current = onSelectComponent;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
      });
    } catch {
      setRenderError(
        'WebGL est indisponible sur ce navigateur. Les paramètres, mesures et exports restent accessibles.',
      );
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.setClearColor('#101720', 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    element.appendChild(renderer.domElement);
    renderer.domElement.setAttribute(
      'aria-label',
      'Environnement 3D interactif. Faites glisser pour tourner, utilisez la molette pour zoomer.',
    );
    renderer.domElement.setAttribute('role', 'img');
    renderer.domElement.tabIndex = 0;
    const world = new THREE.Scene();
    world.add(new THREE.HemisphereLight('#e3f4ff', '#63738d', 2.8));
    const key = new THREE.DirectionalLight('#fff1db', 3.8);
    key.position.set(3, 9, 5);
    world.add(key);
    const fill = new THREE.DirectionalLight('#7acdda', 2.4);
    fill.position.set(-4, 4, -7);
    world.add(fill);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 150);
    const controls = new OrbitControls(camera, renderer.domElement);
    let needsRender = true;
    const invalidate = () => {
      needsRender = true;
    };
    controls.addEventListener('change', invalidate);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 1;
    controls.maxDistance = 34;
    controls.maxPolarAngle = Math.PI * 0.88;
    const model = new THREE.Group();
    const overlay = new THREE.Group();
    const markers = new THREE.Group();
    const components = new THREE.Group();
    const selection = new THREE.Group();
    world.add(model, overlay, markers, components, selection);
    const grid = new THREE.GridHelper(32, 64, '#22313e', '#1a2835');
    grid.position.set(2.8, -0.04, -4);
    world.add(grid);
    const fit = () => {
      const bounds = sceneRef.current?.bounds_m ?? [5.6, 8, 3.2];
      const scale = (Math.max(...bounds) / 8) * Math.max(1, 1.3 / camera.aspect);
      controls.target.set(bounds[0] / 2, bounds[2] * 0.42, -bounds[1] / 2);
      camera.position.set(
        bounds[0] / 2 + 8.1 * scale,
        bounds[2] / 2 + 6.3 * scale,
        -bounds[1] / 2 + 10.8 * scale,
      );
      controls.update();
    };
    fit();
    state.current = {
      scene: world,
      camera,
      controls,
      renderer,
      model,
      overlay,
      markers,
      components,
      selection,
      fit,
      invalidate,
    };
    const observer = new ResizeObserver(() => {
      const width = element.clientWidth;
      const height = element.clientHeight;
      if (!width || !height) return;
      const wasNarrow = camera.aspect < 1.3;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      if (wasNarrow !== camera.aspect < 1.3) fit();
      invalidate();
    });
    observer.observe(element);
    const raycaster = new THREE.Raycaster();
    let pointerStart = { x: 0, y: 0 };
    const down = (event: PointerEvent) => {
      pointerStart = { x: event.clientX, y: event.clientY };
    };
    const up = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 6) return;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((event.clientX - rect.left) / rect.width) * 2 - 1,
          (-(event.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      const markerHits = raycaster.intersectObject(components, true);
      for (const hit of markerHits) {
        const id = annotationId(hit.object, 'component_id');
        if (id && componentSelectRef.current) {
          componentSelectRef.current(id);
          return;
        }
      }
      const hits = raycaster.intersectObject(model, true);
      let selected: string | null = null;
      for (const hit of hits) {
        if (!hit.object.visible) continue;
        const id =
          annotationId(hit.object) ??
          (sceneRef.current?.objects.some((object) => object.id === hit.object.name)
            ? hit.object.name
            : null);
        if (id) {
          selected = id;
          break;
        }
      }
      const component = componentsRef.current?.find((item) => item.object_id === selected);
      componentSelectRef.current?.(component?.id ?? null);
      selectRef.current(selected);
    };
    renderer.domElement.addEventListener('pointerdown', down);
    renderer.domElement.addEventListener('pointerup', up);
    let animation = 0;
    let previous = 0;
    const animate = (time: number) => {
      animation = requestAnimationFrame(animate);
      if (time - previous < 1000 / 40 || document.hidden) return;
      previous = time;
      controls.update();
      if (needsRender) {
        renderer.render(world, camera);
        needsRender = false;
      }
    };
    animation = requestAnimationFrame(animate);
    setReady(true);
    return () => {
      setReady(false);
      cancelAnimationFrame(animation);
      observer.disconnect();
      renderer.domElement.removeEventListener('pointerdown', down);
      renderer.domElement.removeEventListener('pointerup', up);
      controls.removeEventListener('change', invalidate);
      controls.dispose();
      disposeTree(world);
      renderer.dispose();
      element.removeChild(renderer.domElement);
      state.current = null;
    };
  }, []);

  useEffect(() => {
    const view = state.current;
    if (!view || !ready) return;
    clearGroup(view.model);
    clearGroup(view.selection);
    view.invalidate();
    if (!scene) {
      setAssetStatus('empty');
      return;
    }
    let cancelled = false;
    setAssetStatus('loading');
    view.fit();
    const loader = new GLTFLoader();
    loader.load(
      scene.asset_url,
      (gltf) => {
        if (cancelled) {
          disposeTree(gltf.scene);
          return;
        }
        view.model.add(gltf.scene);
        view.invalidate();
        setAssetStatus('loaded');
      },
      undefined,
      () => {
        if (cancelled) return;
        fallbackGeometry(scene, view.model);
        view.invalidate();
        setAssetStatus('fallback');
      },
    );
    return () => {
      cancelled = true;
      clearGroup(view.model);
    };
  }, [scene, ready]);

  useEffect(() => {
    state.current?.model.traverse((object) => {
      if (object.userData.cutaway === true) object.visible = !cutaway;
    });
    state.current?.invalidate();
  }, [cutaway, assetStatus]);

  useEffect(() => {
    const group = state.current?.markers;
    if (!group) return;
    clearGroup(group);
    state.current?.invalidate();
    if (!scene || !showSensors) return;
    for (const sensor of scene.sensors) addMarker(group, sensor.position_m, '#75e2d9', 0.045);
    if (showSource) addMarker(group, scene.source_position_m, '#ffaf6a', 0.075);
  }, [scene, showSensors, showSource, ready]);

  useEffect(() => {
    const view = state.current;
    if (!view) return;
    clearGroup(view.components);
    for (const component of componentMarkers ?? []) {
      if (!component.position_m.every(finite)) continue;
      const selected = component.id === selectedComponentId;
      const marker = addMarker(
        view.components,
        component.position_m,
        component.color ?? '#7d8898',
        selected ? 0.085 : 0.06,
      );
      marker.userData.component_id = component.id;
      marker.name = component.name;
      if (selected) {
        const outline = new THREE.Mesh(
          new THREE.SphereGeometry(0.105, 16, 10),
          new THREE.MeshBasicMaterial({
            color: '#dae8f2',
            wireframe: true,
            transparent: true,
            opacity: 0.4,
            depthTest: false,
          }),
        );
        outline.position.set(...toWorld(component.position_m));
        outline.renderOrder = 6;
        marker.add(outline);
      }
    }
    view.invalidate();
  }, [componentMarkers, selectedComponentId, scene, ready]);

  useEffect(() => {
    const group = state.current?.overlay;
    if (!group) return;
    clearGroup(group);
    if (frame && field !== 'scene') createOverlay(group, frame, field, slice);
    state.current?.invalidate();
  }, [frame, field, slice, ready]);

  useEffect(() => {
    const view = state.current;
    if (!view) return;
    clearGroup(view.selection);
    view.invalidate();
    if (!selectedId) return;
    const box = new THREE.Box3();
    view.model.updateMatrixWorld(true);
    view.model.traverse((object) => {
      if (
        (object.userData.object_id === selectedId || object.name === selectedId) &&
        object instanceof THREE.Mesh
      )
        box.expandByObject(object);
    });
    if (!box.isEmpty()) view.selection.add(new THREE.Box3Helper(box, '#ffb66d'));
  }, [selectedId, assetStatus, ready]);

  const fullscreen = () => {
    void host.current?.parentElement?.requestFullscreen?.();
  };
  return (
    <div className="viewport-wrap">
      <div ref={host} className="three-host" />
      <div className="viewport-topline">
        <div className="viewport-ident">
          <span className="live-dot" />
          <span>{scene ? 'ENVIRONNEMENT 3D' : 'EN ATTENTE DU CATALOGUE'}</span>
          {frame && field !== 'scene' && (
            <span className="frame-timestamp">
              CHAMP À {frame.time_s.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} s
            </span>
          )}
        </div>
        <div className="viewport-actions">
          <button
            className="icon-button"
            onClick={() => state.current?.fit()}
            title="Recentrer la caméra"
            aria-label="Recentrer la caméra"
          >
            <RotateCcw size={15} />
          </button>
          <button
            className="icon-button"
            onClick={fullscreen}
            title="Plein écran"
            aria-label="Afficher la scène en plein écran"
          >
            <Maximize2 size={15} />
          </button>
        </div>
      </div>
      {assetStatus === 'loading' && (
        <div className="viewport-loading">
          <LoaderCircle className="spin" size={25} />
          <span>Chargement du compartiment…</span>
        </div>
      )}
      {assetStatus === 'empty' && !renderError && (
        <div className="viewport-empty">
          <Box size={38} strokeWidth={1} />
          <strong>Votre laboratoire attend sa scène</strong>
          <span>Le catalogue sera chargé dès que le service sera disponible.</span>
        </div>
      )}
      {renderError && (
        <div className="viewport-empty">
          <TriangleAlert size={32} />
          <strong>Rendu 3D indisponible</strong>
          <span>{renderError}</span>
        </div>
      )}
      {assetStatus === 'fallback' && (
        <div className="asset-warning">
          <TriangleAlert size={14} /> GLB indisponible · proxy géométrique affiché
        </div>
      )}
      <div className="viewport-bottomline">
        <span>
          <Crosshair size={13} /> Glisser pour explorer · molette pour zoomer · clic pour inspecter
        </span>
        <div className="axis-key">
          <i className="axis-x" />X <i className="axis-y" />Y <i className="axis-z" />Z
        </div>
      </div>
    </div>
  );
}
