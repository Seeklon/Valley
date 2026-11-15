import { describe, expect, it } from 'vitest';
import {
  aggregateHotspotMetrics,
  hotspotBaselineRows,
  hotspotCaseUrl,
  hotspotColdCaseAlarms,
  hotspotClass,
  hotspotFrameMetrics,
  metricsFromCounts,
  parseHotspotCase,
  parseHotspotIndex,
  peakHotspotFrame,
} from './hotspot-poc';
import type { HotspotCase, HotspotCaseEntry, HotspotFrame, HotspotIndex } from './hotspot-poc';

// Synthetic values are confined to unit tests; the UI loads only exported results.
const frame: HotspotFrame = {
  time_s: 3,
  temperature_c: [25, 28, 22, 21, null, 90, 50],
  hotspot_score: [0.5, 0.1, 0.8, 0.1, 1, 1, null],
  valid_mask: [true, true, true, true, true, false, true],
};
const metric = metricsFromCounts({ tp: 1, fp: 1, fn: 1, tn: 1 });
const entry: HotspotCaseEntry = {
  id: 'case-unit',
  split: 'validation',
  layout_id: 'layout-unit',
  family: 'unit-test',
  gravity_g: 0.0001,
  incident_type: 'overheating',
  ambient_temperature_c: 20,
  airflow_m_s: 0.2,
  peak_temperature_c: 28,
  metrics: metric,
  url: '/poc/cases/case-unit.json',
};
const index: HotspotIndex = {
  schema_version: 'hotspot-poc-1',
  generated_at: '2026-11-14T21:00:00Z',
  model: { id: 'test-only', name: 'Unit test', heat_delta_c: 5, score_threshold: 0.5 },
  metrics: { validation: metric },
  cases: [entry],
  limitations: ['Test-only fixture.'],
};
const data: HotspotCase = {
  id: entry.id,
  scene: {
    bounds_m: [2, 3, 2],
    objects: [
      {
        id: 'box',
        name: 'Box',
        role: 'obstacle',
        material_id: 'steel',
        center_m: [1, 1, 0.5],
        size_m: [1, 1, 1],
      },
    ],
    vents: [],
  },
  conditions: {
    ambient_temperature_c: 20,
    gravity_g: 0.0001,
    airflow_m_s: 0.2,
    incident_type: 'overheating',
    source_position_m: [1, 1, 1],
  },
  sample_positions_m: Array.from({ length: 7 }, (_, i) => [0.1 + i * 0.1, 1, 1]),
  frames: [frame],
};

describe('F1 comparison with the source proximity baseline', () => {
  const reported: HotspotIndex = {
    ...index,
    metrics: { validation: { ...metric, groups: { microgravity: { f1: 0.3 }, earth: { f1: null } } } },
    baselines: {
      validation: { source_proximity: { groups: { microgravity: { f1: 0.4 }, earth: { f1: 0.2 } } } },
    },
  };
  it('uses reported F1 for each gravity and preserves an undefined ratio', () => {
    expect(parseHotspotIndex(reported)).toBe(reported);
    expect(hotspotBaselineRows(reported, 'validation')).toEqual([
      { gravity: 'microgravity', label: 'Microgravité', model_f1: 0.3, proximity_f1: 0.4 },
      { gravity: 'earth', label: 'Terre', model_f1: null, proximity_f1: 0.2 },
    ]);
  });
  it('never merges partitions or fabricates an unavailable comparison', () => {
    expect(hotspotBaselineRows(reported, 'all')).toEqual([]);
    expect(hotspotBaselineRows(reported, 'test')).toEqual([]);
    expect(hotspotBaselineRows(index, 'validation')).toEqual([]);
    expect(
      hotspotBaselineRows(
        {
          ...reported,
          baselines: { validation: { source_proximity: { groups: { microgravity: { f1: 0.4 } } } } },
        },
        'validation',
      ),
    ).toEqual([]);
  });
  it('rejects invalid F1 values rather than displaying percentages as ratios', () => {
    expect(() =>
      parseHotspotIndex({
        ...reported,
        baselines: { validation: { source_proximity: { groups: { earth: { f1: 40 } } } } },
      }),
    ).toThrow('ratio');
    expect(() =>
      parseHotspotIndex({
        ...reported,
        metrics: { validation: { ...metric, groups: { microgravity: { f1: -0.2 } } } },
      }),
    ).toThrow('ratio');
  });
});

describe('hotspot comparison on common observed points', () => {
  it('counts false alarms per observed cold case without hiding them among cold points', () => {
    const cold = { ...entry, metrics: metricsFromCounts({ tp: 0, fn: 0, fp: 0, tn: 100000 }) };
    const alarm = { ...entry, metrics: metricsFromCounts({ tp: 0, fn: 0, fp: 1, tn: 100000 }) };
    const empty = { ...entry, metrics: metricsFromCounts({ tp: 0, fn: 0, fp: 0, tn: 0 }) };
    expect(hotspotColdCaseAlarms([cold, alarm, entry, empty])).toEqual({ total: 2, alerted: 1 });
    expect(hotspotColdCaseAlarms([])).toEqual({ total: 0, alerted: 0 });
  });
  it('includes equality at both fixed thresholds and distinguishes all error classes', () => {
    expect(Array.from({ length: 7 }, (_, i) => hotspotClass(frame, i, 20, 5, 0.5))).toEqual([
      'tp',
      'fn',
      'fp',
      'tn',
      null,
      null,
      null,
    ]);
  });

  it('excludes missing and masked measurements from every denominator', () => {
    expect(hotspotFrameMetrics(frame, 20, 5, 0.5)).toEqual({
      tp: 1,
      fn: 1,
      fp: 1,
      tn: 1,
      precision: 0.5,
      recall: 0.5,
      iou: 1 / 3,
      false_positive_rate: 0.5,
      n_valid: 4,
    });
  });

  it('honors exported class masks to preserve float32 threshold decisions', () => {
    const withMasks = {
      ...frame,
      hotspot_truth: [false, true, false, false, null, false, null],
      predicted_hot_mask: [true, true, false, false, null, false, null],
    };
    expect(hotspotClass(withMasks, 0, 20, 5, 0.5)).toBe('fp');
    expect(hotspotClass(withMasks, 1, 20, 5, 0.5)).toBe('tp');
  });

  it('keeps undefined recall/precision/IoU absent for a genuinely cold control', () => {
    expect(metricsFromCounts({ tp: 0, fn: 0, fp: 0, tn: 100 })).toMatchObject({
      recall: null,
      precision: null,
      iou: null,
      false_positive_rate: 0,
    });
    expect(metricsFromCounts({ tp: 0, fn: 0, fp: 0, tn: 0 }).false_positive_rate).toBeNull();
  });

  it('aggregates confusion counts rather than averaging incompatible denominators', () => {
    const second = { ...entry, id: 'second', metrics: metricsFromCounts({ tp: 9, fn: 0, fp: 0, tn: 0 }) };
    expect(aggregateHotspotMetrics([entry, second])).toMatchObject({
      tp: 10,
      recall: 10 / 11,
      precision: 10 / 11,
      iou: 10 / 12,
    });
    expect(aggregateHotspotMetrics([])).toBeNull();
  });

  it('chooses the initial instant using observed FDS temperatures, never predicted scores', () => {
    const before = { ...frame, time_s: 0, temperature_c: [20, 20, 20, 20, null, 9999, 20] };
    const after = {
      ...frame,
      time_s: 6,
      temperature_c: [26, 75, 23, 22, null, 9999, 22],
      hotspot_score: [0, 0, 0, 0, null, 1, null],
    };
    expect(peakHotspotFrame([before, frame, after])).toBe(2);
    expect(peakHotspotFrame([])).toBe(0);
  });
});

describe('static export validation', () => {
  it('accepts the contract without requiring a GLB or an API scene', () => {
    expect(parseHotspotIndex(index)).toBe(index);
    expect(parseHotspotCase(data, entry.id)).toBe(data);
  });

  it('accepts the explicit all-cold threshold candidate without changing score bounds', () => {
    expect(
      parseHotspotIndex({ ...index, model: { ...index.model, score_threshold: 1.000001 } }).model
        .score_threshold,
    ).toBe(1.000001);
    expect(hotspotClass(frame, 0, 20, 5, 1.000001)).toBe('fn');
  });

  it('rejects a wrong case identity and unequal point arrays instead of misaligning views', () => {
    expect(() => parseHotspotCase(data, 'other')).toThrow('correspond');
    expect(() =>
      parseHotspotCase({ ...data, frames: [{ ...frame, hotspot_score: [0.2] }] }, entry.id),
    ).toThrow('nombre');
  });

  it('rejects invalid scores, masks and timestamps', () => {
    expect(() =>
      parseHotspotCase({ ...data, frames: [{ ...frame, hotspot_score: [2, 0, 0, 0, 0, 0, 0] }] }, entry.id),
    ).toThrow('[0, 1]');
    expect(() => parseHotspotCase({ ...data, frames: [{ ...frame, valid_mask: [true] }] }, entry.id)).toThrow(
      'Masque',
    );
    expect(() => parseHotspotCase({ ...data, frames: [frame, frame] }, entry.id)).toThrow('croissants');
  });

  it('rejects non-finite coordinates and ambiguous case identities', () => {
    expect(() => parseHotspotCase({ ...data, sample_positions_m: [[0, NaN, 0]] }, entry.id)).toThrow(
      'Positions',
    );
    expect(() => parseHotspotIndex({ ...index, cases: [entry, entry] })).toThrow('répété');
  });

  it('requires actual metric ratios and valid split membership', () => {
    expect(() => parseHotspotIndex({ ...index, metrics: { validation: { ...metric, recall: 50 } } })).toThrow(
      'ratio',
    );
    expect(() => parseHotspotIndex({ ...index, cases: [{ ...entry, split: 'unknown' }] })).toThrow(
      'Partition',
    );
  });

  it('only downloads local POC case files', () => {
    expect(hotspotCaseUrl('cases/test.json')).toBe('/poc/cases/test.json');
    expect(hotspotCaseUrl('./cases/test.json')).toBe('/poc/cases/test.json');
    expect(hotspotCaseUrl('/poc/cases/test.json')).toBe('/poc/cases/test.json');
    for (const url of [
      'https://example.org/test.json',
      '//example.org/test.json',
      '../private.json',
      '/api/run.json',
      'cases/%2e%2e/private.json',
    ])
      expect(() => hotspotCaseUrl(url)).toThrow();
  });
});
