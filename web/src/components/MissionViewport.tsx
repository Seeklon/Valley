import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { finite, toWorld } from '../data';
import {
  missionBracket,
  missionGridAxes,
  missionPosition,
  missionSampleCount,
  missionSampleIndices,
  missionScalar,
  missionScales,
  missionVelocity,
} from '../mission-rendering';
import type { MissionBracket, MissionCamera, MissionLayer, MissionScales } from '../mission-rendering';
import type { Frame, Scene, ViewportMarker } from '../types';

export type { MissionCamera, MissionLayer } from '../mission-rendering';

interface Props {
  scene?: Scene;
  frames: Frame[];
  time: number;
  cameraMode: MissionCamera;
  layer: MissionLayer;
  opacity: number;
  cutaway: boolean;
  markers?: ViewportMarker[];
  selectedComponentId?: string | null;
  onSelectComponent?: (id: string | null) => void;
  resetToken?: number;
}

interface VolumeField {
  group: THREE.Group;
  frame: Frame;
  indices: number[];
  material: THREE.ShaderMaterial;
  mesh: THREE.Mesh;
  values: THREE.InstancedBufferAttribute;
  mask: THREE.Data3DTexture;
  maskBytes: Uint8Array;
  axes: THREE.DataTexture[];
  arrows: THREE.LineSegments;
  arrowPositions: THREE.BufferAttribute;
  arrowColors: THREE.BufferAttribute;
}

interface ViewState {
  world: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  model: THREE.Group;
  components: THREE.Group;
  grid: THREE.GridHelper;
  field: VolumeField | null;
  configureCamera: () => void;
  invalidate: () => void;
}

// These splats interpolate sampled fields visually. They add no particle transport,
// buoyancy, flame or optical-extinction model to the recorded solver result.
const VOLUME_VERTEX = `
  attribute vec3 center;
  attribute vec3 sampleValue;
  attribute float radius;
  varying vec2 vUv;
  varying vec3 vValue;
  varying vec3 vWorld;
  void main() {
    vUv = position.xy;
    vValue = sampleValue;
    vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
    vec3 up = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
    vWorld = center + (right * position.x + up * position.y) * radius;
    gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
  }
`;

const VOLUME_FRAGMENT = `
  precision highp sampler3D;
  uniform float opacity;
  uniform int layer;
  uniform vec3 bounds;
  uniform sampler3D validVolume;
  uniform sampler2D axisX;
  uniform sampler2D axisY;
  uniform sampler2D axisZ;
  uniform bool useVolumeMask;
  varying vec2 vUv;
  varying vec3 vValue;
  varying vec3 vWorld;

  int nearestCell(sampler2D axis, float coordinate) {
    int count = textureSize(axis, 0).x;
    int low = 0;
    int high = count - 1;
    for (int step = 0; step < 20; step++) {
      if (low >= high) break;
      int middle = (low + high) / 2;
      float boundary = 0.5 * (texelFetch(axis, ivec2(middle, 0), 0).r +
                              texelFetch(axis, ivec2(middle + 1, 0), 0).r);
      if (coordinate > boundary) low = middle + 1;
      else high = middle;
    }
    return low;
  }

  vec3 temperatureColor(float t) {
    vec3 cold = vec3(0.141, 0.388, 0.639);
    vec3 mild = vec3(0.224, 0.722, 0.745);
    vec3 warm = vec3(0.914, 0.847, 0.412);
    vec3 hot = vec3(0.945, 0.549, 0.271);
    vec3 peak = vec3(0.902, 0.251, 0.212);
    if (t < 0.25) return mix(cold, mild, t * 4.0);
    if (t < 0.5) return mix(mild, warm, (t - 0.25) * 4.0);
    if (t < 0.75) return mix(warm, hot, (t - 0.5) * 4.0);
    return mix(hot, peak, (t - 0.75) * 4.0);
  }

  void main() {
    if (vValue.z < 0.5) discard;
    float r2 = dot(vUv, vUv);
    if (r2 >= 1.0) discard;
    vec3 physical = vec3(vWorld.x, -vWorld.z, vWorld.y);
    if (any(lessThan(physical, vec3(0.0))) || any(greaterThan(physical, bounds))) discard;
    if (useVolumeMask) {
      ivec3 cell = ivec3(nearestCell(axisX, physical.x), nearestCell(axisY, physical.y),
                         nearestCell(axisZ, physical.z));
      if (texelFetch(validVolume, cell, 0).r < 0.5) discard;
    }
    float gaussian = exp(-3.5 * r2) * (1.0 - smoothstep(0.72, 1.0, r2));
    float density = max(0.0, vValue.x);
    float temperature = clamp(vValue.y, 0.0, 1.0);
    float strength = layer == 1 ? 0.04 + 0.52 * sqrt(temperature) : 2.5 * density;
    float alpha = 1.0 - exp(-strength * opacity * gaussian);
    if (alpha < 0.001) discard;
    vec3 color = layer == 0 ? mix(vec3(0.60, 0.65, 0.67), vec3(0.86, 0.89, 0.89), density * 0.35)
                            : temperatureColor(temperature);
    // Color is an analytical overlay, deliberately independent of scene lighting.
    gl_FragColor = vec4(color, min(alpha, 0.84));
  }
`;

function disposeTree(root: THREE.Object3D): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    for (const material of Array.isArray(mesh.material)
      ? mesh.material
      : mesh.material
        ? [mesh.material]
        : []) {
      materials.add(material);
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
    }
  });
  textures.forEach((texture) => texture.dispose());
  materials.forEach((material) => material.dispose());
  geometries.forEach((geometry) => geometry.dispose());
}

function clearGroup(group: THREE.Group): void {
  for (const child of [...group.children]) {
    group.remove(child);
    disposeTree(child);
  }
}

function disposeField(view: ViewState): void {
  if (!view.field) return;
  view.world.remove(view.field.group);
  disposeTree(view.field.group);
  view.field.mask.dispose();
  view.field.axes.forEach((axis) => axis.dispose());
  view.field = null;
}

function makeAxis(values: number[]): THREE.DataTexture {
  const texture = new THREE.DataTexture(
    new Float32Array(values),
    values.length,
    1,
    THREE.RedFormat,
    THREE.FloatType,
  );
  texture.minFilter = THREE.NearestFilter;
  texture.magFilter = THREE.NearestFilter;
  texture.needsUpdate = true;
  return texture;
}

function buildField(frame: Frame): VolumeField | null {
  const indices = missionSampleIndices(frame);
  if (!indices.length) return null;
  const gridAxes = missionGridAxes(frame);
  // A rectilinear mask is only meaningful where the exported positions really form one.
  // Unstructured samples retain their exact positions and per-sample validity instead.
  const axes = (gridAxes ?? [[0], [0], [0]]).map(makeAxis);
  const [nx, ny, nz] = gridAxes ? frame.shape : [1, 1, 1];
  const maskBytes = new Uint8Array(nx * ny * nz);
  const mask = new THREE.Data3DTexture(maskBytes, nx, ny, nz);
  mask.format = THREE.RedFormat;
  mask.type = THREE.UnsignedByteType;
  mask.minFilter = THREE.NearestFilter;
  mask.magFilter = THREE.NearestFilter;
  mask.unpackAlignment = 1;
  mask.needsUpdate = true;

  const centers = new Float32Array(indices.length * 3);
  const radii = new Float32Array(indices.length);
  const defaultSpacing = frame.bounds_m.map((bound, axis) => bound / frame.shape[axis]);
  indices.forEach((index, slot) => {
    const position = missionPosition(frame, index);
    if (position) centers.set(toWorld(position), slot * 3);
    const coordinates = [
      Math.floor(index / (frame.shape[1] * frame.shape[2])),
      Math.floor(index / frame.shape[2]) % frame.shape[1],
      index % frame.shape[2],
    ];
    const spacing = defaultSpacing.map((fallback, axis) => {
      const points = gridAxes?.[axis];
      const coordinate = coordinates[axis];
      if (!points || points.length < 2) return fallback;
      return Math.max(
        coordinate > 0 ? points[coordinate] - points[coordinate - 1] : 0,
        coordinate + 1 < points.length ? points[coordinate + 1] - points[coordinate] : 0,
      );
    });
    radii[slot] = Math.hypot(...spacing) * 0.86;
  });

  const geometry = new THREE.InstancedBufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0], 3),
  );
  geometry.setIndex([0, 1, 2, 0, 2, 3]);
  geometry.setAttribute('center', new THREE.InstancedBufferAttribute(centers, 3));
  geometry.setAttribute('radius', new THREE.InstancedBufferAttribute(radii, 1));
  const values = new THREE.InstancedBufferAttribute(new Float32Array(indices.length * 3), 3);
  values.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute('sampleValue', values);
  geometry.instanceCount = indices.length;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      opacity: { value: 0.8 },
      layer: { value: 0 },
      bounds: { value: new THREE.Vector3(...frame.bounds_m) },
      validVolume: { value: mask },
      axisX: { value: axes[0] },
      axisY: { value: axes[1] },
      axisZ: { value: axes[2] },
      useVolumeMask: { value: gridAxes !== null },
    },
    vertexShader: VOLUME_VERTEX,
    fragmentShader: VOLUME_FRAGMENT,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false;
  mesh.renderOrder = 3;

  const arrowGeometry = new THREE.BufferGeometry();
  const arrowPositions = new THREE.BufferAttribute(new Float32Array(240 * 18), 3);
  const arrowColors = new THREE.BufferAttribute(new Float32Array(240 * 18), 3);
  arrowPositions.setUsage(THREE.DynamicDrawUsage);
  arrowColors.setUsage(THREE.DynamicDrawUsage);
  arrowGeometry.setAttribute('position', arrowPositions);
  arrowGeometry.setAttribute('color', arrowColors);
  arrowGeometry.setDrawRange(0, 0);
  const arrows = new THREE.LineSegments(
    arrowGeometry,
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false }),
  );
  arrows.frustumCulled = false;
  arrows.renderOrder = 4;
  const group = new THREE.Group();
  group.add(mesh, arrows);
  return {
    group,
    frame,
    indices,
    material,
    mesh,
    values,
    mask,
    maskBytes,
    axes,
    arrows,
    arrowPositions,
    arrowColors,
  };
}

function fieldValidity(bracket: MissionBracket, index: number, layer: MissionLayer): boolean {
  if (!missionPosition(bracket.from, index)) return false;
  if (layer === 'airflow') return missionVelocity(bracket, index) !== null;
  const smoke = missionScalar(bracket, index, 'smoke_kg_m3');
  const temperature = missionScalar(bracket, index, 'temperature_c');
  if (layer === 'temperature') return temperature !== null;
  if (layer === 'thermal-smoke') return smoke !== null && smoke >= 0 && temperature !== null;
  return smoke !== null && smoke >= 0;
}

function updateField(
  field: VolumeField,
  bracket: MissionBracket,
  layer: MissionLayer,
  scales: MissionScales,
  opacity: number,
): number {
  field.group.visible = layer !== 'scene' && bracket.compatible;
  field.mesh.visible = layer !== 'airflow';
  field.arrows.visible = layer === 'airflow';
  field.material.uniforms.layer.value = layer === 'temperature' ? 1 : layer === 'thermal-smoke' ? 2 : 0;
  field.material.uniforms.opacity.value = Math.max(0, Math.min(1, opacity));
  (field.arrows.material as THREE.LineBasicMaterial).opacity = Math.max(0, Math.min(1, opacity));
  if (!field.group.visible) return 0;
  const { from } = bracket;
  let validCount = 0;
  const valid = new Uint8Array(missionSampleCount(from));
  for (let index = 0; index < valid.length; index++) {
    valid[index] = fieldValidity(bracket, index, layer) ? 255 : 0;
    if (valid[index]) validCount++;
    if (field.maskBytes.length > 1) {
      // FDS is z-fast; WebGL's 3D texture is x-fast. Preserve that distinction.
      const x = Math.floor(index / (from.shape[1] * from.shape[2]));
      const y = Math.floor(index / from.shape[2]) % from.shape[1];
      const z = index % from.shape[2];
      field.maskBytes[x + y * from.shape[0] + z * from.shape[0] * from.shape[1]] = valid[index];
    } else field.maskBytes[0] = valid[index];
  }
  field.mask.needsUpdate = true;

  field.indices.forEach((index, slot) => {
    const smoke = missionScalar(bracket, index, 'smoke_kg_m3');
    const temperature = missionScalar(bracket, index, 'temperature_c');
    field.values.setXYZ(
      slot,
      smoke === null ? 0 : Math.min(1, Math.max(0, smoke / scales.smoke.max)),
      temperature === null
        ? 0
        : Math.min(
            1,
            Math.max(
              0,
              (temperature - scales.temperature.min) / (scales.temperature.max - scales.temperature.min),
            ),
          ),
      valid[index] ? 1 : 0,
    );
  });
  field.values.needsUpdate = true;

  if (layer === 'airflow') {
    let vertices = 0;
    const arrowIndices = missionSampleIndices(from, 240);
    const side = new THREE.Vector3();
    const tip = new THREE.Vector3();
    const tail = new THREE.Vector3();
    const direction = new THREE.Vector3();
    const normal = new THREE.Vector3(0, 1, 0);
    for (const index of arrowIndices) {
      if (!valid[index]) continue;
      const position = missionPosition(from, index);
      const velocity = missionVelocity(bracket, index);
      if (!position || !velocity) continue;
      const speed = Math.hypot(...velocity);
      if (speed < 1e-6) continue;
      tail.set(...toWorld(position));
      direction.set(...toWorld(velocity)).normalize();
      const length = 0.06 + Math.min(1, speed / scales.airflow.max) * 0.4;
      tip.copy(tail).addScaledVector(direction, length);
      side.crossVectors(direction, normal);
      if (side.lengthSq() < 1e-6) side.set(1, 0, 0);
      side.normalize().multiplyScalar(length * 0.15);
      const wing = tip.clone().addScaledVector(direction, -length * 0.3);
      const points = [tail, tip, tip, wing.clone().add(side), tip, wing.clone().sub(side)];
      for (const point of points) {
        field.arrowPositions.setXYZ(vertices, point.x, point.y, point.z);
        const strength = Math.min(1, speed / scales.airflow.max);
        field.arrowColors.setXYZ(vertices, 0.3 + strength * 0.45, 0.65 + strength * 0.3, 0.8);
        vertices++;
      }
    }
    field.arrows.geometry.setDrawRange(0, vertices);
    field.arrowPositions.needsUpdate = true;
    field.arrowColors.needsUpdate = true;
  }
  return validCount;
}

function annotation(node: THREE.Object3D, key: string): string | null {
  let current: THREE.Object3D | null = node;
  while (current) {
    if (typeof current.userData[key] === 'string') return current.userData[key];
    current = current.parent;
  }
  return null;
}

function addFallback(scene: Scene, parent: THREE.Group): void {
  for (const object of scene.objects.filter((object) => object.role !== 'decoration')) {
    const wall = object.role === 'wall';
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(object.size_m[0], object.size_m[2], object.size_m[1]),
      new THREE.MeshStandardMaterial({
        color: wall ? '#6e858b' : '#84969b',
        roughness: 0.85,
        transparent: wall,
        opacity: wall ? 0.13 : 1,
      }),
    );
    mesh.position.set(...toWorld(object.center_m));
    mesh.userData.object_id = object.id;
    mesh.userData.cutaway = wall && ['ceiling', 'wall_entry', 'wall_starboard'].includes(object.id);
    parent.add(mesh);
  }
}

function completePovShell(root: THREE.Group, scene: Scene): void {
  if (scene.id !== 'soyuz') return;
  // The authored asset contains a 180° presentation cutaway. Reuse its own
  // skins/ribs for the interior view; this visual closure changes no FDS proxy.
  const completion = new THREE.Group();
  completion.name = 'mission_pov_visual_shell';
  completion.userData.mission_pov_only = true;
  completion.position.set(scene.bounds_m[0], 0, -scene.bounds_m[1]);
  completion.rotation.y = Math.PI;
  root.updateMatrixWorld(true);
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    if (
      ![
        'exterior_pressure_shell',
        'interior_liner',
        'capsule_circumferential_frame',
        'quilted_liner_panel',
        'capsule_vertical_conduit',
      ].some((name) => object.name === name || object.name.startsWith(`${name}.`))
    )
      return;
    const copy = object.clone();
    copy.matrix.copy(object.matrixWorld);
    copy.matrix.decompose(copy.position, copy.quaternion, copy.scale);
    completion.add(copy);
  });
  root.add(completion);
}

function setPovPresentation(model: THREE.Group, mode: MissionCamera): void {
  model.traverse((object) => {
    if (object.userData.mission_pov_only) object.visible = mode === 'pov';
    // Engraved labels belong to the exterior-facing experimental markers. Their
    // reversed backs obscure the crew view; their actual instruments stay visible.
    if (object.name.startsWith('sensor_label')) object.visible = mode !== 'pov';
  });
}

export default function MissionViewport(props: Props) {
  const {
    scene,
    frames,
    time,
    cameraMode,
    layer,
    opacity,
    cutaway,
    markers,
    selectedComponentId,
    resetToken,
  } = props;
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<ViewState | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const [ready, setReady] = useState(false);
  const [assetState, setAssetState] = useState<'empty' | 'loading' | 'loaded' | 'fallback'>('empty');
  const [error, setError] = useState<string | null>(null);
  const [fieldStatus, setFieldStatus] = useState<'available' | 'empty' | 'incompatible'>('empty');
  const scales = useMemo(() => missionScales(frames), [frames]);
  const bracket = useMemo(() => missionBracket(frames, time), [frames, time]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance',
      });
    } catch {
      setError('Ce navigateur ne peut pas ouvrir la vue 3D. Activez WebGL ou utilisez un autre navigateur.');
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    renderer.setClearColor('#080e14');
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.debug.onShaderError = () => {
      setError('Le navigateur ne peut pas afficher ce champ 3D. Essayez un navigateur avec WebGL 2.');
      console.error('IGNIS: mission field shader compilation failed.');
    };
    const canvas = renderer.domElement;
    canvas.tabIndex = 0;
    canvas.setAttribute(
      'aria-label',
      'Vue 3D du compartiment. Glisser pour regarder, flèches ou ZQSD pour se déplacer en vue équipage.',
    );
    canvas.setAttribute('role', 'img');
    canvas.style.touchAction = 'none';
    element.appendChild(canvas);
    const world = new THREE.Scene();
    world.add(new THREE.HemisphereLight('#d8e4ec', '#3c4e5d', 2.25));
    const key = new THREE.DirectionalLight('#ffeed6', 3.3);
    key.position.set(2, 7, 5);
    key.castShadow = true;
    key.shadow.mapSize.set(1536, 1536);
    key.shadow.camera.left = -8;
    key.shadow.camera.right = 8;
    key.shadow.camera.top = 8;
    key.shadow.camera.bottom = -8;
    key.shadow.normalBias = 0.025;
    world.add(key);
    const fill = new THREE.DirectionalLight('#86b4d0', 1.5);
    fill.position.set(-4, 3, -4);
    world.add(fill);
    const interior = new THREE.PointLight('#cfe8e4', 6, 12, 1.2);
    interior.position.set(1.5, 2.2, -1.6);
    world.add(interior);

    const camera = new THREE.PerspectiveCamera(72, 1, 0.025, 100);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.minDistance = 0.5;
    const model = new THREE.Group();
    const components = new THREE.Group();
    const grid = new THREE.GridHelper(30, 60, '#1e2d38', '#101e29');
    grid.position.y = -0.17;
    world.add(model, components, grid);
    let dirty = true;
    const invalidate = () => {
      dirty = true;
    };
    const look = new THREE.Euler(0, 0, 0, 'YXZ');
    const keys = new Set<string>();
    const configureCamera = () => {
      const current = latest.current;
      const bounds = current.scene?.bounds_m ?? [3, 3, 2.6];
      const [x, y, z] = bounds;
      const span = Math.max(...bounds);
      setPovPresentation(model, current.cameraMode);
      camera.up.set(0, 1, 0);
      grid.visible = current.cameraMode !== 'pov';
      controls.enabled = current.cameraMode !== 'pov';
      controls.enableRotate = current.cameraMode === 'orbit';
      controls.mouseButtons.LEFT = current.cameraMode === 'top' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
      controls.touches.ONE = current.cameraMode === 'top' ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
      controls.maxDistance = span * 5;
      controls.maxPolarAngle = Math.PI * 0.92;
      camera.fov = current.cameraMode === 'pov' ? 80 : 42;
      controls.target.set(x / 2, z * 0.45, -y / 2);
      if (current.cameraMode === 'pov') {
        if (current.scene?.id === 'soyuz') {
          camera.position.set(...toWorld([1.12, 2.12, 1.48]));
          camera.lookAt(...toWorld([1.5, 0.55, 1.14]));
        } else {
          camera.position.set(...toWorld([x * 0.5, y * 0.17, Math.min(1.65, z * 0.58)]));
          camera.lookAt(...toWorld([x * 0.5, y * 0.7, z * 0.47]));
        }
        look.setFromQuaternion(camera.quaternion, 'YXZ');
      } else if (current.cameraMode === 'top') {
        camera.position.set(x / 2, z + span * 1.3, -y / 2 + 0.001);
        camera.up.set(0, 0, -1);
        camera.lookAt(controls.target);
      } else {
        const fit = Math.max(1, 1.3 / camera.aspect);
        camera.position.set(
          x / 2 + span * 0.95 * fit,
          z * 0.5 + span * 0.95 * fit,
          -y / 2 + span * 1.35 * fit,
        );
        camera.lookAt(controls.target);
      }
      camera.updateProjectionMatrix();
      if (controls.enabled) controls.update();
      keys.clear();
      invalidate();
    };
    state.current = {
      world,
      camera,
      renderer,
      controls,
      model,
      components,
      grid,
      field: null,
      configureCamera,
      invalidate,
    };
    configureCamera();
    controls.addEventListener('change', invalidate);
    const observer = new ResizeObserver(() => {
      if (!element.clientWidth || !element.clientHeight) return;
      renderer.setSize(element.clientWidth, element.clientHeight);
      camera.aspect = element.clientWidth / element.clientHeight;
      camera.updateProjectionMatrix();
      invalidate();
    });
    observer.observe(element);

    const raycaster = new THREE.Raycaster();
    let pointer: { id: number; x: number; y: number; lastX: number; lastY: number } | null = null;
    const down = (event: PointerEvent) => {
      canvas.focus({ preventScroll: true });
      pointer = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
      };
      if (latest.current.cameraMode === 'pov') canvas.setPointerCapture(event.pointerId);
    };
    const move = (event: PointerEvent) => {
      if (!pointer || pointer.id !== event.pointerId || latest.current.cameraMode !== 'pov') return;
      look.y -= (event.clientX - pointer.lastX) * 0.004;
      look.x = THREE.MathUtils.clamp(
        look.x - (event.clientY - pointer.lastY) * 0.004,
        -Math.PI * 0.47,
        Math.PI * 0.47,
      );
      camera.quaternion.setFromEuler(look);
      pointer.lastX = event.clientX;
      pointer.lastY = event.clientY;
      invalidate();
    };
    const up = (event: PointerEvent) => {
      const started = pointer;
      pointer = null;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (!started || Math.hypot(event.clientX - started.x, event.clientY - started.y) > 6) return;
      const rect = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((event.clientX - rect.left) / rect.width) * 2 - 1,
          -((event.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      let selected: string | null = null;
      for (const hit of raycaster.intersectObject(components, true)) {
        selected = annotation(hit.object, 'component_id');
        if (selected) break;
      }
      if (!selected) {
        for (const hit of raycaster.intersectObject(model, true)) {
          if (!hit.object.visible) continue;
          const objectId = annotation(hit.object, 'object_id');
          selected = latest.current.markers?.find((marker) => marker.object_id === objectId)?.id ?? null;
          if (selected) break;
        }
      }
      latest.current.onSelectComponent?.(selected);
    };
    const cancel = () => {
      pointer = null;
      keys.clear();
    };
    const constrain = () => {
      const current = latest.current.scene;
      const bounds = current?.bounds_m ?? [3, 3, 2.6];
      camera.position.x = THREE.MathUtils.clamp(camera.position.x, 0.12, bounds[0] - 0.12);
      camera.position.y = THREE.MathUtils.clamp(camera.position.y, 0.25, bounds[2] - 0.12);
      camera.position.z = THREE.MathUtils.clamp(camera.position.z, -bounds[1] + 0.12, -0.12);
      if (current?.id === 'soyuz') {
        const x = camera.position.x - 1.5;
        const z = camera.position.z + 1.5;
        const radius = Math.max(0.58, 1.28 - Math.max(0, camera.position.y - 1.2) * 0.47);
        const distance = Math.hypot(x, z);
        if (distance > radius) {
          camera.position.x = 1.5 + (x / distance) * radius;
          camera.position.z = -1.5 + (z / distance) * radius;
        }
      }
    };
    const wheel = (event: WheelEvent) => {
      if (latest.current.cameraMode !== 'pov') return;
      event.preventDefault();
      camera.translateZ(Math.sign(event.deltaY) * 0.12);
      constrain();
      invalidate();
    };
    const keydown = (event: KeyboardEvent) => {
      if (latest.current.cameraMode !== 'pov') return;
      if (
        [
          'KeyW',
          'KeyA',
          'KeyS',
          'KeyD',
          'KeyQ',
          'KeyZ',
          'ArrowUp',
          'ArrowDown',
          'ArrowLeft',
          'ArrowRight',
          'KeyE',
          'KeyC',
        ].includes(event.code)
      ) {
        event.preventDefault();
        keys.add(event.code);
      }
    };
    const keyup = (event: KeyboardEvent) => {
      keys.delete(event.code);
    };
    const lost = (event: Event) => {
      event.preventDefault();
      setError('La connexion graphique a été interrompue. Rechargez la page pour retrouver la vue 3D.');
    };
    canvas.addEventListener('pointerdown', down);
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', cancel);
    canvas.addEventListener('wheel', wheel, { passive: false });
    canvas.addEventListener('keydown', keydown);
    canvas.addEventListener('keyup', keyup);
    canvas.addEventListener('blur', cancel);
    canvas.addEventListener('webglcontextlost', lost);
    window.addEventListener('blur', cancel);

    let animation = 0;
    let previous = performance.now();
    const animate = (now: number) => {
      animation = requestAnimationFrame(animate);
      const delta = Math.min((now - previous) / 1000, 0.05);
      previous = now;
      if (document.hidden) return;
      if (latest.current.cameraMode === 'pov' && keys.size) {
        const speed = (latest.current.scene?.id === 'soyuz' ? 0.65 : 1.2) * delta;
        const forward =
          Number(keys.has('KeyW') || keys.has('KeyZ') || keys.has('ArrowUp')) -
          Number(keys.has('KeyS') || keys.has('ArrowDown'));
        const sideways =
          Number(keys.has('KeyD') || keys.has('ArrowRight')) -
          Number(keys.has('KeyA') || keys.has('KeyQ') || keys.has('ArrowLeft'));
        camera.translateZ(-forward * speed);
        camera.translateX(sideways * speed);
        camera.position.y += (Number(keys.has('KeyE')) - Number(keys.has('KeyC'))) * speed;
        constrain();
        invalidate();
      }
      if (controls.enabled) controls.update();
      if (dirty) {
        renderer.render(world, camera);
        dirty = false;
      }
    };
    animation = requestAnimationFrame(animate);
    setReady(true);
    return () => {
      cancelAnimationFrame(animation);
      observer.disconnect();
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', cancel);
      canvas.removeEventListener('wheel', wheel);
      canvas.removeEventListener('keydown', keydown);
      canvas.removeEventListener('keyup', keyup);
      canvas.removeEventListener('blur', cancel);
      canvas.removeEventListener('webglcontextlost', lost);
      window.removeEventListener('blur', cancel);
      controls.removeEventListener('change', invalidate);
      controls.dispose();
      if (state.current) disposeField(state.current);
      disposeTree(world);
      key.shadow.dispose();
      renderer.dispose();
      canvas.remove();
      state.current = null;
    };
  }, []);

  useEffect(() => {
    const view = state.current;
    if (!view || !ready) return;
    clearGroup(view.model);
    view.invalidate();
    if (!scene) {
      setAssetState('empty');
      return;
    }
    let cancelled = false;
    setAssetState('loading');
    view.configureCamera();
    new GLTFLoader().load(
      scene.asset_url,
      (gltf) => {
        if (cancelled) {
          disposeTree(gltf.scene);
          return;
        }
        // The authored GLB is already Y-up ([x,z,-y]); applying another rotation
        // here would detach the recorded fields from their physical sample positions.
        gltf.scene.traverse((object) => {
          if (!(object instanceof THREE.Mesh)) return;
          object.castShadow = true;
          object.receiveShadow = true;
        });
        completePovShell(gltf.scene, scene);
        setPovPresentation(gltf.scene, latest.current.cameraMode);
        view.model.add(gltf.scene);
        view.invalidate();
        setAssetState('loaded');
      },
      undefined,
      () => {
        if (cancelled) return;
        addFallback(scene, view.model);
        view.invalidate();
        setAssetState('fallback');
      },
    );
    return () => {
      cancelled = true;
      clearGroup(view.model);
    };
  }, [scene, ready]);

  useEffect(() => {
    const view = state.current;
    if (!view) return;
    view.model.traverse((object) => {
      if (object.userData.cutaway === true) object.visible = !cutaway;
    });
    view.invalidate();
  }, [cutaway, assetState]);

  useEffect(() => {
    state.current?.configureCamera();
  }, [cameraMode, resetToken, ready]);

  useEffect(() => {
    const view = state.current;
    if (!view) return;
    clearGroup(view.components);
    for (const marker of markers ?? []) {
      if (!marker.position_m.every(finite)) continue;
      const selected = marker.id === selectedComponentId;
      const group = new THREE.Group();
      group.userData.component_id = marker.id;
      group.position.set(...toWorld(marker.position_m));
      const material = new THREE.MeshBasicMaterial({
        color: marker.color ?? '#8d9ba0',
        transparent: true,
        opacity: selected ? 1 : 0.8,
        depthTest: false,
        toneMapped: false,
      });
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(selected ? 0.052 : 0.035, 16, 12), material);
      sphere.renderOrder = 5;
      group.add(sphere);
      if (selected) {
        const ring = new THREE.Mesh(
          new THREE.SphereGeometry(0.085, 16, 12),
          new THREE.MeshBasicMaterial({
            color: '#e5f5f1',
            transparent: true,
            opacity: 0.45,
            wireframe: true,
            depthTest: false,
          }),
        );
        ring.renderOrder = 5;
        group.add(ring);
      }
      view.components.add(group);
    }
    view.invalidate();
  }, [markers, selectedComponentId, ready]);

  useEffect(() => {
    const view = state.current;
    if (!view) return;
    if (!bracket || layer === 'scene') {
      if (view.field) view.field.group.visible = false;
      setFieldStatus('empty');
      view.invalidate();
      return;
    }
    const frame = bracket.from;
    let layoutChanged =
      !view.field ||
      view.field.frame.shape.some((value, axis) => value !== frame.shape[axis]) ||
      view.field.frame.bounds_m.some((value, axis) => value !== frame.bounds_m[axis]);
    if (view.field && view.field.frame !== frame && !layoutChanged) {
      layoutChanged = view.field.indices.some((index) => {
        const a = missionPosition(view.field!.frame, index);
        const b = missionPosition(frame, index);
        return !a || !b || a.some((value, axis) => Math.abs(value - b[axis]) > 1e-7);
      });
    }
    if (layoutChanged) {
      disposeField(view);
      view.field = buildField(frame);
      if (view.field) view.world.add(view.field.group);
    }
    const count = view.field ? updateField(view.field, bracket, layer, scales, opacity) : 0;
    setFieldStatus(!bracket.compatible ? 'incompatible' : count ? 'available' : 'empty');
    view.invalidate();
  }, [bracket, layer, scales, opacity, ready]);

  return (
    <div
      className="mission-viewport"
      data-camera={cameraMode}
      data-layer={layer}
      data-field-status={fieldStatus}
    >
      <div className="mission-canvas" ref={host} />
      {error ? (
        <div className="mission-render-status" role="alert">
          {error}
        </div>
      ) : assetState === 'loading' ? (
        <div className="mission-render-status" role="status">
          Ouverture du compartiment…
        </div>
      ) : assetState === 'empty' ? (
        <div className="mission-render-status" role="status">
          En attente du compartiment
        </div>
      ) : null}
      {assetState === 'fallback' && (
        <div className="mission-render-status" role="status">
          Maquette indisponible · volumes simplifiés
        </div>
      )}
      {layer !== 'scene' &&
        !error &&
        ['loaded', 'fallback'].includes(assetState) &&
        fieldStatus !== 'available' && (
          <div className="mission-render-status" role="status">
            {fieldStatus === 'incompatible'
              ? 'Les grilles de ces deux instants ne permettent pas une interpolation.'
              : 'Aucun champ disponible à cet instant.'}
          </div>
        )}
      {!error && (
        <div className="mission-render-hint">
          {cameraMode === 'pov'
            ? 'Glisser pour regarder · ZQSD / flèches pour avancer · molette pour se rapprocher'
            : cameraMode === 'top'
              ? 'Glisser pour déplacer le plan · molette pour zoomer'
              : 'Glisser pour tourner · molette pour zoomer'}
        </div>
      )}
    </div>
  );
}
