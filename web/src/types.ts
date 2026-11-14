export type Vec3 = [number, number, number];
export type RunMode = 'physics' | 'prediction';
export type SourceModel = 'prescribed_source' | 'coupled_combustion';
export type Field = 'scene' | 'temperature' | 'airflow' | 'smoke' | 'oxygen';

/** Component annotations use the same physical Z-up coordinates as the scene. */
export interface ViewportMarker {
  id: string;
  name: string;
  position_m: Vec3;
  object_id?: string;
  color?: string;
}

export interface Material {
  id: string;
  name: string;
  description?: string;
  color?: string;
  provenance?: unknown;
}

export interface SceneObject {
  id: string;
  name: string;
  role: 'obstacle' | 'fuel' | 'wall' | 'decoration';
  material_id: string;
  center_m: Vec3;
  size_m: Vec3;
}

export interface Vent {
  id: string;
  role: 'inlet' | 'outlet';
  center_m: Vec3;
  size_m: Vec3;
  normal: Vec3;
  nominal_speed_m_s: number;
}

export interface Scene {
  id: string;
  name: string;
  description: string;
  asset_url: string;
  preview_url?: string;
  bounds_m: Vec3;
  objects: SceneObject[];
  vents: Vent[];
  sensors: { id: string; name: string; position_m: Vec3 }[];
  source_position_m: Vec3;
  defaults?: Partial<RunConfig>;
  provenance?: unknown;
}

export interface Catalog {
  schema_version: number;
  materials: Material[];
  scenes: Scene[];
}

export interface RunConfig {
  scene_id: string;
  mode: RunMode;
  source_model: SourceModel;
  gravity_g: number;
  airflow_m_s: number;
  oxygen_percent: number;
  material_id: string;
  ignition_power_w: number;
  ignition_duration_s: number;
  duration_s: number;
  seed: number;
  ignition_kind: 'thermal' | 'resistive';
  current_a: number;
  resistance_ohm: number;
  model_id?: string | null;
  mesh_cell_m?: number;
  sample_shape?: Vec3;
  incident_type?: 'overheating' | 'arc' | 'flaming' | 'smoldering' | 'battery';
  component_id?: string;
}

export interface Metric {
  time_s: number;
  temperature_max_c?: number;
  temperature_mean_c?: number;
  oxygen_mean_percent?: number;
  smoke_mean_kg_m3?: number;
  heat_release_w?: number;
  sensors?: Record<string, Record<string, number>>;
}

export interface Frame {
  time_s: number;
  shape: Vec3;
  bounds_m: Vec3;
  temperature_c?: (number | null)[];
  oxygen_percent?: (number | null)[];
  smoke_kg_m3?: (number | null)[];
  velocity_m_s?: (number | null)[];
  valid_mask?: boolean[];
  sample_positions_m?: Vec3[];
}

export interface Result {
  provenance: {
    engine: string;
    engine_version?: string;
    model_id?: string | null;
    scientific_status?: string;
    source_model?: string;
    warnings?: string[];
    [key: string]: unknown;
  };
  metrics: Metric[];
  frames: Frame[];
  summary?: Record<string, unknown>;
}

export interface Run {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress?: number;
  message?: string;
  config?: RunConfig;
  result?: Result | null;
  error?: string;
}

export interface ModelInfo {
  id: string;
  name?: string;
  kind?: string;
  status?: string;
  loaded?: boolean;
  available?: boolean;
  description?: string;
  domain?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  scientific_status?: string;
  [key: string]: unknown;
}

export interface Health {
  status?: string;
  worker_available?: boolean;
  capabilities?: {
    physics?: boolean;
    prediction?: boolean;
    source_models?: SourceModel[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface Source {
  id?: string;
  name?: string;
  title?: string;
  url?: string;
  description?: string;
  doi?: string;
  status?: string;
  observations?: unknown;
  [key: string]: unknown;
}

export interface CampaignRequest {
  count: number;
  seed: number;
  scene_ids: string[];
  base_config: RunConfig;
  ranges: Partial<
    Record<'airflow_m_s' | 'oxygen_percent' | 'ignition_power_w' | 'gravity_g', [number, number]>
  >;
}

export interface Campaign {
  id: string;
  status: Run['status'];
  progress?: number;
  completed_runs?: number;
  failed_runs?: number;
  cancelled_runs?: number;
  total_runs?: number;
  message?: string;
  run_ids?: string[];
}

export interface Insight {
  summary: string;
  method: string;
  model?: string | null;
  sources: { id: string; name: string; url: string; score?: number; reasons: string[] }[];
  facts: { text: string; source_id: string }[];
  limits: string[];
}
