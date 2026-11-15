import * as THREE from 'three';
import { HOTSPOT_COLORS } from './hotspot-poc';
import { assertIssSceneBinding, issProbeSpacing, issSampleState, issToWorld } from './iss-poc';
import type { IssCase, IssDisplay, IssFrame, IssModel, IssScene } from './iss-poc';
export interface IssOverlayOptions { display: IssDisplay; heat: boolean; smoke: boolean; }

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
    },
  };
}
