import type { HotspotCase, HotspotClass, HotspotMetrics, PocSplit } from './hotspot-poc';
import { metricsFromCounts } from './hotspot-poc';
import type { Vec3 } from './types';

export type IssChannel = 'heat' | 'smoke';
export type IssDisplay = 'prediction' | 'reference' | 'errors';
export type IssMetrics = Record<IssChannel, HotspotMetrics>;
export type IssScene = Omit<HotspotCase['scene'], 'objects'> & {
  objects: (HotspotCase['scene']['objects'][number] & { thermal_thickness_m?: number | null })[];
};

export interface IssModel {
  id: string;
  name?: string;
  weights_sha256: string;
  dataset_sha256: string;
  device?: string;
  training_seconds?: number;
  heat_delta_c: number;
  smoke_threshold_kg_m3: number;
  score_thresholds: Record<IssChannel, number>;
}

export interface IssCaseEntry {
  id: string;
  split: PocSplit;
  layout_id: string;
  module_id: string;
  family: string;
  gravity_g: number;
  incident_type?: string;
  airflow_m_s?: number;
  url: string;
  sha256: string;
  metrics: IssMetrics;
}

export interface IssIndex {
  schema_version: 'iss-poc-1';
  generated_at?: string;
  model: IssModel;
  cases: IssCaseEntry[];
  metrics: Partial<Record<PocSplit, IssMetrics>>;
  default_case_id?: string | null;
  example_cases?: {
    modules?: Record<string, string | null>;
    representative?: string | null;
    failure?: string | null;
    cold_control?: string | null;
  };
  limitations?: string[];
}

export interface IssFrame {
  time_s: number;
  temperature_c: (number | null)[];
  soot_kg_m3: (number | null)[];
  heat_score: (number | null)[];
  smoke_score: (number | null)[];
  heat_valid_mask: boolean[];
  smoke_valid_mask: boolean[];
  hotspot_truth?: (boolean | null)[];
  smoke_truth?: (boolean | null)[];
  predicted_hot_mask?: (boolean | null)[];
  predicted_smoke_mask?: (boolean | null)[];
}

export interface IssCase {
  schema_version: 'iss-poc-1';
  id: string;
  layout_id: string;
  module_id: string;
  score_thresholds: Record<IssChannel, number>;
  heat_delta_c: number;
  smoke_threshold_kg_m3: number;
  scene: IssScene;
  conditions: HotspotCase['conditions'];
  sample_positions_m: Vec3[];
  frames: IssFrame[];
  notes?: string[];
}

export const ISS_SPLIT_LABELS: Record<PocSplit, string> = {
  train: 'Entraînement',
  validation: 'Validation · réglage du modèle',
  test: 'Test · géométries réservées',
};

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const nonempty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const vector = (value: unknown): value is Vec3 =>
  Array.isArray(value) && value.length === 3 && value.every(finite);
function ensure(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}
function record(value: unknown, path: string): Record<string, unknown> {
  ensure(value !== null && typeof value === 'object' && !Array.isArray(value), `${path} absent ou invalide.`);
  return value as Record<string, unknown>;
}

/** Physical coordinates in metres, Z up. This is the glTF/THREE axis conversion, with no rescaling. */
export function issToWorld([x, y, z]: Vec3): Vec3 {
  return [x, z, -y];
}

export function issCaseUrl(value: string): string {
  const relative = value.startsWith('./') ? value.slice(2) : value;
  const path = relative.startsWith('/') ? relative : `/poc/iss/${relative}`;
  ensure(
    /^\/poc\/iss\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.json$/.test(path),
    'Adresse hors de l’export ISS.',
  );
  ensure(!path.split('/').includes('..'), 'Adresse de cas ISS invalide.');
  return path;
}

function validateMetrics(value: unknown, path: string) {
  const channels = record(value, path);
  for (const channel of ['heat', 'smoke']) {
    const metric = record(channels[channel], `${path}.${channel}`);
    for (const key of ['tp', 'fp', 'fn', 'tn'])
      ensure(
        finite(metric[key]) && Number.isInteger(metric[key]) && metric[key] >= 0,
        `${path}.${channel}.${key} invalide.`,
      );
    for (const key of ['precision', 'recall', 'iou', 'false_positive_rate', 'f1']) {
      if (key === 'f1' && metric[key] === undefined) continue;
      ensure(
        metric[key] === null || (finite(metric[key]) && metric[key] >= 0 && metric[key] <= 1),
        `${path}.${channel}.${key} doit être un ratio ou null.`,
      );
    }
  }
}

export function parseIssIndex(value: unknown): IssIndex {
  const data = record(value, 'Export ISS');
  ensure(data.schema_version === 'iss-poc-1', 'Version de l’export ISS non prise en charge.');
  const model = record(data.model, 'Modèle');
  ensure(nonempty(model.id), 'Identité du modèle absente.');
  for (const key of ['weights_sha256', 'dataset_sha256'])
    ensure(
      typeof model[key] === 'string' && /^[a-f0-9]{64}$/i.test(model[key]),
      `Empreinte ${key} absente ou invalide.`,
    );
  ensure(finite(model.heat_delta_c) && model.heat_delta_c > 0, 'Seuil thermique invalide.');
  ensure(finite(model.smoke_threshold_kg_m3) && model.smoke_threshold_kg_m3 > 0, 'Seuil de suie invalide.');
  const thresholds = record(model.score_thresholds, 'Seuils ML');
  for (const channel of ['heat', 'smoke'])
    ensure(
      finite(thresholds[channel]) && thresholds[channel] >= 0 && thresholds[channel] <= 1.00001,
      `Seuil ${channel} invalide.`,
    );
  const metrics = record(data.metrics, 'Métriques');
  for (const split of ['train', 'validation', 'test'])
    if (metrics[split] !== undefined) validateMetrics(metrics[split], `Métriques ${split}`);
  ensure(Array.isArray(data.cases) && data.cases.length > 0, 'Aucun scénario ISS exporté.');
  const ids = new Set<string>();
  for (const raw of data.cases) {
    const item = record(raw, 'Scénario');
    ensure(nonempty(item.id) && !ids.has(item.id), 'Identifiant de scénario absent ou répété.');
    ids.add(item.id);
    for (const key of ['layout_id', 'module_id', 'family', 'url'])
      ensure(nonempty(item[key]), `${item.id} : ${key} absent.`);
    ensure(['train', 'validation', 'test'].includes(String(item.split)), `${item.id} : partition invalide.`);
    ensure(finite(item.gravity_g) && item.gravity_g >= 0, `${item.id} : gravité invalide.`);
    issCaseUrl(item.url as string);
    ensure(
      typeof item.sha256 === 'string' && /^[a-f0-9]{64}$/i.test(item.sha256),
      `${item.id} : empreinte du fichier absente ou invalide.`,
    );
    validateMetrics(item.metrics, item.id);
  }
  if (data.default_case_id != null)
    ensure(
      typeof data.default_case_id === 'string' && ids.has(data.default_case_id),
      'Scénario initial absent de l’index.',
    );
  if (data.limitations !== undefined)
    ensure(
      Array.isArray(data.limitations) && data.limitations.every((item) => typeof item === 'string'),
      'Limites invalides.',
    );
  return value as IssIndex;
}

export function parseIssCase(
  value: unknown,
  expected: Pick<IssCaseEntry, 'id' | 'layout_id' | 'module_id'>,
  model?: IssModel,
): IssCase {
  const data = record(value, 'Scénario');
  ensure(data.schema_version === 'iss-poc-1', 'Version du scénario ISS non prise en charge.');
  ensure(data.id === expected.id, 'Le fichier ne correspond pas au scénario sélectionné.');
  for (const key of ['layout_id', 'module_id'] as const)
    ensure(data[key] === expected[key], `Identité ${key} incompatible avec l’index.`);
  const thresholds = record(data.score_thresholds, 'Seuils du scénario');
  for (const channel of ['heat', 'smoke'] as const) {
    ensure(
      finite(thresholds[channel]) && thresholds[channel] >= 0 && thresholds[channel] <= 1.00001,
      `Seuil ${channel} du scénario invalide.`,
    );
    if (model)
      ensure(
        thresholds[channel] === model.score_thresholds[channel],
        `Seuil ${channel} différent du modèle sélectionné.`,
      );
  }
  for (const key of ['heat_delta_c', 'smoke_threshold_kg_m3'] as const) {
    ensure(finite(data[key]) && data[key] > 0, `Seuil physique ${key} invalide.`);
    if (model) ensure(data[key] === model[key], `Seuil physique ${key} différent du modèle sélectionné.`);
  }
  const scene = record(data.scene, 'Scène');
  ensure(vector(scene.bounds_m) && scene.bounds_m.every((n) => n > 0), 'Dimensions de scène invalides.');
  const bounds = scene.bounds_m;
  ensure(Array.isArray(scene.objects) && Array.isArray(scene.vents), 'Géométrie physique absente.');
  const objectIds = new Set<string>();
  for (const raw of scene.objects) {
    const item = record(raw, 'Objet');
    ensure(
      nonempty(item.id) && !objectIds.has(item.id) && nonempty(item.role) && nonempty(item.material_id),
      'Annotation d’objet absente ou identifiant répété.',
    );
    objectIds.add(item.id);
    ensure(
      vector(item.center_m) && vector(item.size_m) && item.size_m.every((n) => n > 0),
      'Dimensions d’objet invalides.',
    );
    if (item.thermal_thickness_m != null)
      ensure(
        finite(item.thermal_thickness_m) && item.thermal_thickness_m > 0,
        'Épaisseur thermique invalide.',
      );
  }
  for (const raw of scene.vents) {
    const vent = record(raw, 'Ventilation');
    ensure(
      nonempty(vent.id) && ['inlet', 'outlet'].includes(String(vent.role)),
      'Bouche de ventilation invalide.',
    );
    ensure(
      vector(vent.center_m) && vector(vent.size_m) && vent.size_m.every((n) => n >= 0) && vector(vent.normal),
      'Géométrie de ventilation invalide.',
    );
  }
  const conditions = record(data.conditions, 'Conditions');
  for (const key of ['ambient_temperature_c', 'gravity_g', 'airflow_m_s'])
    ensure(finite(conditions[key]), `Condition ${key} absente.`);
  ensure(
    nonempty(conditions.incident_type) && vector(conditions.source_position_m),
    'Source incidente absente.',
  );
  ensure(
    Array.isArray(data.sample_positions_m) && data.sample_positions_m.length > 0,
    'Positions des sondes absentes.',
  );
  for (const position of data.sample_positions_m)
    ensure(
      vector(position) && position.every((n, axis) => n >= -1e-6 && n <= bounds[axis] + 1e-6),
      'Sonde située hors du domaine physique.',
    );
  const count = data.sample_positions_m.length;
  ensure(Array.isArray(data.frames) && data.frames.length > 0, 'Aucun instant enregistré.');
  let previous = -Infinity;
  for (const raw of data.frames) {
    const frame = record(raw, 'Instant');
    ensure(
      finite(frame.time_s) && frame.time_s >= 0 && frame.time_s > previous,
      'Les instants doivent être croissants et distincts.',
    );
    previous = frame.time_s;
    for (const key of ['temperature_c', 'soot_kg_m3', 'heat_score', 'smoke_score']) {
      const values = frame[key];
      ensure(
        Array.isArray(values) && values.length === count && values.every((n) => n === null || finite(n)),
        `${key} : valeurs incompatibles avec les sondes.`,
      );
      if (key.endsWith('_score'))
        ensure(
          values.every((n) => n === null || (n >= 0 && n <= 1)),
          `${key} : score hors de [0, 1].`,
        );
      if (key === 'soot_kg_m3')
        ensure(
          values.every((n) => n === null || n >= 0),
          'Concentration de suie négative.',
        );
    }
    for (const key of ['heat_valid_mask', 'smoke_valid_mask'])
      ensure(
        Array.isArray(frame[key]) &&
          frame[key].length === count &&
          frame[key].every((n) => typeof n === 'boolean'),
        `${key} incompatible avec les sondes.`,
      );
    for (const key of ['hotspot_truth', 'smoke_truth', 'predicted_hot_mask', 'predicted_smoke_mask']) {
      const mask = frame[key];
      if (mask !== undefined)
        ensure(
          Array.isArray(mask) &&
            mask.length === count &&
            mask.every((n) => n === null || typeof n === 'boolean'),
          `${key} incompatible avec les sondes.`,
        );
    }
    for (const channel of ['heat', 'smoke'] as const) {
      const heat = channel === 'heat';
      const measurements = frame[heat ? 'temperature_c' : 'soot_kg_m3'] as (number | null)[];
      const scores = frame[heat ? 'heat_score' : 'smoke_score'] as (number | null)[];
      const valid = frame[heat ? 'heat_valid_mask' : 'smoke_valid_mask'] as boolean[];
      const truth = frame[heat ? 'hotspot_truth' : 'smoke_truth'] as (boolean | null)[] | undefined;
      const prediction = frame[heat ? 'predicted_hot_mask' : 'predicted_smoke_mask'] as
        (boolean | null)[] | undefined;
      const physicalThreshold = heat
        ? (conditions.ambient_temperature_c as number) + (data.heat_delta_c as number)
        : (data.smoke_threshold_kg_m3 as number);
      for (let point = 0; point < count; point++) {
        const measurement = measurements[point],
          score = scores[point];
        if (typeof truth?.[point] === 'boolean')
          ensure(
            valid[point] && finite(measurement) && truth[point] === measurement >= physicalThreshold,
            `Masque vérité ${channel} incohérent avec la mesure.`,
          );
        if (typeof prediction?.[point] === 'boolean')
          ensure(
            valid[point] && finite(score) && prediction[point] === score >= (thresholds[channel] as number),
            `Masque prédit ${channel} incohérent avec le score.`,
          );
      }
    }
  }
  return value as IssCase;
}

/** Verify the uncompressed JSON bytes against the selected immutable index. */
export async function decodeIssCase(
  bytes: ArrayBuffer,
  expected: IssCaseEntry,
  model: IssModel,
): Promise<IssCase> {
  ensure(globalThis.crypto?.subtle, 'La vérification des exports nécessite HTTPS ou localhost.');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const actual = Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, '0')).join('');
  ensure(
    actual === expected.sha256.toLowerCase(),
    'L’empreinte du scénario diffère de l’index. Rechargez l’export complet.',
  );
  return parseIssCase(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), expected, model);
}

/** A stable descriptor of the physical proxies, not of artistic GLB details. */
export function issGeometryKey(scene: IssScene): string {
  const order = <T extends { id: string }>(items: T[]) => [...items].sort((a, b) => a.id.localeCompare(b.id));
  return JSON.stringify({
    bounds_m: scene.bounds_m,
    objects: order(scene.objects.filter((item) => item.role !== 'decoration')).map((item) => ({
      id: item.id,
      role: item.role,
      material_id: item.material_id,
      combustible_material_id: item.combustible_material_id ?? null,
      thermal_thickness_m: item.thermal_thickness_m ?? null,
      center_m: item.center_m,
      size_m: item.size_m,
    })),
    vents: order(scene.vents).map(({ id, role, center_m, size_m, normal }) => ({
      id,
      role,
      center_m,
      size_m,
      normal,
    })),
  });
}

/** Refuse attaching a replay to a different module merely because it looks similar. */
export function assertIssSceneBinding(data: IssCase, scene: IssScene): void {
  ensure(
    issGeometryKey(data.scene) === issGeometryKey(scene),
    'La géométrie et les matériaux de la maquette ne correspondent pas au scénario ML.',
  );
}

export function issSampleState(
  frame: IssFrame,
  point: number,
  channel: IssChannel,
  ambient: number,
  model: IssModel,
) {
  const heat = channel === 'heat';
  const value = (heat ? frame.temperature_c : frame.soot_kg_m3)[point];
  const score = (heat ? frame.heat_score : frame.smoke_score)[point];
  const valid = (heat ? frame.heat_valid_mask : frame.smoke_valid_mask)[point];
  const truthMask = (heat ? frame.hotspot_truth : frame.smoke_truth)?.[point];
  const predictedMask = (heat ? frame.predicted_hot_mask : frame.predicted_smoke_mask)?.[point];
  if (!valid || !finite(value) || !finite(score) || truthMask === null || predictedMask === null) return null;
  const truth = truthMask ?? value >= (heat ? ambient + model.heat_delta_c : model.smoke_threshold_kg_m3);
  const predicted = predictedMask ?? score >= model.score_thresholds[channel];
  const kind: HotspotClass = truth ? (predicted ? 'tp' : 'fn') : predicted ? 'fp' : 'tn';
  return { value, score, truth, predicted, kind };
}

export function issFrameMetrics(
  data: IssCase,
  frame: IssFrame,
  model: IssModel,
  channel: IssChannel,
): HotspotMetrics {
  const counts = { tp: 0, fp: 0, fn: 0, tn: 0 };
  data.sample_positions_m.forEach((_, point) => {
    const state = issSampleState(frame, point, channel, data.conditions.ambient_temperature_c, model);
    if (state) counts[state.kind]++;
  });
  return metricsFromCounts(counts);
}

/** Initial presentation instant depends on FDS only, never on model quality. */
export function issPeakFrame(data: IssCase): number {
  let selected = 0;
  let peak = -Infinity;
  let smokePeak = 0;
  let smokeSelected = 0;
  data.frames.forEach((frame, index) =>
    frame.temperature_c.forEach((value, point) => {
      if (frame.heat_valid_mask[point] && finite(value) && value > peak) {
        peak = value;
        selected = index;
      }
      const soot = frame.soot_kg_m3[point];
      if (frame.smoke_valid_mask[point] && finite(soot) && soot > smokePeak) {
        smokePeak = soot;
        smokeSelected = index;
      }
    }),
  );
  return peak >= data.conditions.ambient_temperature_c + data.heat_delta_c
    ? selected
    : smokePeak >= data.smoke_threshold_kg_m3
      ? smokeSelected
      : selected;
}

/** Choose a free aisle position and look toward the real conditional source. */
export function issInteriorPose(data: IssCase): { position_m: Vec3; target_m: Vec3 } {
  const [width, depth, height] = data.scene.bounds_m;
  const [sx, sy, sz] = data.conditions.source_position_m;
  const clamp = (n: number, low: number, high: number) => Math.max(low, Math.min(high, n));
  const margin = Math.min(0.18, width / 10, depth / 10, height / 10);
  const eye = clamp(Math.max(height * 0.58, sz + 0.3), margin, height - margin);
  const distance = Math.max(width, depth) * 0.28;
  const positions: Vec3[] = [];
  // Show the compartment around the source instead of opening against its rack.
  // This changes only the camera, never the scene, samples or model outputs.
  const aisle = [sy - distance, sy + distance, depth * 0.1, depth * 0.9, depth / 2]
    .map(y => clamp(y, margin, depth - margin))
    .sort((a, b) => Math.abs(b - sy) - Math.abs(a - sy));
  for (const y of aisle)
    for (const x of [width / 2, width * 0.4, width * 0.6])
      positions.push([x, y, eye]);
  const free = (position: Vec3) =>
    !data.scene.objects.some(
      (object) =>
        object.role !== 'decoration' &&
        position.every((n, axis) => Math.abs(n - object.center_m[axis]) < object.size_m[axis] / 2 + margin),
    );
  const position =
    positions.find((p) => free(p) && Math.hypot(p[0] - sx, p[1] - sy) > margin * 3) ??
    data.sample_positions_m.find((p) => free(p)) ??
    positions[0];
  return { position_m: position, target_m: [sx, sy, clamp(sz + 0.2, margin, height - margin)] };
}

/** Glyph support, not a fluid interpolation or a learned physical plume radius. */
export function issProbeSpacing(data: Pick<IssCase, 'sample_positions_m' | 'scene'>): number {
  const gaps: number[] = [];
  for (let axis = 0; axis < 3; axis++) {
    const sorted = [...new Set(data.sample_positions_m.map((p) => p[axis]))].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i++)
      if (sorted[i] - sorted[i - 1] > 1e-6) gaps.push(sorted[i] - sorted[i - 1]);
  }
  return gaps.length ? Math.min(...gaps) : Math.min(...data.scene.bounds_m) / 12;
}
