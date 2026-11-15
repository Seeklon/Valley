import { describe, expect, it } from 'vitest';
import { defaultCase, environmentCases } from './catalog';
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
});
