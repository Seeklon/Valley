import { describe, expect, it } from 'vitest';
import { defaultCase, environmentCases, roomLayouts, scenarioName } from './catalog';
import type { IssCaseEntry, IssIndex } from './iss-poc';
import { metricsFromCounts } from './hotspot-poc';

const metric = metricsFromCounts({ tp: 0, fp: 0, fn: 0, tn: 1 });
const entry = (id: string, gravity: number, family = 'iss-node'): IssCaseEntry => ({
  id, gravity_g: gravity, family, module_id: family, layout_id: id,
  split: 'validation', incident_type: 'flaming', url: `./cases/${id}.json`,
  sha256: 'a'.repeat(64), metrics: { heat: metric, smoke: metric },
});
const index: IssIndex = {
  schema_version: 'iss-poc-1',
  model: { id: 'unit-only', weights_sha256: 'b'.repeat(64), dataset_sha256: 'c'.repeat(64),
    heat_delta_c: 5, smoke_threshold_kg_m3: 1e-6, score_thresholds: { heat: 0.5, smoke: 0.5 } },
  metrics: {},
  cases: [entry('micro', 0.0001), entry('earth', 1), entry('moon', 1 / 6), entry('cargo', 0.0001, 'habitat-cargo')],
  example_cases: { modules: { 'iss-node': 'micro' } },
};

describe('bind a room to compatible saved predictions', () => {
  it('keeps microgravity, Earth and lunar predictions separate', () => {
    expect(environmentCases(index, 'iss').map(item => item.id)).toEqual(['micro', 'cargo']);
    expect(environmentCases(index, 'earth').map(item => item.id)).toEqual(['earth']);
    expect(environmentCases(index, 'moon').map(item => item.id)).toEqual(['moon']);
    expect(environmentCases({ ...index, cases: index.cases.filter(item => item.id !== 'moon') }, 'moon')).toEqual([]);
  });
  it('cannot pick the microgravity example for the Earth environment', () => {
    expect(defaultCase(index, environmentCases(index, 'earth'), 'iss-node')?.id).toBe('earth');
  });
  it('prefers the exported example within the requested family', () => {
    expect(defaultCase(index, environmentCases(index, 'iss'), 'iss-node')?.id).toBe('micro');
    expect(defaultCase(index, environmentCases(index, 'iss'), 'habitat-cargo')?.id).toBe('cargo');
  });
  it('returns no invented scenario when the export contains no compatible case', () => {
    expect(defaultCase(index, [], 'iss-node')).toBeUndefined();
  });
  it('groups ventilation variants under stable rooms without leaking another compartment', () => {
    const entries = [
      { ...entry('fast', 0), layout_id: 'layout-10' },
      { ...entry('still', 0), layout_id: 'layout-2' },
      { ...entry('reverse', 0), layout_id: 'layout-2' },
      { ...entry('cargo', 0, 'habitat-cargo'), layout_id: 'layout-1' },
    ];
    expect(roomLayouts(entries, 'iss-node')).toEqual([
      { id: 'layout-2', name: 'Room 01' }, { id: 'layout-10', name: 'Room 02' },
    ]);
    expect(roomLayouts(entries.reverse(), 'iss-node')).toEqual([
      { id: 'layout-2', name: 'Room 01' }, { id: 'layout-10', name: 'Room 02' },
    ]);
  });
  it('identifies the no-fire control even when its incident metadata says overheating', () => {
    expect(scenarioName({ ...entry('control', 0), incident_type: 'overheating', ventilation_state: 'control', airflow_m_s: 0 }))
      .toBe('No-fire control · Fans off');
  });
  it('distinguishes opposite flow directions at the same speed', () => {
    const forward = { ...entry('fast', 0), airflow_m_s: 0.36, ventilation_state: 'fast' };
    expect(scenarioName(forward)).toBe('Electrical fire · High flow 36 cm/s');
    expect(scenarioName({ ...forward, ventilation_state: 'reverse', reverse_ventilation: true }))
      .toBe('Electrical fire · Reversed flow 36 cm/s');
  });
});
