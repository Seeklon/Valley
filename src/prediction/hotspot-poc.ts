import type { Vec3 } from './types';

export type PocSplit = 'train' | 'validation' | 'test';
type GravityGroups = Partial<Record<'microgravity' | 'earth', { f1: number | null }>>;

export interface HotspotMetrics {
  precision: number | null;
  recall: number | null;
  iou: number | null;
  false_positive_rate: number | null;
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  f1?: number | null;
  n_valid?: number;
  groups?: GravityGroups;
}

export interface HotspotCaseEntry {
  id: string;
  split: PocSplit;
  layout_id: string;
  family: string;
  gravity_g: number;
  incident_type: string;
  ambient_temperature_c: number;
  airflow_m_s: number;
  peak_temperature_c: number | null;
  metrics: HotspotMetrics;
  url: string;
  evaluation_role?: string;
}

export interface HotspotIndex {
  schema_version: 'hotspot-poc-1';
  generated_at: string;
  model: {
    id: string;
    name: string;
    trained_at?: string;
    device?: string;
    heat_delta_c: number;
    score_threshold: number;
    training_seconds?: number;
    weights_sha256?: string;
    dataset_sha256?: string;
  };
  metrics: Partial<Record<PocSplit, HotspotMetrics>>;
  baselines?: Partial<Record<PocSplit, { source_proximity?: { groups?: GravityGroups } }>>;
  cases: HotspotCaseEntry[];
  limitations: string[];
  metrics_time_filter?: string;
  default_case_id?: string;
  example_cases?: { representative?: string; failure?: string; cold_control?: string };
}

export interface HotspotFrame {
  time_s: number;
  temperature_c: (number | null)[];
  hotspot_score: (number | null)[];
  valid_mask?: boolean[];
  hotspot_truth?: (boolean | null)[];
  predicted_hot_mask?: (boolean | null)[];
}

export interface HotspotCase {
  id: string;
  scene: {
    id?: string;
    name?: string;
    bounds_m: Vec3;
    objects: {
      id: string;
      name?: string;
      role: string;
      material_id: string;
      combustible_material_id?: string | null;
      center_m: Vec3;
      size_m: Vec3;
    }[];
    vents: {
      id: string;
      role: 'inlet' | 'outlet';
      center_m: Vec3;
      size_m: Vec3;
      normal: Vec3;
    }[];
  };
  conditions: {
    ambient_temperature_c: number;
    gravity_g: number;
    airflow_m_s: number;
    oxygen_percent?: number;
    incident_type: string;
    source_position_m: Vec3;
    power_w?: number;
    source_duration_s?: number;
    duration_s?: number;
  };
  sample_positions_m: Vec3[];
  frames: HotspotFrame[];
  notes?: string[];
}

export type HotspotClass = 'tp' | 'fp' | 'fn' | 'tn';
export const HOTSPOT_COLORS: Record<HotspotClass, string> = {
  tp: '#ffb36d',
  fp: '#df83d1',
  fn: '#7cbbea',
  tn: '#45545e',
};
export const SPLIT_LABELS: Record<PocSplit, string> = {
  train: 'Entraînement',
  validation: 'Validation · choix du seuil',
  test: 'Hors entraînement · test historique déjà consulté',
};

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function ensure(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function record(value: unknown, path: string): Record<string, unknown> {
  ensure(value !== null && typeof value === 'object' && !Array.isArray(value), `${path} absent ou invalide.`);
  return value as Record<string, unknown>;
}

function nonempty(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function vector(value: unknown): value is Vec3 {
  return Array.isArray(value) && value.length === 3 && value.every(finite);
}

function validateMetrics(value: unknown, path: string): void {
  const metric = record(value, path);
  for (const key of ['precision', 'recall', 'iou', 'false_positive_rate']) {
    const n = metric[key];
    ensure(n === null || (finite(n) && n >= 0 && n <= 1), `${path}.${key} doit être un ratio ou null.`);
  }
  for (const key of ['tp', 'fp', 'fn', 'tn']) {
    const n = metric[key];
    ensure(finite(n) && Number.isInteger(n) && n >= 0, `${path}.${key} doit être un compte positif ou nul.`);
  }
  validateGravityGroups(metric, path);
}

function validateGravityGroups(value: Record<string, unknown>, path: string): void {
  if (value.groups === undefined) return;
  const groups = record(value.groups, `${path}.groups`);
  for (const gravity of ['microgravity', 'earth']) {
    if (groups[gravity] === undefined) continue;
    const group = record(groups[gravity], `${path}.groups.${gravity}`);
    ensure(
      group.f1 === null || (finite(group.f1) && group.f1 >= 0 && group.f1 <= 1),
      `${path}.groups.${gravity}.f1 doit être un ratio ou null.`,
    );
  }
}

/** Restrict replay downloads to this site's static POC export. */
export function hotspotCaseUrl(value: string): string {
  const relative = value.startsWith('./') ? value.slice(2) : value;
  const path = relative.startsWith('/') ? relative : `/poc/${relative}`;
  ensure(
    /^\/poc\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.json$/.test(path),
    'Adresse de cas hors du dossier POC.',
  );
  ensure(!path.split('/').includes('..'), 'Adresse de cas invalide.');
  return path;
}

export function parseHotspotIndex(value: unknown): HotspotIndex {
  const data = record(value, 'Export');
  ensure(data.schema_version === 'hotspot-poc-1', 'Version de l’export POC non prise en charge.');
  const model = record(data.model, 'Modèle');
  ensure(nonempty(model.id) && nonempty(model.name), 'Identité du modèle manquante.');
  ensure(finite(model.heat_delta_c) && model.heat_delta_c > 0, 'Seuil thermique manquant.');
  ensure(
    finite(model.score_threshold) && model.score_threshold >= 0 && model.score_threshold <= 1.00001,
    'Seuil du score invalide.',
  );
  ensure(nonempty(data.generated_at), 'Date d’export manquante.');
  const metrics = record(data.metrics, 'Métriques');
  for (const split of ['train', 'validation', 'test']) {
    if (metrics[split] !== undefined) validateMetrics(metrics[split], `Métriques ${split}`);
  }
  if (data.baselines !== undefined) {
    const baselines = record(data.baselines, 'Références simples');
    for (const split of ['train', 'validation', 'test']) {
      if (baselines[split] === undefined) continue;
      const baseline = record(baselines[split], `Références ${split}`);
      if (baseline.source_proximity !== undefined)
        validateGravityGroups(record(baseline.source_proximity, 'Proximité source'), `Proximité ${split}`);
    }
  }
  ensure(Array.isArray(data.cases), 'Liste des cas manquante.');
  const ids = new Set<string>();
  for (const raw of data.cases) {
    const item = record(raw, 'Cas');
    ensure(nonempty(item.id) && !ids.has(item.id), 'Identifiant de cas manquant ou répété.');
    ids.add(item.id);
    ensure(
      ['train', 'validation', 'test'].includes(String(item.split)),
      `Partition invalide pour ${item.id}.`,
    );
    ensure(
      nonempty(item.layout_id) && nonempty(item.family) && nonempty(item.incident_type),
      `Description manquante pour ${item.id}.`,
    );
    for (const key of ['ambient_temperature_c', 'gravity_g', 'airflow_m_s']) {
      ensure(finite(item[key]), `${item.id} : ${key} manquant.`);
    }
    ensure(item.peak_temperature_c === null || finite(item.peak_temperature_c), `${item.id} : pic invalide.`);
    ensure(nonempty(item.url), `${item.id} : fichier absent.`);
    hotspotCaseUrl(item.url);
    validateMetrics(item.metrics, `Cas ${item.id}`);
  }
  ensure(
    Array.isArray(data.limitations) && data.limitations.every((item) => typeof item === 'string'),
    'Limites de l’export manquantes.',
  );
  return value as HotspotIndex;
}

export function parseHotspotCase(value: unknown, expectedId: string): HotspotCase {
  const data = record(value, 'Cas');
  ensure(data.id === expectedId, 'Le fichier ne correspond pas au cas sélectionné.');
  const scene = record(data.scene, 'Scène');
  ensure(vector(scene.bounds_m) && scene.bounds_m.every((n) => n > 0), 'Dimensions de scène invalides.');
  ensure(Array.isArray(scene.objects) && Array.isArray(scene.vents), 'Géométrie physique absente.');
  for (const raw of scene.objects) {
    const item = record(raw, 'Objet');
    ensure(
      nonempty(item.id) && nonempty(item.material_id) && nonempty(item.role),
      'Annotation d’objet absente.',
    );
    ensure(
      vector(item.center_m) && vector(item.size_m) && item.size_m.every((n) => n > 0),
      'Dimensions d’objet invalides.',
    );
  }
  for (const raw of scene.vents) {
    const item = record(raw, 'Ventilation');
    ensure(
      nonempty(item.id) && ['inlet', 'outlet'].includes(String(item.role)),
      'Bouche de ventilation invalide.',
    );
    ensure(
      vector(item.center_m) && vector(item.size_m) && vector(item.normal),
      'Géométrie de ventilation invalide.',
    );
  }
  const conditions = record(data.conditions, 'Conditions');
  for (const key of ['ambient_temperature_c', 'gravity_g', 'airflow_m_s']) {
    ensure(finite(conditions[key]), `Condition ${key} manquante.`);
  }
  ensure(
    nonempty(conditions.incident_type) && vector(conditions.source_position_m),
    'Source incidente manquante.',
  );
  ensure(
    Array.isArray(data.sample_positions_m) &&
      data.sample_positions_m.length > 0 &&
      data.sample_positions_m.every(vector),
    'Positions des sondes invalides.',
  );
  ensure(Array.isArray(data.frames) && data.frames.length > 0, 'Aucun instant enregistré.');
  const count = data.sample_positions_m.length;
  let previous = -Infinity;
  for (const raw of data.frames) {
    const frame = record(raw, 'Instant');
    ensure(
      finite(frame.time_s) && frame.time_s >= 0 && frame.time_s > previous,
      'Les instants doivent être croissants et distincts.',
    );
    previous = frame.time_s;
    for (const key of ['temperature_c', 'hotspot_score']) {
      const values = frame[key];
      ensure(
        Array.isArray(values) && values.length === count,
        `${key} : nombre de valeurs différent du nombre de sondes.`,
      );
      ensure(
        values.every((n) => n === null || finite(n)),
        `${key} : valeur non numérique.`,
      );
      if (key === 'hotspot_score')
        ensure(
          values.every((n) => n === null || (n >= 0 && n <= 1)),
          'Score ML hors de [0, 1].',
        );
    }
    if (frame.valid_mask !== undefined) {
      ensure(
        Array.isArray(frame.valid_mask) &&
          frame.valid_mask.length === count &&
          frame.valid_mask.every((n) => typeof n === 'boolean'),
        'Masque de validité incompatible.',
      );
    }
    for (const key of ['hotspot_truth', 'predicted_hot_mask']) {
      const mask = frame[key];
      if (mask !== undefined)
        ensure(
          Array.isArray(mask) &&
            mask.length === count &&
            mask.every((n) => n === null || typeof n === 'boolean'),
          'Masque de classe incompatible.',
        );
    }
  }
  return value as HotspotCase;
}

/** Both panels use the same observed support. Never turn missing data into cold points. */
export function hotspotClass(
  frame: HotspotFrame,
  point: number,
  ambient: number,
  delta: number,
  threshold: number,
): HotspotClass | null {
  const temperature = frame.temperature_c[point];
  const score = frame.hotspot_score[point];
  if (frame.valid_mask?.[point] === false || !finite(temperature) || !finite(score)) return null;
  if (frame.hotspot_truth?.[point] === null || frame.predicted_hot_mask?.[point] === null) return null;
  const actual = frame.hotspot_truth?.[point] ?? temperature >= ambient + delta;
  const predicted = frame.predicted_hot_mask?.[point] ?? score >= threshold;
  return actual ? (predicted ? 'tp' : 'fn') : predicted ? 'fp' : 'tn';
}

export function metricsFromCounts(counts: Pick<HotspotMetrics, 'tp' | 'fp' | 'fn' | 'tn'>): HotspotMetrics {
  const { tp, fp, fn, tn } = counts;
  const ratio = (a: number, b: number) => (b > 0 ? a / b : null);
  return {
    ...counts,
    precision: ratio(tp, tp + fp),
    recall: ratio(tp, tp + fn),
    iou: ratio(tp, tp + fp + fn),
    false_positive_rate: ratio(fp, fp + tn),
    n_valid: tp + fp + fn + tn,
  };
}

export function hotspotFrameMetrics(
  frame: HotspotFrame,
  ambient: number,
  delta: number,
  threshold: number,
): HotspotMetrics {
  const counts = { tp: 0, fp: 0, fn: 0, tn: 0 };
  frame.temperature_c.forEach((_, index) => {
    const kind = hotspotClass(frame, index, ambient, delta, threshold);
    if (kind) counts[kind]++;
  });
  return metricsFromCounts(counts);
}

/** A presentation instant chosen from FDS alone, independently of ML quality. */
export function peakHotspotFrame(frames: HotspotFrame[]): number {
  let peak = -Infinity;
  let selected = 0;
  frames.forEach((frame, frameIndex) => {
    frame.temperature_c.forEach((value, point) => {
      if (frame.valid_mask?.[point] !== false && finite(value) && value > peak) {
        peak = value;
        selected = frameIndex;
      }
    });
  });
  return selected;
}

export function aggregateHotspotMetrics(cases: HotspotCaseEntry[]): HotspotMetrics | null {
  if (!cases.length) return null;
  const counts = { tp: 0, fp: 0, fn: 0, tn: 0 };
  for (const item of cases) {
    for (const key of ['tp', 'fp', 'fn', 'tn'] as const) counts[key] += item.metrics[key];
  }
  return metricsFromCounts(counts);
}

export function hotspotColdCaseAlarms(cases: HotspotCaseEntry[]) {
  const cold = cases.filter(({ metrics }) => metrics.tp + metrics.fn === 0 && metrics.fp + metrics.tn > 0);
  return { total: cold.length, alerted: cold.filter(({ metrics }) => metrics.fp > 0).length };
}

/** Compare reported F1 on one partition; never mix train and held-out results. */
export function hotspotBaselineRows(index: HotspotIndex, split: PocSplit | 'all') {
  if (split === 'all') return [];
  const model = index.metrics[split]?.groups;
  const baseline = index.baselines?.[split]?.source_proximity?.groups;
  if (!model?.microgravity || !model.earth || !baseline?.microgravity || !baseline.earth) return [];
  return (['microgravity', 'earth'] as const).map((gravity) => ({
    gravity,
    label: gravity === 'microgravity' ? 'Microgravité' : 'Terre',
    model_f1: model[gravity]!.f1,
    proximity_f1: baseline[gravity]!.f1,
  }));
}
