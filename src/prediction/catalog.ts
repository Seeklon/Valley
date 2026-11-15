import { decodeIssCase, issCaseUrl, parseIssIndex } from './iss-poc';
import type { IssCaseEntry, IssIndex } from './iss-poc';

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
  const response = await fetch(assetUrl(issCaseUrl(entry.url)), { signal, cache: 'no-cache' });
  if (!response.ok) throw new Error('Scenario unavailable. Reload the complete model export.');
  return decodeIssCase(await response.arrayBuffer(), entry, index.model);
}
