import { describe, expect, it } from 'vitest';
import {
  comparisonIssue,
  futureSuffix,
  observationPrefix,
  preventionConfigIssue,
  preventionState,
} from './prevention';
import type { ComponentAssessment, PreventionCatalog, PreventionResult } from './prevention';

const config = {
  scene_id: 'soyuz',
  current_a: 5,
  airflow_m_s: 0,
  gravity_g: 0.0001,
  ambient_temperature_c: 20,
  oxygen_percent: 21,
  pressure_pa: 101325,
  duration_s: 20,
  observation_cutoff_s: 0.5,
  horizon_s: 5,
  cutoff_s: null,
};
const component: ComponentAssessment = {
  component_id: 'wire',
  status: 'available',
  reasons: [],
  current_a: 5,
  observations: [],
  forecast: [],
  learned_forecast: [],
  estimate: {
    ignition_delay_s: 3,
    remaining_time_s: 2.5,
    within_horizon: true,
    phase: 'before_estimated_ignition',
    model_id: 'experimental-delay',
    domain: 'NiCr/LDPE constant current',
    conditional_on: 'Constant current maintained',
  },
  interval: null,
  ignition_probability: null,
  thermal: null,
  evidence_ids: [],
};
const result: PreventionResult = {
  id: 'a',
  config,
  observation_cutoff_s: 0.5,
  horizon_s: 5,
  origin: 'simulation_and_published_experiments',
  target: { event_kind: 'ignition', name: 'Ignition', unit: 's', criterion: 'Observed ignition' },
  components: [component],
  provenance: {},
  limitations: [],
  export_url: '/api/prevention/analyses/a/export',
};

describe('frontière temporelle des données de prévention', () => {
  const rows = [
    { time_s: 1, value: 'future' },
    { time_s: 0, value: 'past' },
    { time_s: 0.5, value: 'boundary' },
    { time_s: NaN, value: 'invalid' },
  ];
  it('garde le point de frontière dans le passé et interdit les observations futures', () => {
    expect(observationPrefix(rows, 0.5).map((row) => row.value)).toEqual(['past', 'boundary']);
    expect(rows[0].value).toBe('future');
  });
  it('conserve seulement les prévisions strictement futures sans inventer de point à la frontière', () => {
    expect(futureSuffix(rows, 0.5)).toEqual([{ time_s: 1, value: 'future' }]);
    expect(futureSuffix([{ time_s: 0.4 }, { time_s: 0.5 }], 0.5)).toEqual([]);
  });
});

describe('états de composant et absence de quantification', () => {
  it('garde le gris si le modèle, le mécanisme ou le délai est indisponible', () => {
    expect(preventionState()).toBe('unknown');
    for (const status of [
      'out_of_domain',
      'unsupported',
      'insufficient_history',
      'model_unavailable',
    ] as const)
      expect(preventionState({ ...component, status })).toBe('unknown');
    expect(preventionState({ ...component, estimate: null })).toBe('unknown');
    expect(
      preventionState({ ...component, estimate: { ...component.estimate!, ignition_delay_s: NaN } }),
    ).toBe('unknown');
  });
  it('distingue un instant estimé dans l’horizon, au-delà et déjà atteint', () => {
    expect(preventionState(component)).toBe('within');
    expect(
      preventionState({ ...component, estimate: { ...component.estimate!, within_horizon: false } }),
    ).toBe('beyond');
    expect(
      preventionState({
        ...component,
        estimate: { ...component.estimate!, remaining_time_s: -1, phase: 'estimated_ignition_reached' },
      }),
    ).toBe('reached');
    expect(component.interval).toBeNull();
    expect(component.ignition_probability).toBeNull();
  });
});

describe('comparaisons physiquement comparables', () => {
  it('permet de comparer deux charges avec le même modèle et domaine', () => {
    expect(
      comparisonIssue({ ...result, id: 'b', config: { ...config, current_a: 7 } }, result, 'wire'),
    ).toBeNull();
  });
  it('refuse des instants, horizons, scènes ou critères différents', () => {
    for (const next of [
      { ...result, observation_cutoff_s: 1 },
      { ...result, horizon_s: 10 },
      { ...result, config: { ...config, scene_id: 'cargo' } },
      { ...result, target: { ...result.target, criterion: 'Temperature threshold' } },
    ])
      expect(comparisonIssue(next, result, 'wire')).not.toBeNull();
  });
  it('refuse un résultat hors domaine, un autre modèle ou un composant absent', () => {
    for (const assessment of [
      { ...component, status: 'out_of_domain' as const },
      { ...component, estimate: { ...component.estimate!, model_id: 'other' } },
      { ...component, estimate: { ...component.estimate!, domain: 'other' } },
      { ...component, estimate: { ...component.estimate!, ignition_delay_s: NaN } },
    ])
      expect(comparisonIssue({ ...result, components: [assessment] }, result, 'wire')).not.toBeNull();
    expect(comparisonIssue({ ...result, components: [] }, result, 'wire')).not.toBeNull();
  });
});

describe('bornes du catalogue et fenêtre du scénario', () => {
  const catalog: PreventionCatalog = {
    version: 'ignis-prevention-1',
    scene_ids: ['soyuz'],
    default_scene_id: 'soyuz',
    components: [],
    defaults: config,
    parameters: {
      current_a: { label: 'Courant', unit: 'A', min: 0, max: 12, step: 0.1 },
      cutoff_s: { label: 'Coupure', unit: 's', min: 0.1, max: 60, step: 0.1 },
    },
    models: [],
    limitations: [],
  };
  it('utilise les bornes serveur et n’accepte pas un champ vide ou une valeur non finie', () => {
    expect(preventionConfigIssue(config, catalog)).toBeNull();
    expect(preventionConfigIssue({ ...config, current_a: 12 }, catalog)).toBeNull();
    expect(preventionConfigIssue({ ...config, current_a: 12.1 }, catalog)).toContain('Courant');
    expect(preventionConfigIssue({ ...config, current_a: NaN }, catalog)).toContain('Courant');
    expect(preventionConfigIssue({ ...config, scene_id: 'unknown' }, catalog)).not.toBeNull();
  });
  it('rejette horizon et coupure au-delà de la durée tout en autorisant la borne exacte', () => {
    expect(preventionConfigIssue({ ...config, observation_cutoff_s: 15 }, catalog)).toBeNull();
    expect(preventionConfigIssue({ ...config, observation_cutoff_s: 15.1 }, catalog)).not.toBeNull();
    expect(preventionConfigIssue({ ...config, cutoff_s: 20 }, catalog)).toBeNull();
    expect(preventionConfigIssue({ ...config, cutoff_s: 21 }, catalog)).not.toBeNull();
  });
});
