import { decodeIssCase, issCaseUrl, parseIssIndex } from './iss-poc';
import type { IssCaseEntry, IssIndex } from './iss-poc';
import { caseBytes } from './case-cache';

export type Environment = 'iss' | 'moon' | 'earth';
export type Room = 'prev' | 'det' | 'sup' | 'fun' | 'si';
export const ROOM_FAMILY: Record<Room, string> = {
  prev: 'habitat-cargo', det: 'iss-node', sup: 'iss-service',
  fun: 'iss-laboratory', si: 'habitat-central-racks',
};
export const FAMILY_NAMES: Record<string, string> = {
  'habitat-cargo': 'Cargo compartment', 'habitat-capsule': 'Crew capsule',
  'habitat-central-racks': 'Central equipment', 'iss-laboratory': 'Laboratory',
  'iss-node': 'Connecting node', 'iss-service': 'Service compartment',
};
export const INCIDENT_NAMES: Record<string, string> = {
  flaming: 'Electrical fire', overheating: 'Overheating', arc: 'Electrical arc',
  smoldering: 'Smouldering', battery: 'Battery incident', none: 'No-fire control',
};

/** Stable room numbers within a compartment; ventilation variants share a room. */
export function roomLayouts(entries: IssCaseEntry[], family: string) {
  return [...new Set(entries.filter(entry => entry.family === family).map(entry => entry.layout_id))]
    .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }))
    .map((id, i) => ({ id, name: `Room ${String(i + 1).padStart(2, '0')}` }));
}

export function scenarioName(entry: IssCaseEntry) {
  // The ventilation export labels control incidents as overheating, but has no active source.
  const incident = entry.ventilation_state === 'control' || entry.incident_type === 'none'
    ? 'No-fire control' : INCIDENT_NAMES[entry.incident_type ?? ''] ?? 'Electrical incident';
  const speed = entry.airflow_m_s == null ? '' : `${+(entry.airflow_m_s * 100).toFixed(1)} cm/s`;
  const ventilation = entry.ventilation_state === 'still' || entry.airflow_m_s === 0 ? 'Fans off'
    : entry.reverse_ventilation || entry.ventilation_state === 'reverse' ? `Reversed flow ${speed}`
    : entry.ventilation_state === 'slow' ? `Low flow ${speed}`
    : entry.ventilation_state === 'fast' ? `High flow ${speed}` : speed ? `Airflow ${speed}` : '';
  return [incident, ventilation].filter(Boolean).join(' · ');
}

// Do not relabel a microgravity prediction as a lunar or terrestrial prediction.
export function environmentCases(index: IssIndex, environment: Environment): IssCaseEntry[] {
  return index.cases.filter(entry => environment === 'iss' ? entry.gravity_g < 0.01
    : Math.abs(entry.gravity_g - (environment === 'earth' ? 1 : 1 / 6)) < 0.02);
}

export function defaultCase(index: IssIndex, entries: IssCaseEntry[], family: string) {
  const matching = entries.filter(entry => entry.family === family);
  const example = index.example_cases?.modules?.[family];
  return matching.find(entry => entry.id === example)
    ?? matching.find(entry => entry.split === 'validation' && entry.incident_type === 'flaming')
    ?? matching.find(entry => entry.split === 'validation') ?? matching[0] ?? entries[0];
}

export function assetUrl(path: string) {
  // The original site supports deployment below a path, not just the domain root.
  const base = new URL(import.meta.env.BASE_URL, document.baseURI);
  return new URL(path.replace(/^\//, ''), base).href;
}

export async function loadIndex(signal: AbortSignal) {
  const response = await fetch(assetUrl('poc/iss/index.json'), { signal, cache: 'no-store' });
  if (!response.ok) throw new Error('Model export unavailable. Import the verified prediction bundle.');
  return parseIssIndex(await response.json());
}

export async function loadCase(entry: IssCaseEntry, index: IssIndex, signal: AbortSignal) {
  const bytes = await caseBytes(assetUrl(issCaseUrl(entry.url)), entry.sha256, signal);
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  return decodeIssCase(bytes, entry, index.model);
}
