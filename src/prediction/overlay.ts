import * as THREE from 'three';
import { HOTSPOT_COLORS } from './hotspot-poc';
import { assertIssSceneBinding, issProbeSpacing, issSampleState, issToWorld } from './iss-poc';
import type { IssCase, IssDisplay, IssFrame, IssModel, IssScene } from './iss-poc';
export interface IssOverlayOptions { display: IssDisplay; heat: boolean; smoke: boolean; }

// A small, repeatable texture gives each observed probe soft cloud detail without
// inventing transport, extra observations or an animated physical simulation.
function cloudTexture() {
  const size = 128;
  const pixels = new Uint8Array(size * size * 4);
  const hash = (x: number, y: number) => {
    let n = Math.imul(x + 17, 374761393) + Math.imul(y + 29, 668265263);
    n = Math.imul(n ^ (n >>> 13), 1274126177);
    return (n >>> 0) / 4294967295;
  };
  const noise = (x: number, y: number, scale: number) => {
    const px = x * scale / size, py = y * scale / size;
    const ix = Math.floor(px), iy = Math.floor(py);
    const fx = px - ix, fy = py - iy;
    const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
    const a = hash(ix % scale, iy % scale), b = hash((ix + 1) % scale, iy % scale);
    const c = hash(ix % scale, (iy + 1) % scale), d = hash((ix + 1) % scale, (iy + 1) % scale);
    return (a + (b - a) * u) * (1 - v) + (c + (d - c) * u) * v;
  };
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = (y * size + x) * 4;
    pixels[i] = Math.round(255 * (noise(x, y, 4) * 0.55 + noise(x, y, 8) * 0.3 + noise(x, y, 16) * 0.15));
    pixels[i + 1] = Math.round(255 * noise(x, y, 32));
    pixels[i + 2] = pixels[i];
    pixels[i + 3] = 255;
  }
  const texture = new THREE.DataTexture(pixels, size, size, THREE.RGBAFormat);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.magFilter = texture.minFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

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
  const texture = cloudTexture();
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
        cloudDetail: { value: texture },
        errorPalette: { value: 0 },
      },
      vertexShader: `
        attribute vec3 glyphColor;
        attribute float glyphAlpha;
        uniform float radius;
        uniform float viewportHeight;
        varying vec3 pointColor;
        varying float pointAlpha;
        varying float pointSeed;
        void main() {
          vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
          pointColor = glyphColor;
          pointAlpha = glyphAlpha;
          pointSeed = fract(sin(dot(position, vec3(12.9898, 78.233, 37.719))) * 43758.5453);
          gl_Position = projectionMatrix * viewPosition;
          gl_PointSize = clamp(radius * projectionMatrix[1][1] * viewportHeight / max(0.01, -viewPosition.z), 1.0, 240.0);
        }
      `,
      fragmentShader: `
        uniform float smokeTexture;
        uniform sampler2D cloudDetail;
        uniform float errorPalette;
        varying vec3 pointColor;
        varying float pointAlpha;
        varying float pointSeed;
        void main() {
          vec2 p = (gl_PointCoord - vec2(0.5)) * 2.0;
          float r = length(p);
          if (r > 1.0 || pointAlpha <= 0.0) discard;
          float angle = pointSeed * 6.2831853;
          vec2 uv = mat2(cos(angle), -sin(angle), sin(angle), cos(angle)) * p * 0.5;
          vec2 detail = texture2D(cloudDetail, uv + vec2(pointSeed, pointSeed * 0.73)).rg;
          float cloudEdge = 1.0 - smoothstep(0.38, 1.0, r + (detail.r - 0.5) * 0.32);
          float smokeAlpha = cloudEdge * (0.36 + detail.r * 0.8) * (0.86 + detail.g * 0.14);
          float heatAlpha = exp(-3.0 * r * r) * (1.0 - smoothstep(0.65, 1.0, r + (detail.r - 0.5) * 0.18));
          float core = pow(1.0 - r, 2.0) * (0.7 + detail.r * 0.3);
          vec3 heatColor = mix(pointColor * (0.8 + detail.g * 0.2), vec3(1.0, 0.72, 0.22), core * 0.75);
          vec3 smokeColor = pointColor * (0.65 + detail.r * 0.75) + vec3(0.012 * core);
          vec3 texturedColor = mix(heatColor, smokeColor, smokeTexture);
          gl_FragColor = vec4(mix(texturedColor, pointColor, errorPalette), pointAlpha * mix(heatAlpha, smokeAlpha, smokeTexture));
          #include <tonemapping_fragment>
          #include <encodings_fragment>
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
      channels.forEach(({ channel, points, geometry, material }) => {
        points.visible = options[channel];
        material.uniforms.errorPalette.value = options.display === 'errors' ? 1 : 0;
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
          // r171 does this automatically; the host site's r128 expects linear values.
          color.convertSRGBToLinear();
          colors.setXYZ(point, color.r, color.g, color.b);
          alphas.setX(point, visible ? (channel === 'heat' ? 0.95 : 0.72) : 0);
        }
        colors.needsUpdate = true;
        alphas.needsUpdate = true;
      });
    },
    dispose() {
      group.parent?.remove(group);
      channels.forEach(({ geometry, material }) => {
        geometry.dispose();
        material.dispose();
      });
      group.clear();
      texture.dispose();
    },
  };
}
