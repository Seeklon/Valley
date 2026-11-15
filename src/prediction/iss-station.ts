import * as THREE from 'three';
import { issToWorld } from './iss-poc';
import type { IssCase } from './iss-poc';

type BoxItem = { position: THREE.Vector3; size: THREE.Vector3; rotation?: THREE.Quaternion };
const white = '#c7cdc9';

/** Repeated panel details share draw calls. All dimensions remain physical metres. */
class Boxes {
  private batches = new Map<THREE.Material, BoxItem[]>();
  add(material: THREE.Material, position: THREE.Vector3, size: THREE.Vector3, rotation?: THREE.Quaternion) {
    const list = this.batches.get(material) ?? [];
    list.push({ position, size, rotation });
    this.batches.set(material, list);
  }
  build(group: THREE.Group) {
    if (this.batches.size === 0) return;
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const transform = new THREE.Matrix4();
    const identity = new THREE.Quaternion();
    for (const [material, boxes] of this.batches) {
      const mesh = new THREE.InstancedMesh(geometry, material, boxes.length);
      boxes.forEach((box, i) =>
        mesh.setMatrixAt(i, transform.compose(box.position, box.rotation ?? identity, box.size)),
      );
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.frustumCulled = false; // r128: no instanced bounding sphere
      group.add(mesh);
    }
  }
}

const paintedSurfaces = new Map<string, HTMLCanvasElement>();
function canvasTexture(draw: (context: CanvasRenderingContext2D, size: number) => void, size = 256, key?: string) {
  let canvas = key && paintedSurfaces.get(key);
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Le rendu des matériaux nécessite Canvas 2D.');
    draw(context, size);
    if (key) paintedSurfaces.set(key, canvas);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.encoding = THREE.sRGBEncoding;
  texture.anisotropy = 4;
  return texture;
}

function surfaceTexture(kind: 'panel' | 'floor' | 'metal' | 'insulation') {
  const texture = canvasTexture((context, size) => {
    context.fillStyle = kind === 'floor' ? '#a9b1b4' : kind === 'metal' ? '#b9c0c3' : kind === 'insulation' ? '#b8b6a4' : '#e1e4df';
    context.fillRect(0, 0, size, size);
    let seed = 4187;
    for (let i = 0; i < 6000; i++) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const x = seed % size;
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const y = seed % size;
      context.fillStyle = `rgba(35,48,55,${kind === 'metal' ? 0.055 : 0.025})`;
      context.fillRect(x, y, kind === 'metal' ? 8 : 1, 1);
    }
    if (kind === 'floor') {
      context.strokeStyle = '#7c898d';
      context.lineWidth = 2;
      for (let n = 12; n < size; n += 16) {
        context.beginPath();
        context.moveTo(n, 0);
        context.lineTo(n, size);
        context.stroke();
      }
      for (let x = 6; x < size; x += 16)
        for (let y = 6; y < size; y += 16) {
          context.fillStyle = '#5f7077';
          context.fillRect(x, y, 3, 3);
        }
    }
    if (kind === 'panel') {
      const shade = context.createLinearGradient(0, 0, size, size);
      shade.addColorStop(0, '#ffffff35'); shade.addColorStop(0.5, '#ffffff00'); shade.addColorStop(1, '#334b5019');
      context.fillStyle = shade; context.fillRect(0, 0, size, size);
      context.strokeStyle = '#7b8c8a'; context.lineWidth = 3;
      context.strokeRect(3, 3, size - 6, size - 6);
      context.strokeStyle = '#f0f2eb'; context.lineWidth = 2;
      context.strokeRect(7, 7, size - 14, size - 14);
      context.strokeStyle = '#aebbb5'; context.lineWidth = 1;
      context.strokeRect(21, 21, size - 42, size - 42);
      for (const x of [15, size - 15])
        for (const y of [15, size - 15]) {
          context.fillStyle = '#7c8a87';
          context.beginPath();
          context.arc(x, y, 4, 0, Math.PI * 2);
          context.fill();
          context.strokeStyle = '#dae1dc'; context.lineWidth = 1;
          context.beginPath(); context.moveTo(x - 2, y); context.lineTo(x + 2, y);
          context.moveTo(x, y - 2); context.lineTo(x, y + 2); context.stroke();
        }
      context.fillStyle = '#476b75'; context.fillRect(32, size - 38, 46, 4);
      context.font = '9px monospace'; context.fillStyle = '#778b88';
      context.fillText('SERVICE PANEL', 88, size - 31);
    }
    if (kind === 'insulation') {
      context.lineWidth = 2;
      for (let offset = -size; offset < size * 2; offset += 64) {
        context.strokeStyle = '#8b928366';
        context.beginPath(); context.moveTo(offset, 0); context.lineTo(offset + size, size); context.stroke();
        context.beginPath(); context.moveTo(offset, 0); context.lineTo(offset - size, size); context.stroke();
      }
      context.setLineDash([3, 4]); context.strokeStyle = '#efecce';
      context.strokeRect(8, 8, size - 16, size - 16); context.setLineDash([]);
    }
  }, 512, `surface:${kind}`);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

function labelTexture(title: string, subtitle: string, display = false) {
  return canvasTexture((context, size) => {
    context.fillStyle = display ? '#102d3b' : '#dfe4df';
    context.fillRect(0, 0, size, size);
    context.fillStyle = display ? '#a6c9d5' : '#2a3e47';
    context.font = `600 ${display ? 17 : 20}px monospace`;
    context.fillText(title.toUpperCase().slice(0, 20), 15, 47);
    context.font = '12px monospace';
    context.fillStyle = display ? '#688f9f' : '#566b70';
    context.fillText(subtitle.toUpperCase().slice(0, 26), 15, 74);
    if (display) {
      context.strokeStyle = '#355768';
      context.lineWidth = 1;
      for (let y = 100; y < 230; y += 26) {
        context.beginPath();
        context.moveTo(16, y);
        context.lineTo(239, y);
        context.stroke();
      }
      context.fillStyle = '#527988';
      context.fillRect(18, 112, 72, 5);
      context.fillRect(18, 140, 120, 5);
      context.fillRect(18, 168, 92, 5);
      context.fillStyle = '#8db6b0';
      context.fillRect(219, 30, 9, 9);
      context.font = '10px monospace';
      context.fillStyle = '#6e9cae';
      context.fillText('DISPLAY / SCHEMATIC', 16, 223);
    } else {
      context.fillStyle = '#8c9b99';
      context.fillRect(15, 93, 225, 2);
      context.fillStyle = '#415d64';
      context.font = '11px monospace';
      context.fillText('EQUIPMENT ACCESS', 15, 119);
      for (let i = 0; i < 25; i++) context.fillRect(16 + i * 4, 162, i % 3 === 0 ? 2 : 1, 32);
      context.fillStyle = '#9f8650';
      context.fillRect(162, 160, 76, 32);
      context.fillStyle = '#e7e7d4';
      context.font = '11px monospace';
      context.fillText('ELEC', 182, 181);
    }
  }, 256, `label:${title}:${subtitle}:${display}`);
}

/** Visual habitat shell and equipment, derived only from the current physical proxies. */
export function createIssStationWorld(data: IssCase) {
  const world = new THREE.Scene();
  world.background = new THREE.Color('#18212b');
  const [width, depth, height] = data.scene.bounds_m;
  const span = Math.max(width, depth, height);
  const roomCenter = new THREE.Vector3(width / 2, height / 2, -depth / 2);
  const panelMap = surfaceTexture('panel');
  const metalMap = surfaceTexture('metal');
  const floorMap = surfaceTexture('floor');
  const insulationMap = surfaceTexture('insulation');
  const panelBump = panelMap.clone();
  panelBump.encoding = THREE.LinearEncoding;
  panelBump.needsUpdate = true;
  const panel = new THREE.MeshStandardMaterial({
    color: white,
    map: panelMap,
    bumpMap: panelBump,
    bumpScale: 0.002,
    roughness: 0.78,
    metalness: 0.04,
  });
  const warmPanel = new THREE.MeshStandardMaterial({
    color: '#adb8b5',
    map: panelMap,
    bumpMap: panelBump,
    bumpScale: 0.002,
    roughness: 0.72,
    metalness: 0.06,
  });
  const structure = new THREE.MeshStandardMaterial({
    color: '#7b8d96',
    map: metalMap,
    roughness: 0.42,
    metalness: 0.58,
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  });
  const dark = new THREE.MeshStandardMaterial({ color: '#243642', roughness: 0.75, metalness: 0.16 });
  const insulation = new THREE.MeshStandardMaterial({ color: '#cdc9b1', map: insulationMap, roughness: 0.95, metalness: 0.02 });
  const floorMaterial = new THREE.MeshStandardMaterial({
    color: '#536874',
    map: floorMap,
    roughness: 0.77,
    metalness: 0.35,
  });
  const rail = new THREE.MeshStandardMaterial({
    color: '#a1afb3',
    map: metalMap,
    roughness: 0.34,
    metalness: 0.68,
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  const black = new THREE.MeshStandardMaterial({ color: '#14212c', roughness: 0.6, metalness: 0.1 });
  const caution = new THREE.MeshStandardMaterial({
    color: '#ad8d4d',
    roughness: 0.65,
    polygonOffset: true,
    polygonOffsetFactor: -3,
    polygonOffsetUnits: -3,
  });
  const teal = new THREE.MeshStandardMaterial({
    color: '#416f7a',
    roughness: 0.5,
    metalness: 0.3,
    polygonOffset: true,
    polygonOffsetFactor: -3,
    polygonOffsetUnits: -3,
  });
  const blueCable = new THREE.MeshStandardMaterial({ color: '#527e9c', roughness: 0.65 });
  const lamp = new THREE.MeshStandardMaterial({
    color: '#d9f0f4',
    emissive: '#c1e3ed',
    emissiveIntensity: 2.2,
    roughness: 0.3,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    polygonOffsetUnits: -4,
  });
  const led = new THREE.MeshStandardMaterial({
    color: '#86b6ac',
    emissive: '#5b9a8c',
    emissiveIntensity: 0.9,
  });
  const wallGroups: { group: THREE.Group; cut: boolean }[] = [];

  // Boundary slabs extend out of the gas domain. Split at vent edges so their
  // actual openings remain open rather than drawing a wall behind the grille.
  const shell = (axis: number, side: 0 | 1, name: string, cut: boolean) => {
    const bounds = data.scene.bounds_m;
    const plane = side * bounds[axis];
    const axes = [0, 1, 2].filter((a) => a !== axis);
    const vents = data.scene.vents.filter(
      (vent) => Math.abs(vent.center_m[axis] - plane) < 1e-5 && vent.size_m[axis] < 1e-5,
    );
    const divisions = axes.map((a) => {
      const cells = Math.max(1, Math.ceil(bounds[a] / 0.72));
      const points = Array.from({ length: cells + 1 }, (_, i) => (i * bounds[a]) / cells);
      for (const vent of vents)
        points.push(vent.center_m[a] - vent.size_m[a] / 2, vent.center_m[a] + vent.size_m[a] / 2);
      return [...new Set(points.map((n) => Math.max(0, Math.min(bounds[a], n))))].sort((a, b) => a - b);
    });
    const group = new THREE.Group();
    group.name = `shell:${name}`;
    const boxes = new Boxes();
    for (let u = 1; u < divisions[0].length; u++)
      for (let v = 1; v < divisions[1].length; v++) {
        const center = [0, 0, 0],
          size = [0, 0, 0];
        center[axis] = plane + (side ? 1 : -1) * 0.028;
        size[axis] = 0.05;
        center[axes[0]] = (divisions[0][u - 1] + divisions[0][u]) / 2;
        center[axes[1]] = (divisions[1][v - 1] + divisions[1][v]) / 2;
        if (
          vents.some((vent) =>
            axes.every((a) => Math.abs(center[a] - vent.center_m[a]) < vent.size_m[a] / 2 - 1e-6),
          )
        )
          continue;
        size[axes[0]] = divisions[0][u] - divisions[0][u - 1];
        size[axes[1]] = divisions[1][v] - divisions[1][v - 1];
        if (Math.min(size[axes[0]], size[axes[1]]) < 0.005) continue;
        boxes.add(
          dark,
          new THREE.Vector3(...issToWorld(center as [number, number, number])),
          new THREE.Vector3(size[0], size[2], size[1]),
        );
        const insetSize = [...size];
        insetSize[axes[0]] -= Math.min(0.012, size[axes[0]] * 0.1);
        insetSize[axes[1]] -= Math.min(0.012, size[axes[1]] * 0.1);
        insetSize[axis] = 0.036;
        const insetCenter = [...center];
        insetCenter[axis] = plane + (side ? 1 : -1) * 0.018;
        boxes.add(
          axis === 2 && side === 0 ? floorMaterial : panel,
          new THREE.Vector3(...issToWorld(insetCenter as [number, number, number])),
          new THREE.Vector3(insetSize[0], insetSize[2], insetSize[1]),
        );
      }
    // Recessed rails lie on the boundary, not across the interior gas volume.
    if (axis !== 2) {
      for (const h of [0.12, height - 0.13]) {
        const position = [width / 2, depth / 2, h];
        const size = [width, depth, 0.035];
        position[axis] = plane + (side ? 1 : -1) * 0.012;
        size[axis] = 0.024;
        if (!vents.some((vent) => Math.abs(h - vent.center_m[2]) < vent.size_m[2] / 2 + 0.02))
          boxes.add(
            structure,
            new THREE.Vector3(...issToWorld(position as [number, number, number])),
            new THREE.Vector3(size[0], size[2], size[1]),
          );
      }
    }
    boxes.build(group);
    world.add(group);
    wallGroups.push({ group, cut });
  };
  shell(0, 0, 'port', false);
  shell(0, 1, 'starboard', true);
  shell(1, 0, 'front', true);
  shell(1, 1, 'aft', false);
  shell(2, 0, 'floor', false);
  shell(2, 1, 'ceiling', true);

  const equipment = new THREE.Group();
  equipment.name = 'physical-equipment';
  const boxes = new Boxes();
  const up = new THREE.Vector3(0, 1, 0);
  data.scene.objects.forEach((object, objectIndex) => {
    if (object.role === 'decoration') return;
    const center = new THREE.Vector3(...issToWorld(object.center_m));
    const size = new THREE.Vector3(object.size_m[0], object.size_m[2], object.size_m[1]);
    if (object.role === 'wall' || Math.min(size.x, size.z) < 0.2 || size.y < 0.4) {
      boxes.add(object.role === 'wall' ? panel : structure, center, size);
      return;
    }
    const delta = roomCenter.clone().sub(center);
    const normal =
      Math.abs(delta.x) >= Math.abs(delta.z)
        ? new THREE.Vector3(Math.sign(delta.x) || 1, 0, 0)
        : new THREE.Vector3(0, 0, Math.sign(delta.z) || 1);
    const u = new THREE.Vector3().crossVectors(up, normal);
    const faceWidth = Math.abs(normal.x) ? size.z : size.x;
    const faceDepth = Math.abs(normal.x) ? size.x : size.z;
    const face = center.clone().addScaledVector(normal, faceDepth / 2);
    const rotation = new THREE.Quaternion().setFromRotationMatrix(
      new THREE.Matrix4().makeBasis(u, up, normal),
    );
    const frontBox = (
      material: THREE.Material,
      x: number,
      y: number,
      w: number,
      h: number,
      thickness: number,
      inset = 0,
    ) => {
      boxes.add(
        material,
        face
          .clone()
          .addScaledVector(u, x)
          .addScaledVector(up, y)
          .addScaledVector(normal, -inset - thickness / 2),
        new THREE.Vector3(w, h, thickness),
        rotation,
      );
    };
    // Recess the core to receive front details; every visible part stays inside
    // the original equipment AABB, whose physical dimensions remain unchanged.
    const coreSize = size.clone();
    if (normal.x) coreSize.x -= 0.045;
    else coreSize.z -= 0.045;
    boxes.add(object.material_id === 'insulation' ? insulation : warmPanel, center.clone().addScaledVector(normal, -0.0225), coreSize);
    const frameWidth = Math.min(0.045, faceWidth * 0.06);
    frontBox(structure, -faceWidth / 2 + frameWidth / 2, 0, frameWidth, size.y, 0.04);
    frontBox(structure, faceWidth / 2 - frameWidth / 2, 0, frameWidth, size.y, 0.04);
    frontBox(structure, 0, size.y / 2 - frameWidth / 2, faceWidth, frameWidth, 0.04);
    frontBox(structure, 0, -size.y / 2 + frameWidth / 2, faceWidth, frameWidth, 0.04);
    // Flush identification stripe and recessed cable trunk: decoration stays inside the existing AABB.
    frontBox(teal, 0, size.y / 2 - frameWidth - 0.012, faceWidth * 0.56, 0.014, 0.003, 0.004);
    const rows = Math.max(2, Math.min(5, Math.round(size.y / 0.43)));
    const innerHeight = size.y - frameWidth * 2;
    const rowHeight = innerHeight / rows;
    const innerWidth = faceWidth - frameWidth * 2;
    for (let row = 0; row < rows; row++) {
      const y = innerHeight / 2 - (row + 0.5) * rowHeight;
      frontBox(row % 2 ? warmPanel : panel, 0, y, innerWidth - 0.009, rowHeight - 0.012, 0.026, 0.009);
      // Handles, fasteners, toggle recesses and ventilation markings are shallow.
      for (const sign of [-1, 1]) {
        frontBox(black, sign * innerWidth * 0.39, y, 0.047, rowHeight * 0.48, 0.012, 0.005);
        frontBox(rail, sign * innerWidth * 0.39, y, 0.016, rowHeight * 0.38, 0.014, 0.001);
        for (const dy of [-rowHeight * 0.35, rowHeight * 0.35])
          frontBox(dark, sign * innerWidth * 0.45, y + dy, 0.012, 0.012, 0.004, 0.007);
      }
      if (row === 0) {
        const screenWidth = Math.min(innerWidth * 0.38, rowHeight * 1.12);
        frontBox(black, -innerWidth * 0.1, y, screenWidth + 0.025, rowHeight * 0.68, 0.014, 0.001);
        const screen = new THREE.Mesh(
          new THREE.PlaneGeometry(screenWidth, rowHeight * 0.59),
          new THREE.MeshStandardMaterial({
            map: labelTexture('CONTROL', 'SCHEMATIC VIEW', true),
            color: '#b1d0d9',
            emissive: '#70b3ce',
            emissiveIntensity: 0.32,
            roughness: 0.38,
          }),
        );
        screen.position
          .copy(face)
          .addScaledVector(u, -innerWidth * 0.1)
          .addScaledVector(up, y)
          .addScaledVector(normal, -0.0007);
        screen.quaternion.copy(rotation);
        equipment.add(screen);
        for (let n = 0; n < 3; n++) {
          const px = innerWidth * 0.24,
            py = y + rowHeight * (0.2 - n * 0.2);
          frontBox(black, px, py, 0.046, 0.038, 0.012, 0.001);
          frontBox(n === 0 ? led : teal, px, py, 0.014, 0.022, 0.008);
        }
      } else if (row === rows - 1) {
        for (let n = 0; n < 8; n++)
          frontBox(
            black,
            0,
            y + (n - 3.5) * rowHeight * 0.07,
            innerWidth * 0.48,
            rowHeight * 0.024,
            0.005,
            0.002,
          );
      } else {
        frontBox(
          dark,
          -innerWidth * 0.16,
          y - rowHeight * 0.08,
          innerWidth * 0.22,
          rowHeight * 0.16,
          0.005,
          0.002,
        );
        frontBox(
          caution,
          innerWidth * 0.18,
          y - rowHeight * 0.07,
          innerWidth * 0.12,
          rowHeight * 0.13,
          0.005,
          0.002,
        );
      }
    }
    const materialName = object.combustible_material_id ?? object.material_id;
    const label = new THREE.Mesh(
      new THREE.PlaneGeometry(Math.min(innerWidth * 0.28, 0.3), Math.min(rowHeight * 0.45, 0.19)),
      new THREE.MeshStandardMaterial({
        map: labelTexture(`RACK ${String(objectIndex + 1).padStart(2, '0')}`, materialName),
        roughness: 0.8,
      }),
    );
    label.position
      .copy(face)
      .addScaledVector(u, innerWidth * 0.16)
      .addScaledVector(up, innerHeight / 2 - rowHeight * 1.3)
      .addScaledVector(normal, -0.0005);
    label.quaternion.copy(rotation);
    equipment.add(label);
    // Two shallow cable harnesses sit entirely within the proxy's front surface.
    for (const sign of [-1, 1]) {
      const curve = new THREE.CatmullRomCurve3(
        [
          [-0.3, -0.11],
          [-0.25, -0.16],
          [0.06, -0.18],
          [0.18, -0.12],
        ].map(([a, b]) =>
          face
            .clone()
            .addScaledVector(u, sign * a * innerWidth)
            .addScaledVector(up, -size.y * 0.24 + b * rowHeight)
            .addScaledVector(normal, -0.01),
        ),
      );
      const cable = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 16, 0.006, 5, false),
        sign < 0 ? blueCable : black,
      );
      cable.castShadow = true;
      equipment.add(cable);
    }
    for (let n = 0; n < 4; n++) {
      frontBox(n % 2 ? blueCable : black, -innerWidth * 0.31 + n * 0.016,
        -innerHeight * 0.27, 0.007, rowHeight * 0.46, 0.004, 0.003);
    }
    // Substrate/coating are actual annotations; visual paint is only an illustration.
    const anchor = new THREE.Object3D();
    anchor.name = object.id;
    anchor.position.copy(center);
    anchor.userData = { ...object, visual_only: true };
    equipment.add(anchor);
  });
  boxes.build(equipment);
  world.add(equipment);

  // Vent louvres lie in their annotated boundary plane, with trim outside gas.
  const ventilation = new THREE.Group();
  ventilation.name = 'compiled-ventilation';
  for (const vent of data.scene.vents) {
    const axis = vent.size_m.findIndex((value) => value < 1e-5);
    if (axis < 0) continue;
    const ventGroup = new THREE.Group();
    ventGroup.name = `vent:${vent.id}`;
    const ventBoxes = new Boxes();
    const center = new THREE.Vector3(...issToWorld(vent.center_m));
    const normal = new THREE.Vector3(...issToWorld(vent.normal)).normalize();
    const v = axis === 2 ? new THREE.Vector3(0, 0, -1) : up;
    const u = new THREE.Vector3().crossVectors(v, normal).normalize();
    const rotation = new THREE.Quaternion().setFromRotationMatrix(
      new THREE.Matrix4().makeBasis(u, v, normal),
    );
    const tangential = [0, 1, 2].filter((a) => a !== axis);
    const w = vent.size_m[tangential[0]],
      h = vent.size_m[tangential[1]];
    const boundaryOutward =
      center.clone().sub(roomCenter).dot(normal) > 0 ? normal.clone() : normal.clone().negate();
    const outwardSign = normal.dot(boundaryOutward);
    const add = (material: THREE.Material, x: number, y: number, sx: number, sy: number) =>
      ventBoxes.add(
        material,
        center
          .clone()
          .addScaledVector(u, x)
          .addScaledVector(v, y)
          .addScaledVector(normal, 0.012 * outwardSign),
        new THREE.Vector3(sx, sy, 0.024),
        rotation,
      );
    add(dark, 0, 0, w, h);
    // The dark background is a visual grille on an already-open boundary, not an OBST.
    for (const side of [-1, 1]) {
      add(structure, side * (w / 2 - 0.018), 0, 0.036, h);
      add(structure, 0, side * (h / 2 - 0.018), w, 0.036);
    }
    for (let j = -h / 2 + 0.06; j < h / 2 - 0.025; j += 0.055)
      ventBoxes.add(
        rail,
        center
          .clone()
          .addScaledVector(v, j)
          .addScaledVector(normal, 0.001 * outwardSign),
        new THREE.Vector3(w - 0.07, 0.018, 0.002),
        rotation,
      );
    const strip = vent.role === 'inlet' ? teal : caution;
    ventBoxes.add(
      strip,
      center
        .clone()
        .addScaledVector(v, h / 2 - 0.025)
        .addScaledVector(normal, 0.0005 * outwardSign),
      new THREE.Vector3(w * 0.4, 0.008, 0.001),
      rotation,
    );
    ventBoxes.build(ventGroup);
    ventilation.add(ventGroup);
    const highSide = vent.center_m[axis] > data.scene.bounds_m[axis] / 2;
    wallGroups.push({ group: ventGroup, cut: axis === 1 ? !highSide : highSide });
  }
  world.add(ventilation);

  const ceilingLights = new THREE.Group();
  ceilingLights.name = 'ceiling-light-panels';
  const fixtures = new Boxes();
  const lightCount = Math.max(2, Math.min(4, Math.ceil(depth / 1.8)));
  for (let i = 0; i < lightCount; i++) {
    const y = ((i + 0.5) * depth) / lightCount;
    fixtures.add(
      dark,
      new THREE.Vector3(width / 2, height + 0.016, -y),
      new THREE.Vector3(Math.min(1.4, width * 0.44), 0.024, 0.14),
    );
    fixtures.add(
      lamp,
      new THREE.Vector3(width / 2, height + 0.001, -y),
      new THREE.Vector3(Math.min(1.28, width * 0.4), 0.002, 0.095),
    );
    const light = new THREE.PointLight('#d9edf8', 13, span * 2.2, 2);
    light.position.set(width / 2, height - 0.12, -y);
    world.add(light);
  }
  fixtures.build(ceilingLights);
  world.add(ceilingLights);
  wallGroups.push({ group: ceilingLights, cut: true });
  world.add(new THREE.HemisphereLight('#dce8f2', '#344550', 0.72));
  const key = new THREE.DirectionalLight('#fff2de', 1.65);
  key.position.set(width * 0.24, height - 0.1, -depth * 0.18);
  key.target.position.copy(roomCenter);
  world.add(key.target);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = key.shadow.camera.bottom = -span;
  key.shadow.camera.right = key.shadow.camera.top = span;
  key.shadow.camera.near = 0.1;
  key.shadow.camera.far = span * 5;
  key.shadow.normalBias = 0.018;
  key.shadow.bias = -0.0002;
  world.add(key);

  const source = new THREE.Mesh(
    new THREE.OctahedronGeometry(Math.min(width, depth, height) * 0.025),
    new THREE.MeshBasicMaterial({ color: '#ffd28a', wireframe: true, depthTest: false, toneMapped: false }),
  );
  source.position.set(...issToWorld(data.conditions.source_position_m));
  source.renderOrder = 5;
  world.add(source);
  // Keep the source renderer's sRGB colours on the host site's older Three r128.
  // Textures already use sRGBEncoding; shared material colours must convert once.
  const converted = new Set<THREE.Material>();
  world.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (mesh.material) {
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        if (converted.has(material)) continue;
        converted.add(material);
        const surface = material as THREE.MeshStandardMaterial;
        surface.color?.convertSRGBToLinear();
        surface.emissive?.convertSRGBToLinear();
      }
    }
    if (object instanceof THREE.Light) object.color.convertSRGBToLinear();
    if (object instanceof THREE.HemisphereLight) object.groundColor.convertSRGBToLinear();
  });
  (world.background as THREE.Color).convertSRGBToLinear();
  return {
    world,
    setCutaway(value: boolean) {
      wallGroups.forEach(({ group, cut }) => {
        group.visible = !value || !cut;
      });
    },
  };
}
