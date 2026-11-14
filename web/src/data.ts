import type { Frame, Metric, ModelInfo, RunConfig, Vec3 } from './types';

export const DEFAULT_CONFIG: RunConfig = {
  scene_id: 'habitat',
  mode: 'physics',
  source_model: 'prescribed_source',
  gravity_g: 0.0001,
  airflow_m_s: 0.2,
  oxygen_percent: 21,
  material_id: 'cellulose',
  ignition_power_w: 500,
  ignition_duration_s: 15,
  duration_s: 60,
  seed: 42,
  ignition_kind: 'thermal',
  current_a: 5,
  resistance_ohm: 20,
};

export function toWorld(point: Vec3): Vec3 {
  return [point[0], point[2], -point[1]];
}

export function voxelPosition(index: number, shape: Vec3, bounds: Vec3): Vec3 {
  const z = index % shape[2];
  const y = Math.floor(index / shape[2]) % shape[1];
  const x = Math.floor(index / (shape[1] * shape[2]));
  return [
    ((x + 0.5) * bounds[0]) / shape[0],
    ((y + 0.5) * bounds[1]) / shape[1],
    ((z + 0.5) * bounds[2]) / shape[2],
  ];
}

export function nearestByTime<T extends { time_s: number }>(items: T[], time: number): T | undefined {
  let best: T | undefined;
  let distance = Infinity;
  for (const item of items) {
    const next = Math.abs(item.time_s - time);
    if (next < distance) {
      best = item;
      distance = next;
    }
  }
  return best;
}

export function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}
export function format(value: unknown, decimals = 1): string {
  return finite(value)
    ? value.toLocaleString('fr-FR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : '—';
}

export function usableModel(model: ModelInfo): boolean {
  return (
    model.loaded === true &&
    model.available !== false &&
    !['failed', 'unavailable', 'error'].includes(model.status ?? '')
  );
}

export function domainWarnings(config: RunConfig, models: ModelInfo[]): string[] {
  if (config.mode !== 'prediction') return [];
  const available = models.filter(usableModel);
  if (config.model_id && !available.some((model) => model.id === config.model_id))
    return ['Le modèle sélectionné n’est plus chargé. Choisissez un modèle disponible.'];
  if (!available.length) return [];
  const first = available.find((model) => model.id === config.model_id) ?? available[0];
  const warnings: string[] = [];
  const domain = first.domain ?? {};
  const labels: Record<string, string> = {
    scene_id: 'Scène',
    material_id: 'Matériau',
    gravity_g: 'Gravité',
    source_model: 'Source de combustion',
    airflow_m_s: 'Ventilation',
    oxygen_percent: 'Oxygène',
    ignition_power_w: 'Puissance',
    ignition_duration_s: 'Durée de la source',
    duration_s: 'Durée du calcul',
  };
  const discrete: [string, unknown][] = [
    ['scene_id', domain.scene_ids],
    ['material_id', domain.materials],
    ['gravity_g', domain.gravity_values],
  ];
  for (const [key, values] of discrete) {
    const value = config[key as keyof RunConfig];
    if (
      Array.isArray(values) &&
      !values.some((allowed: unknown) =>
        finite(value) && finite(allowed) ? Math.abs(value - allowed) < 1e-8 : value === allowed,
      )
    ) {
      warnings.push(`${labels[key]} : cette valeur n’appartient pas aux conditions d’entraînement.`);
    }
  }
  const ranges =
    domain.ranges && typeof domain.ranges === 'object' && !Array.isArray(domain.ranges)
      ? (domain.ranges as Record<string, unknown>)
      : {};
  for (const [key, allowed] of Object.entries({ ...domain, ...ranges })) {
    const value = config[key as keyof RunConfig];
    const label = labels[key] ?? key;
    if (value === undefined) continue;
    if (Array.isArray(allowed) && allowed.length === 2 && allowed.every(finite) && finite(value)) {
      if (value < allowed[0] || value > allowed[1])
        warnings.push(`${label} : ${value} hors de [${allowed[0]}, ${allowed[1]}].`);
    } else if (Array.isArray(allowed) && !allowed.includes(value))
      warnings.push(`${label} : cette valeur n’appartient pas au domaine d’entraînement.`);
    else if (allowed && typeof allowed === 'object' && !Array.isArray(allowed) && finite(value)) {
      const range = allowed as { min?: number; max?: number };
      if ((finite(range.min) && value < range.min) || (finite(range.max) && value > range.max))
        warnings.push(`${label} : hors de la plage d’entraînement.`);
    } else if ((typeof allowed === 'string' || typeof allowed === 'boolean') && value !== allowed) {
      warnings.push(`${label} : cette configuration n’est pas prise en charge par le modèle.`);
    }
  }
  return warnings;
}

export function fieldAvailable(frame: Frame | undefined, field: string): boolean {
  if (field === 'scene') return true;
  if (!frame) return false;
  const arrays: Record<string, (number | null)[] | undefined> = {
    temperature: frame.temperature_c,
    airflow: frame.velocity_m_s,
    smoke: frame.smoke_kg_m3,
    oxygen: frame.oxygen_percent,
  };
  const values = arrays[field];
  if (!values?.length) return false;
  const count = frame.shape[0] * frame.shape[1] * frame.shape[2];
  for (let index = 0; index < count; index++) {
    if (frame.valid_mask?.[index] === false) continue;
    if (field === 'airflow') {
      if (finite(values[index * 3]) && finite(values[index * 3 + 1]) && finite(values[index * 3 + 2]))
        return true;
    } else if (finite(values[index])) return true;
  }
  return false;
}

export function metricPath(
  rows: Metric[],
  key: keyof Metric,
  width: number,
  height: number,
  domain: [number, number],
  maxTime: number,
): string {
  let path = '';
  let connected = false;
  for (const row of rows) {
    const value = row[key];
    if (!finite(value) || !finite(row.time_s)) {
      connected = false;
      continue;
    }
    const x = (row.time_s / Math.max(0.001, maxTime)) * width;
    const y = height - ((value - domain[0]) / Math.max(0.001, domain[1] - domain[0])) * height;
    path += `${connected ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)} `;
    connected = true;
  }
  return path.trim();
}
