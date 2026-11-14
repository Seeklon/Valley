import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from './data';
import {
  consequenceColor,
  consequenceValue,
  incidentSourcePosition,
  predictionMatches,
  propagationConfigIssue,
  simulationConfig,
  simulationMatches,
} from './propagation';
import type { IncidentsCatalog, PropagationAssessment } from './propagation';
import type { Result, Run, RunConfig } from './types';

const config: RunConfig = {
  ...DEFAULT_CONFIG,
  scene_id: 'soyuz',
  mode: 'prediction',
  model_id: 'incident-field-v1',
  component_id: 'console-left',
  incident_type: 'arc',
  ignition_power_w: 1000,
  ignition_duration_s: 10,
  duration_s: 30,
  mesh_cell_m: 0.2,
  sample_shape: [12, 10, 8],
};
const assessment: PropagationAssessment = { config, components: [], model_id: 'incident-field-v1' };
const run: Run = {
  id: 'physical-run',
  status: 'completed',
  config: simulationConfig(config, 'console-left'),
};
const catalog: IncidentsCatalog = {
  version: 'test',
  incidents: [
    {
      id: 'arc',
      name: 'Arc',
      description: '',
      limitations: [],
      defaults: { ignition_power_w: 1000, ignition_duration_s: 10 },
    },
  ],
  components: [
    {
      id: 'console-left',
      scene_id: 'soyuz',
      name: 'Console gauche',
      object_id: null,
      position_m: [1, 2, 3],
      kind: 'electrical',
      critical: true,
      provenance: 'test',
    },
  ],
  model: { available: false, id: 'incident-field-v1', name: 'Absent', limitations: [] },
  defaults: config,
};
const result = (consequences: Record<string, unknown>): Result => ({
  provenance: { engine: 'test' },
  metrics: [],
  frames: [],
  summary: { consequences },
});

describe('propagation session boundaries', () => {
  it('keeps an all-component map while inspecting another component or preparing physics', () => {
    expect(predictionMatches(assessment, { ...config, component_id: 'console-right' })).toBe(true);
    expect(predictionMatches(assessment, simulationConfig(config, 'console-right'))).toBe(true);
    expect(predictionMatches(null, config)).toBe(false);
    expect(predictionMatches(assessment, null)).toBe(false);
  });

  it.each<Partial<RunConfig>>([
    { scene_id: 'cargo' },
    { incident_type: 'battery' },
    { gravity_g: 1 },
    { airflow_m_s: 0.4 },
    { oxygen_percent: 25 },
    { ignition_power_w: 1500 },
    { ignition_duration_s: 5 },
    { duration_s: 60 },
    { material_id: 'pmma' },
    { mesh_cell_m: 0.1 },
    { sample_shape: [24, 10, 8] },
    { seed: 43 },
  ])('hides old predictions and physics when a physical condition changes: %j', (patch) => {
    expect(predictionMatches(assessment, { ...config, ...patch })).toBe(false);
    expect(simulationMatches(run, { ...config, ...patch })).toBe(false);
  });

  it('requires the exact component and a physical run for the Simulation page', () => {
    expect(simulationMatches(run, config)).toBe(true);
    expect(simulationMatches(run, { ...config, component_id: 'console-right' })).toBe(false);
    expect(simulationMatches({ ...run, config }, config)).toBe(false);
    expect(simulationMatches({ ...run, config: undefined }, config)).toBe(false);
    expect(simulationMatches(null, config)).toBe(false);
  });

  it('transfers every physical setting without mutating the selected scenario', () => {
    const original = structuredClone(config);
    const transferred = simulationConfig(config, 'console-right');
    expect(transferred).toEqual({
      ...config,
      mode: 'physics',
      component_id: 'console-right',
      model_id: undefined,
    });
    expect(Object.hasOwn(transferred, 'model_id')).toBe(false);
    expect(config).toEqual(original);
    expect(transferred).not.toBe(config);
  });
});

describe('honest consequence display', () => {
  it('keeps a legitimate zero distinct from missing, null and nonfinite values', () => {
    expect(consequenceValue(result({ exposed_equipment_count: 0 }), 'exposed_equipment_count')).toBe(0);
    for (const value of [undefined, null, NaN, Infinity, '0']) {
      expect(consequenceValue(result({ heat_peak_c: value }), 'heat_peak_c')).toBeNull();
      expect(
        consequenceColor(consequenceValue(result({ heat_peak_c: value }), 'heat_peak_c'), 'heat_peak_c'),
      ).toBe('#7e8d9a');
    }
    expect(consequenceValue(undefined, 'smoke_peak_mg_m3')).toBeNull();
    expect(consequenceColor(0, 'exposed_equipment_count')).not.toBe('#7e8d9a');
  });

  it('uses fixed display limits and saturates rather than renormalizing the map', () => {
    expect(consequenceColor(20, 'heat_peak_c')).toBe('rgb(86,122,171)');
    expect(consequenceColor(310, 'heat_peak_c')).toBe('rgb(229,202,121)');
    expect(consequenceColor(600, 'heat_peak_c')).toBe('rgb(220,98,100)');
    expect(consequenceColor(900, 'heat_peak_c')).toBe(consequenceColor(600, 'heat_peak_c'));
    expect(consequenceColor(50, 'smoke_peak_mg_m3')).toBe('rgb(229,202,121)');
  });

  it('places the result marker at the applied source rather than the requested annotation', () => {
    const actual = result({});
    actual.provenance.incident = {
      source: { requested_position_m: [1, 2, 3], position_m: [1.1, 2.1, 3.1] },
    };
    expect(incidentSourcePosition(actual)).toEqual([1.1, 2.1, 3.1]);
    for (const position of [undefined, [1, 2], [1, 2, NaN], ['1', 2, 3]]) {
      actual.provenance.incident = { source: { position_m: position } };
      expect(incidentSourcePosition(actual)).toBeNull();
    }
    expect(incidentSourcePosition(result({}))).toBeNull();
  });
});

describe('propagation input validation', () => {
  it('accepts a catalog whose unavailable model has no metrics or domain', () => {
    expect(propagationConfigIssue(config, catalog)).toBeNull();
  });

  it.each<Partial<RunConfig>>([
    { ignition_duration_s: 31 },
    { duration_s: NaN },
    { oxygen_percent: 0 },
    { scene_id: 'missing' },
    { component_id: 'other-scene-component' },
    { incident_type: undefined },
  ])('rejects incomplete or inconsistent inputs: %j', (patch) => {
    expect(propagationConfigIssue({ ...config, ...patch }, catalog)).toBeTruthy();
  });
});
