import { describe, expect, it } from 'vitest';
import { createIssPocOverlay } from './overlay';
import { metricsFromCounts } from './hotspot-poc';
import {
  assertIssSceneBinding,
  decodeIssCase,
  issCaseUrl,
  issFrameMetrics,
  issGeometryKey,
  issInteriorPose,
  issPeakFrame,
  issProbeSpacing,
  issSampleState,
  issToWorld,
  parseIssCase,
  parseIssIndex,
} from './iss-poc';
import type { IssCase, IssCaseEntry, IssFrame, IssIndex, IssModel } from './iss-poc';

// All fabricated values remain inside unit tests; public exports come from model inference.
const model: IssModel = {
  id: 'unit-test-only',
  weights_sha256: 'a'.repeat(64),
  dataset_sha256: 'b'.repeat(64),
  heat_delta_c: 5,
  smoke_threshold_kg_m3: 1e-6,
  score_thresholds: { heat: 0.5, smoke: 0.5 },
};
const frame: IssFrame = {
  time_s: 2,
  temperature_c: [25, 30, 20, 21, null, 90],
  soot_kg_m3: [0, 1e-6, 2e-6, 0, 0, 5e-6],
  heat_score: [0.5, 0.1, 0.8, 0.1, 1, 1],
  smoke_score: [0.9, 0.6, 0.1, 0.1, null, 1],
  heat_valid_mask: [true, true, true, true, true, false],
  smoke_valid_mask: [true, true, true, true, true, true],
};
const metric = metricsFromCounts({ tp: 1, fp: 1, fn: 1, tn: 1 });
const entry: IssCaseEntry = {
  id: 'case-unit',
  split: 'validation',
  layout_id: 'unit-layout',
  module_id: 'lab',
  family: 'unit-test',
  gravity_g: 0.0001,
  url: './cases/unit.json',
  sha256: 'c'.repeat(64),
  metrics: { heat: metric, smoke: metric },
};
const index: IssIndex = {
  schema_version: 'iss-poc-1',
  model,
  cases: [entry],
  metrics: { validation: entry.metrics },
  default_case_id: entry.id,
  limitations: ['Unit test fixture.'],
};
const data: IssCase = {
  schema_version: 'iss-poc-1',
  id: entry.id,
  layout_id: entry.layout_id,
  module_id: entry.module_id,
  heat_delta_c: model.heat_delta_c,
  smoke_threshold_kg_m3: model.smoke_threshold_kg_m3,
  score_thresholds: model.score_thresholds,
  scene: {
    id: 'unit-scene',
    name: 'Unit scene',
    bounds_m: [2, 4, 2],
    objects: [
      { id: 'rack', role: 'equipment', material_id: 'steel', center_m: [0.5, 2, 1], size_m: [0.5, 0.5, 1] },
    ],
    vents: [{ id: 'supply', role: 'inlet', center_m: [0, 2, 1], size_m: [0, 0.2, 0.2], normal: [1, 0, 0] }],
  },
  conditions: {
    ambient_temperature_c: 20,
    gravity_g: 0.0001,
    airflow_m_s: 0.2,
    incident_type: 'arc',
    source_position_m: [1, 1, 1],
  },
  sample_positions_m: [
    [0.1, 1, 1],
    [0.3, 1, 1],
    [0.5, 1, 1],
    [0.7, 1, 1],
    [0.9, 1, 1],
    [1.1, 1, 1],
  ],
  frames: [frame],
};

describe('ISS replay contract and identity', () => {
  it('accepts exact independent heat/smoke exports with model provenance', () => {
    expect(parseIssIndex(index)).toBe(index);
    expect(parseIssCase(data, entry, model)).toBe(data);
    expect(issCaseUrl('./cases/unit.json')).toBe('/poc/iss/cases/unit.json');
  });
  it('rejects mismatched scenarios, layouts, model thresholds and missing provenance', () => {
    expect(() => parseIssCase({ ...data, id: 'another' }, entry, model)).toThrow('sélectionné');
    expect(() => parseIssCase({ ...data, layout_id: 'another' }, entry, model)).toThrow('layout_id');
    expect(() => parseIssCase({ ...data, module_id: 'node' }, entry, model)).toThrow('module_id');
    expect(() =>
      parseIssCase({ ...data, score_thresholds: { heat: 0.4, smoke: 0.5 } }, entry, model),
    ).toThrow('Seuil heat');
    expect(() => parseIssCase({ ...data, heat_delta_c: 10 }, entry, model)).toThrow('Seuil physique');
    expect(() => parseIssIndex({ ...index, model: { ...model, weights_sha256: 'not-a-hash' } })).toThrow(
      'Empreinte',
    );
    expect(() => parseIssIndex({ ...index, cases: [{ ...entry, sha256: '' }] })).toThrow('empreinte');
  });
  it('rejects truncated arrays, non-finite scores, out-of-domain probes and duplicated times', () => {
    expect(() => parseIssCase({ ...data, frames: [{ ...frame, heat_score: [0] }] }, entry)).toThrow('sondes');
    expect(() =>
      parseIssCase({ ...data, frames: [{ ...frame, heat_score: [2, 0, 0, 0, 0, 0] }] }, entry),
    ).toThrow('[0, 1]');
    expect(() => parseIssCase({ ...data, frames: [{ ...frame, smoke_valid_mask: [true] }] }, entry)).toThrow(
      'smoke_valid_mask',
    );
    expect(() => parseIssCase({ ...data, sample_positions_m: [[9, 1, 1]] }, entry)).toThrow(
      'hors du domaine',
    );
    expect(() => parseIssCase({ ...data, frames: [frame, frame] }, entry)).toThrow('croissants');
  });
  it('restricts replay fetches to the known static export directory', () => {
    for (const url of [
      'https://external.test/x.json',
      '/poc/cases/old.json',
      '../old.json',
      '/poc/iss/a/../x.json',
      '/poc/iss/x.json?old=1',
      '/poc/iss/%2e%2e/x.json',
    ])
      expect(() => issCaseUrl(url)).toThrow();
  });
  it('checks exact JSON bytes before parsing, including whitespace changes', async () => {
    const bytes = new TextEncoder().encode(JSON.stringify(data)).buffer;
    const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (n) =>
      n.toString(16).padStart(2, '0'),
    ).join('');
    expect((await decodeIssCase(bytes, { ...entry, sha256 }, model)).id).toBe(data.id);
    await expect(decodeIssCase(bytes, entry, model)).rejects.toThrow('empreinte');
    const different = new TextEncoder().encode(JSON.stringify(data) + '\n').buffer;
    await expect(decodeIssCase(different, { ...entry, sha256 }, model)).rejects.toThrow('empreinte');
  });
});

describe('ISS geometry registration', () => {
  it('converts Z-up metres to THREE without an implicit scale or offset', () => {
    expect(issToWorld([1, 2, 3])).toEqual([1, 3, -2]);
    expect(issToWorld([0, -1, 0])).toEqual([0, 0, 1]);
    expect(issProbeSpacing(data)).toBeCloseTo(0.2);
  });
  it('accepts a reordered copy but rejects different layout, material and airflow proxies', () => {
    const reordered = {
      ...data.scene,
      name: 'Artistic display name',
      objects: [...data.scene.objects].reverse(),
    };
    expect(issGeometryKey(reordered)).toBe(issGeometryKey(data.scene));
    expect(() => assertIssSceneBinding(data, reordered)).not.toThrow();
    expect(() => assertIssSceneBinding(data, { ...data.scene, bounds_m: [2, 5, 2] })).toThrow('géométrie');
    expect(() =>
      assertIssSceneBinding(data, {
        ...data.scene,
        objects: [{ ...data.scene.objects[0], material_id: 'pmma' }],
      }),
    ).toThrow('matériaux');
    expect(() => assertIssSceneBinding(data, { ...data.scene, vents: [] })).toThrow();
    expect(() =>
      assertIssSceneBinding(data, {
        ...data.scene,
        objects: [{ ...data.scene.objects[0], thermal_thickness_m: 0.01 }],
      }),
    ).toThrow('matériaux');
  });
  it.each(['obstacle', 'wall'])('frames the real source from a free position with a front %s', (role) => {
    const obstacle = {
      id: 'front-block',
      role,
      material_id: 'steel',
      center_m: [1, 0.65, 1] as [number, number, number],
      size_m: [1.2, 1.3, 2] as [number, number, number],
    };
    const value = { ...data, scene: { ...data.scene, objects: [obstacle] } };
    const before = JSON.stringify(value);
    const pose = issInteriorPose(value);
    expect(pose.target_m.slice(0, 2)).toEqual(data.conditions.source_position_m.slice(0, 2));
    expect(pose.position_m[1]).toBeGreaterThan(1.3);
    expect(pose.position_m.every((n, axis) => n > 0 && n < data.scene.bounds_m[axis])).toBe(true);
    expect(JSON.stringify(value)).toBe(before);
  });
});

describe('independent heat and smoke labels', () => {
  it('separates actual and predicted classes, including equality at the physical thresholds', () => {
    expect(
      Array.from({ length: 6 }, (_, i) => issSampleState(frame, i, 'heat', 20, model)?.kind ?? null),
    ).toEqual(['tp', 'fn', 'fp', 'tn', null, null]);
    expect(
      Array.from({ length: 6 }, (_, i) => issSampleState(frame, i, 'smoke', 20, model)?.kind ?? null),
    ).toEqual(['fp', 'tp', 'fn', 'tn', null, 'tp']);
  });
  it('uses per-channel observation masks and excludes missing values from metrics', () => {
    expect(issFrameMetrics(data, frame, model, 'heat')).toMatchObject({
      tp: 1,
      fp: 1,
      fn: 1,
      tn: 1,
      n_valid: 4,
    });
    expect(issFrameMetrics(data, frame, model, 'smoke')).toMatchObject({
      tp: 2,
      fp: 1,
      fn: 1,
      tn: 1,
      n_valid: 5,
    });
  });
  it('preserves exact float32 boundaries and rejects contradictory exported masks', () => {
    const exact = {
      ...frame,
      heat_score: [0.4999999701976776, 0.1, 0.8, 0.1, 1, 1],
      hotspot_truth: [true, true, false, false, null, null],
      predicted_hot_mask: [false, false, true, false, null, null],
    };
    expect(parseIssCase({ ...data, frames: [exact] }, entry, model)).toBeTruthy();
    expect(issSampleState(exact, 0, 'heat', 20, model)?.kind).toBe('fn');
    expect(() =>
      parseIssCase(
        { ...data, frames: [{ ...exact, hotspot_truth: [false, true, false, false, null, null] }] },
        entry,
        model,
      ),
    ).toThrow('Masque vérité');
    expect(() =>
      parseIssCase(
        { ...data, frames: [{ ...exact, predicted_hot_mask: [true, false, true, false, null, null] }] },
        entry,
        model,
      ),
    ).toThrow('Masque prédit');
    const smoke = {
      ...frame,
      soot_kg_m3: [0, Math.fround(1e-6), 2e-6, 0, 0, 5e-6],
      smoke_truth: [false, false, true, false, null, true],
    };
    expect(parseIssCase({ ...data, frames: [smoke] }, entry, model)).toBeTruthy();
    expect(issSampleState(smoke, 1, 'smoke', 20, model)?.truth).toBe(false);
  });
  it('chooses initial time from observed FDS temperature alone', () => {
    const first = {
      ...frame,
      time_s: 0,
      temperature_c: [20, 20, 20, 20, null, 99999],
      heat_score: [1, 1, 1, 1, 1, 1],
    };
    expect(issPeakFrame({ ...data, frames: [first, frame] })).toBe(1);
  });
  it('opens smoke-only scenarios at their measured soot peak, even when heat peaks earlier', () => {
    const early = {
      ...frame,
      time_s: 0,
      temperature_c: [24, 24, 24, 24, null, 9999],
      soot_kg_m3: [0, 0, 0, 0, 0, 0],
    };
    const smoky = {
      ...frame,
      temperature_c: [20, 20, 20, 20, null, 9999],
      soot_kg_m3: [0, 0, 2e-6, 0, 0, 0],
    };
    expect(issPeakFrame({ ...data, frames: [early, smoky] })).toBe(1);
  });
});

describe('portable overlay renders classifications only', () => {
  it('keeps prediction, reference and error support separate without a WebGL context', () => {
    const overlay = createIssPocOverlay(data, model, data.scene);
    try {
      const heat = overlay.group.getObjectByName('heat')!;
      const smoke = overlay.group.getObjectByName('smoke')!;
      const alpha = (object: typeof heat) =>
        Array.from((object as import('three').Points).geometry.getAttribute('glyphAlpha').array).map(
          (n) => n > 0,
        );
      overlay.setFrame(frame, { display: 'prediction', heat: true, smoke: true });
      expect(alpha(heat)).toEqual([true, false, true, false, false, false]);
      expect(alpha(smoke)).toEqual([true, true, false, false, false, true]);
      overlay.setFrame(frame, { display: 'reference', heat: true, smoke: false });
      expect(alpha(heat)).toEqual([true, true, false, false, false, false]);
      expect(smoke.visible).toBe(false);
      overlay.setFrame(frame, { display: 'errors', heat: true, smoke: true });
      expect(alpha(heat)).toEqual([true, true, true, false, false, false]);
      expect(overlay.group.userData.mode).toBe('recorded-inference');
    } finally {
      overlay.dispose();
    }
    expect(overlay.group.children).toHaveLength(0);
  });
});
