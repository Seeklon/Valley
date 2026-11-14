import { finite } from './data';
import type { Vec3 } from './types';

export interface PreventionConfig {
  scene_id: string;
  current_a: number;
  airflow_m_s: number;
  gravity_g: number;
  ambient_temperature_c: number;
  oxygen_percent: number;
  pressure_pa: number;
  duration_s: number;
  observation_cutoff_s: number;
  horizon_s: number;
  cutoff_s: number | null;
}

export interface PreventionComponent {
  id: string;
  scene_id: string;
  name: string;
  kind: 'wire' | 'battery';
  material_id: string;
  position_m: Vec3;
  object_id: string | null;
  current_factor: number;
  supported: boolean;
  provenance: string;
  limitations: string[];
}

export interface PreventionCatalog {
  version: 'ignis-prevention-1';
  scene_ids: string[];
  default_scene_id: string;
  components: PreventionComponent[];
  defaults: PreventionConfig;
  parameters: Record<string, { label: string; unit: string; min: number; max: number; step: number }>;
  models: Record<string, unknown>[];
  limitations: string[];
}

export interface ThermalPoint {
  time_s: number;
  current_a: number;
  conductor_temperature_c: number;
  surface_temperature_c: number;
  pyrolyzed_fraction: number;
}

export interface ComponentAssessment {
  component_id: string;
  status: 'available' | 'out_of_domain' | 'unsupported' | 'insufficient_history' | 'model_unavailable';
  reasons: string[];
  current_a: number;
  observations: ThermalPoint[];
  forecast: ThermalPoint[];
  learned_forecast: { time_s: number; surface_temperature_c: number }[];
  estimate: {
    ignition_delay_s: number;
    remaining_time_s: number;
    within_horizon: boolean;
    phase: 'before_estimated_ignition' | 'estimated_ignition_reached';
    model_id: string;
    domain: string;
    conditional_on: string;
  } | null;
  interval: { lower_s: number; upper_s: number; kind: string } | null;
  ignition_probability: null;
  thermal: {
    status: string;
    ignition_supported: false;
    summary: Record<string, unknown>;
    model_id: string | null;
    limitations: string[];
  } | null;
  evidence_ids: string[];
}

export interface PreventionResult {
  id: string;
  config: PreventionConfig;
  observation_cutoff_s: number;
  horizon_s: number;
  origin: 'simulation_and_published_experiments';
  target: { event_kind: 'ignition'; name: string; unit: 's'; criterion: string };
  components: ComponentAssessment[];
  evidence_snapshot?: PreventionEvidence;
  evidence_snapshots_by_component?: Record<string, PreventionEvidence>;
  provenance: Record<string, unknown>;
  limitations: string[];
  export_url: string;
}

export interface PreventionEvidence {
  findings: {
    id: string;
    source_id: string;
    title: string;
    statement: string;
    epistemic_status: string;
    relevance: string;
    reasons: string[];
    evidence_quality: string;
    is_nasa_source?: boolean;
    source: { name: string; url: string; locator: string };
    conditions: Record<string, unknown>;
    limitations: string[];
  }[];
  limitations: string[];
}

export interface PreventionInterpretation {
  summary: string;
  method: string;
  model: string | null;
  evidence_ids: string[];
  limitations: string[];
}

export const preventionStates = {
  unknown: { label: 'Allumage non estimé', color: '#7c8898' },
  within: { label: 'Instant estimé dans l’horizon', color: '#efb779' },
  beyond: { label: 'Instant estimé au-delà de l’horizon', color: '#7eb8d1' },
  reached: { label: 'Instant estimé atteint', color: '#eb9685' },
} as const;

export function preventionState(assessment?: ComponentAssessment) {
  const estimate = assessment?.status === 'available' ? assessment.estimate : null;
  if (!estimate || !finite(estimate.ignition_delay_s) || !finite(estimate.remaining_time_s)) return 'unknown';
  if (estimate.phase === 'estimated_ignition_reached') return 'reached';
  return estimate.within_horizon ? 'within' : 'beyond';
}

export const preventionStatusLabels: Record<ComponentAssessment['status'], string> = {
  available: 'Estimation dans le protocole couvert',
  out_of_domain: 'Hors du protocole d’allumage',
  unsupported: 'Mécanisme non pris en charge',
  insufficient_history: 'Historique insuffisant',
  model_unavailable: 'Modèle d’allumage indisponible',
};

export function observationPrefix<T extends { time_s: number }>(rows: T[], cutoff: number): T[] {
  return rows.filter((row) => finite(row.time_s) && row.time_s <= cutoff).sort((a, b) => a.time_s - b.time_s);
}

export function futureSuffix<T extends { time_s: number }>(rows: T[], cutoff: number): T[] {
  return rows.filter((row) => finite(row.time_s) && row.time_s > cutoff).sort((a, b) => a.time_s - b.time_s);
}

export function comparisonIssue(
  current: PreventionResult,
  baseline: PreventionResult,
  componentId: string,
): string | null {
  if (current.config.scene_id !== baseline.config.scene_id) return 'Les scènes diffèrent.';
  if (
    current.observation_cutoff_s !== baseline.observation_cutoff_s ||
    current.horizon_s !== baseline.horizon_s
  )
    return 'L’instant de prévision et l’horizon doivent être identiques.';
  if (
    current.target.event_kind !== baseline.target.event_kind ||
    current.target.unit !== baseline.target.unit ||
    current.target.criterion !== baseline.target.criterion
  )
    return 'Les critères d’événement diffèrent.';
  const next = current.components.find((item) => item.component_id === componentId);
  const before = baseline.components.find((item) => item.component_id === componentId);
  if (!next || !before) return 'Le composant doit être présent dans les deux analyses.';
  if (next.status !== 'available' || before.status !== 'available' || !next.estimate || !before.estimate)
    return 'Le délai n’est pas disponible dans le même protocole pour les deux scénarios.';
  if (!finite(next.estimate.ignition_delay_s) || !finite(before.estimate.ignition_delay_s))
    return 'Les deux délais doivent être renseignés.';
  if (next.estimate.model_id !== before.estimate.model_id || next.estimate.domain !== before.estimate.domain)
    return 'Les modèles ou domaines d’allumage diffèrent.';
  return null;
}

export function preventionConfigIssue(config: PreventionConfig, catalog: PreventionCatalog): string | null {
  if (!catalog.scene_ids.includes(config.scene_id))
    return 'Cette scène ne figure pas dans le catalogue de prévention.';
  for (const [key, parameter] of Object.entries(catalog.parameters)) {
    const value = config[key as keyof PreventionConfig];
    if (key === 'cutoff_s' && value === null) continue;
    if (typeof value !== 'number' || !finite(value) || value < parameter.min || value > parameter.max)
      return `${parameter.label} : valeur hors des bornes du catalogue.`;
  }
  if (config.observation_cutoff_s + config.horizon_s > config.duration_s)
    return 'L’instant de prévision et l’horizon dépassent la durée du scénario.';
  if (config.cutoff_s !== null && (config.cutoff_s < 0 || config.cutoff_s > config.duration_s))
    return 'La coupure électrique doit être comprise dans la durée du scénario.';
  return null;
}
