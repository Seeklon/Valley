import { finite, voxelPosition } from './data';
import type { Frame, Vec3 } from './types';

export type MissionCamera = 'pov' | 'orbit' | 'top';
export type MissionLayer = 'scene' | 'smoke' | 'temperature' | 'thermal-smoke' | 'airflow';
export interface MissionScale {
  min: number;
  max: number;
  unit: string;
  available: boolean;
}
export interface MissionScales {
  temperature: MissionScale;
  smoke: MissionScale;
  airflow: MissionScale;
}
export const MISSION_TEMPERATURE_GRADIENT =
  'linear-gradient(90deg, #2463a3 0%, #39b8be 25%, #e9d869 50%, #f18c45 75%, #e64036 100%)';

export interface MissionBracket {
  from: Frame;
  to: Frame;
  mix: number;
  compatible: boolean;
}

export function missionSampleCount(frame: Frame): number {
  if (!frame.shape.every((value) => Number.isInteger(value) && value > 0)) return 0;
  const count = frame.shape[0] * frame.shape[1] * frame.shape[2];
  return count <= 5_000_000 ? count : 0;
}

function validAt(frame: Frame, index: number): boolean {
  return (
    index >= 0 &&
    index < missionSampleCount(frame) &&
    (frame.valid_mask === undefined || frame.valid_mask[index] === true)
  );
}

export function missionPosition(frame: Frame, index: number): Vec3 | null {
  if (index < 0 || index >= missionSampleCount(frame)) return null;
  const position = frame.sample_positions_m
    ? frame.sample_positions_m[index]
    : voxelPosition(index, frame.shape, frame.bounds_m);
  return position?.length === 3 && position.every(finite) ? position : null;
}

function sameGrid(a: Frame, b: Frame): boolean {
  if (a === b) return true;
  if (
    !a.shape.every((value, axis) => value === b.shape[axis]) ||
    !a.bounds_m.every((value, axis) => Math.abs(value - b.bounds_m[axis]) < 1e-7)
  )
    return false;
  if (a.sample_positions_m === b.sample_positions_m) return true;
  for (let index = 0; index < missionSampleCount(a); index++) {
    const first = missionPosition(a, index);
    const second = missionPosition(b, index);
    if (!first || !second || !first.every((value, axis) => Math.abs(value - second[axis]) < 1e-7))
      return false;
  }
  return true;
}

/** Interpolation is confined to observed timestamps; no extrapolation or grid remapping. */
export function missionBracket(frames: Frame[], time: number): MissionBracket | null {
  const ordered = frames.filter((frame) => finite(frame.time_s)).sort((a, b) => a.time_s - b.time_s);
  if (!ordered.length || !finite(time)) return null;
  let from = ordered[0];
  for (const frame of ordered) {
    if (frame.time_s === time) return { from: frame, to: frame, mix: 0, compatible: true };
    if (frame.time_s > time) {
      if (frame === from) return { from, to: from, mix: 0, compatible: true };
      return {
        from,
        to: frame,
        mix: (time - from.time_s) / (frame.time_s - from.time_s),
        compatible: sameGrid(from, frame),
      };
    }
    from = frame;
  }
  return { from, to: from, mix: 0, compatible: true };
}

export function missionScalar(
  bracket: MissionBracket,
  index: number,
  field: 'temperature_c' | 'smoke_kg_m3',
): number | null {
  if (!bracket.compatible || !validAt(bracket.from, index)) return null;
  const a = bracket.from[field]?.[index];
  if (!finite(a)) return null;
  if (bracket.mix === 0 || bracket.from === bracket.to) return a;
  if (!validAt(bracket.to, index)) return null;
  const b = bracket.to[field]?.[index];
  return finite(b) ? a + (b - a) * bracket.mix : null;
}

export function missionVelocity(bracket: MissionBracket, index: number): Vec3 | null {
  if (!bracket.compatible || !validAt(bracket.from, index)) return null;
  const a = bracket.from.velocity_m_s?.slice(index * 3, index * 3 + 3);
  if (a?.length !== 3 || !a.every(finite)) return null;
  if (bracket.mix === 0 || bracket.from === bracket.to) return a as Vec3;
  if (!validAt(bracket.to, index)) return null;
  const b = bracket.to.velocity_m_s?.slice(index * 3, index * 3 + 3);
  if (b?.length !== 3 || !b.every(finite)) return null;
  return a.map((value, axis) => value + (b[axis] - value) * bracket.mix) as Vec3;
}

function ceiling(value: number, fallback: number): number {
  if (!finite(value) || value <= 0) return fallback;
  const power = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / power) * power;
}

/** One scale per complete recording, including values hidden by display decimation. */
export function missionScales(frames: Frame[]): MissionScales {
  let temperatureMin = Infinity;
  let temperatureMax = -Infinity;
  let smokeMax = -Infinity;
  let speedMax = -Infinity;
  for (const frame of frames) {
    for (let index = 0; index < missionSampleCount(frame); index++) {
      if (!validAt(frame, index) || !missionPosition(frame, index)) continue;
      const temperature = frame.temperature_c?.[index];
      const smoke = frame.smoke_kg_m3?.[index];
      if (finite(temperature)) {
        temperatureMin = Math.min(temperatureMin, temperature);
        temperatureMax = Math.max(temperatureMax, temperature);
      }
      if (finite(smoke) && smoke >= 0) smokeMax = Math.max(smokeMax, smoke);
      const x = frame.velocity_m_s?.[index * 3];
      const y = frame.velocity_m_s?.[index * 3 + 1];
      const z = frame.velocity_m_s?.[index * 3 + 2];
      if (finite(x) && finite(y) && finite(z)) speedMax = Math.max(speedMax, Math.hypot(x, y, z));
    }
  }
  const lower = finite(temperatureMin) ? Math.floor(temperatureMin / 10) * 10 : 20;
  return {
    temperature: {
      min: lower,
      max: Math.max(lower + 10, ceiling(temperatureMax, 100)),
      unit: '°C',
      available: finite(temperatureMax),
    },
    smoke: { min: 0, max: ceiling(smokeMax, 0.0001), unit: 'kg/m³', available: finite(smokeMax) },
    airflow: { min: 0, max: ceiling(speedMax, 1), unit: 'm/s', available: finite(speedMax) },
  };
}

/** Return the actual, potentially nonuniform, sample axes only for a separable grid. */
export function missionGridAxes(frame: Frame): [number[], number[], number[]] | null {
  const count = missionSampleCount(frame);
  if (!count) return null;
  const [nx, ny, nz] = frame.shape;
  const axes: [number[], number[], number[]] = [[], [], []];
  for (let x = 0; x < nx; x++) axes[0].push(missionPosition(frame, x * ny * nz)?.[0] ?? NaN);
  for (let y = 0; y < ny; y++) axes[1].push(missionPosition(frame, y * nz)?.[1] ?? NaN);
  for (let z = 0; z < nz; z++) axes[2].push(missionPosition(frame, z)?.[2] ?? NaN);
  if (
    axes.some((axis) =>
      axis.some((value, index) => !finite(value) || (index > 0 && value <= axis[index - 1])),
    )
  )
    return null;
  for (let index = 0; index < count; index++) {
    const position = missionPosition(frame, index);
    const x = Math.floor(index / (ny * nz));
    const y = Math.floor(index / nz) % ny;
    const z = index % nz;
    if (
      !position ||
      Math.abs(position[0] - axes[0][x]) > 1e-6 ||
      Math.abs(position[1] - axes[1][y]) > 1e-6 ||
      Math.abs(position[2] - axes[2][z]) > 1e-6
    )
      return null;
  }
  return axes;
}

export function missionSampleIndices(frame: Frame, limit = 12_000): number[] {
  const count = missionSampleCount(frame);
  if (!count || !Number.isInteger(limit) || limit <= 0) return [];
  const used = Math.min(count, limit);
  return Array.from({ length: used }, (_, index) => Math.floor((index * count) / used));
}
