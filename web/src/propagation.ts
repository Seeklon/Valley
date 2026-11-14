import { finite } from './data';
import type { Result, Run, RunConfig, Vec3 } from './types';

export type IncidentType = NonNullable<RunConfig['incident_type']>;
export interface IncidentComponent {
  id: string;
  scene_id: string;
  name: string;
  object_id: string | null;
  position_m: Vec3;
  kind: string;
  critical: boolean;
  provenance: string;
}
export interface IncidentsCatalog {
  version: string;
  incidents: {
    id: IncidentType;
    name: string;
    description: string;
    defaults: { ignition_power_w: number; ignition_duration_s: number };
    limitations: string[];
  }[];
  components: IncidentComponent[];
  model: {
    available: boolean;
    id: string;
    name: string;
    metrics?: Record<string, unknown>;
    quality_note?: string;
    limitations: string[];
    domain?: Record<string, unknown>;
  } | null;
  defaults: RunConfig;
}
export interface IncidentConsequences {
  heat_peak_c: number | null;
  hot_volume_peak_m3: number | null;
  smoke_peak_mg_m3: number | null;
  smoky_volume_peak_m3: number | null;
  exposed_equipment_count: number | null;
  critical_exposed_count: number | null;
  passages_exposed_count: number | null;
  first_exposure_s: number | null;
  thresholds: { temperature_c: number; smoke_mg_m3: number };
  basis: string;
}
export interface PropagationAssessment {
  config: RunConfig;
  components: { component_id: string; result: Result | null; error: string | null }[];
  model_id: string;
}
export interface PropagationSession {
  config: RunConfig | null;
  assessment: PropagationAssessment | null;
  simulation: Run | null;
}
export const EMPTY_PROPAGATION_SESSION: PropagationSession = {
  config: null,
  assessment: null,
  simulation: null,
};
export type ConsequenceMetric =
  'heat_peak_c' | 'smoke_peak_mg_m3' | 'exposed_equipment_count' | 'critical_exposed_count';
export const consequenceMetrics: {
  id: ConsequenceMetric;
  name: string;
  unit: string;
  min: number;
  max: number;
  decimals: number;
}[] = [
  { id: 'heat_peak_c', name: 'Pic de température', unit: '°C', min: 20, max: 600, decimals: 1 },
  { id: 'smoke_peak_mg_m3', name: 'Pic de fumée', unit: 'mg/m³', min: 0, max: 100, decimals: 1 },
  {
    id: 'exposed_equipment_count',
    name: 'Équipements exposés',
    unit: 'équipements',
    min: 0,
    max: 10,
    decimals: 0,
  },
  {
    id: 'critical_exposed_count',
    name: 'Équipements critiques exposés',
    unit: 'équipements',
    min: 0,
    max: 5,
    decimals: 0,
  },
];

/** A map changes with conditions, never just with which component is inspected. */
export function propagationKey(config: RunConfig, includeComponent = false): string {
  const values = Object.entries(config).filter(
    ([key, value]) =>
      value !== undefined &&
      !['mode', 'model_id', ...(includeComponent ? [] : ['component_id'])].includes(key),
  );
  return JSON.stringify(Object.fromEntries(values.sort(([a], [b]) => a.localeCompare(b))));
}
export function predictionMatches(
  assessment: PropagationAssessment | null,
  config: RunConfig | null,
): boolean {
  return Boolean(assessment && config && propagationKey(assessment.config) === propagationKey(config));
}
export function simulationMatches(run: Run | null, config: RunConfig | null): boolean {
  return Boolean(
    run?.config &&
    config?.component_id &&
    run.config.mode === 'physics' &&
    propagationKey(run.config, true) === propagationKey(config, true),
  );
}
export function simulationConfig(config: RunConfig, componentId: string): RunConfig {
  const { model_id: _model, ...conditions } = config;
  return { ...conditions, mode: 'physics', component_id: componentId };
}
export function consequencesOf(result: Result | null | undefined): Partial<IncidentConsequences> | null {
  const value = result?.summary?.consequences;
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Partial<IncidentConsequences>)
    : null;
}
export function consequenceValue(
  result: Result | null | undefined,
  metric: ConsequenceMetric,
): number | null {
  const value = consequencesOf(result)?.[metric];
  return finite(value) ? value : null;
}
/** Results identify the source actually applied to the solver's mesh. */
export function incidentSourcePosition(result: Result | null | undefined): Vec3 | null {
  const incident = result?.provenance.incident;
  if (!incident || typeof incident !== 'object' || !('source' in incident)) return null;
  const source = incident.source;
  if (!source || typeof source !== 'object' || !('position_m' in source)) return null;
  const position = source.position_m;
  return Array.isArray(position) && position.length === 3 && position.every(finite)
    ? [position[0], position[1], position[2]]
    : null;
}
export const CONSEQUENCE_GRADIENT =
  'linear-gradient(90deg, #567aab, #65c4ca 25%, #e5ca79 50%, #e38c62 75%, #dc6264)';
/** Fixed display limits are not fire-safety thresholds or probabilities. */
export function consequenceColor(value: number | null | undefined, metric: ConsequenceMetric): string {
  if (!finite(value)) return '#7e8d9a';
  const scale = consequenceMetrics.find((item) => item.id === metric)!;
  const fraction = Math.max(0, Math.min(1, (value - scale.min) / (scale.max - scale.min)));
  const colors = [
    [86, 122, 171],
    [101, 196, 202],
    [229, 202, 121],
    [227, 140, 98],
    [220, 98, 100],
  ];
  const index = Math.min(3, Math.floor(fraction * 4));
  return `rgb(${colors[index].map((channel, axis) => Math.round(channel + (colors[index + 1][axis] - channel) * (fraction * 4 - index))).join(',')})`;
}
export function propagationConfigIssue(config: RunConfig, catalog: IncidentsCatalog): string | null {
  if (!catalog.components.some((item) => item.scene_id === config.scene_id))
    return 'Aucun point de départ n’est renseigné pour cette scène.';
  if (
    !catalog.components.some((item) => item.scene_id === config.scene_id && item.id === config.component_id)
  )
    return 'Choisissez un point de départ renseigné pour cette scène.';
  if (!catalog.incidents.some((item) => item.id === config.incident_type))
    return 'Choisissez un type de départ dans le catalogue.';
  const constraints: [keyof RunConfig, number, number][] = [
    ['gravity_g', 0, 1],
    ['airflow_m_s', 0, 1],
    ['oxygen_percent', 15, 30],
    ['ignition_power_w', 0, 10000],
    ['ignition_duration_s', 0.1, 120],
    ['duration_s', 2, 180],
  ];
  if (
    constraints.some(
      ([key, min, max]) =>
        !finite(config[key]) || (config[key] as number) < min || (config[key] as number) > max,
    )
  )
    return 'Un paramètre est vide ou hors des bornes de calcul.';
  if (config.ignition_duration_s > config.duration_s)
    return 'Le départ doit se terminer dans la durée du scénario.';
  return null;
}
