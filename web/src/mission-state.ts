import { finite } from './data';
import type { ComponentAssessment } from './prevention';
import type { Run } from './types';

/** Prefer an actual, longer FDS replay. Never mix configurations between scenes. */
export function sceneReplays(runs: Run[], sceneId: string): Run[] {
  return runs
    .filter((run) => run.status === 'completed' && run.config?.scene_id === sceneId)
    .sort((a, b) => {
      const score = (run: Run) =>
        (run.config?.mode === 'physics' ? 100_000 : 0) +
        (run.config?.duration_s ?? 0) * 100 +
        (run.config?.ignition_power_w ?? 0);
      return score(b) - score(a);
    });
}

export function componentTemperature(
  assessment: ComponentAssessment | undefined,
  time: number,
  cutoff: number,
): { value: number; kind: 'history' | 'prediction' } | null {
  if (!assessment || !finite(time)) return null;
  const history = assessment.observations.filter((point) => point.time_s <= cutoff);
  const future = assessment.learned_forecast.filter((point) => point.time_s > cutoff);
  const rows = time <= cutoff ? history : [...history.slice(-1), ...future];
  if (!rows.length || (time > cutoff && !future.length)) return null;
  if (time < rows[0].time_s || time > rows[rows.length - 1].time_s) return null;
  const after = rows.findIndex((point) => point.time_s >= time);
  if (after < 0) return null;
  const right = rows[after];
  const left = rows[Math.max(0, after - 1)];
  if (!finite(left.surface_temperature_c) || !finite(right.surface_temperature_c)) return null;
  const mix = right.time_s === left.time_s ? 0 : (time - left.time_s) / (right.time_s - left.time_s);
  return {
    value: left.surface_temperature_c + mix * (right.surface_temperature_c - left.surface_temperature_c),
    kind: time <= cutoff ? 'history' : 'prediction',
  };
}

/** The component legend is a temperature scale, never an ignition probability. */
export function componentTemperatureColor(value: number | undefined): string {
  if (!finite(value)) return '#8c98a4';
  const fraction = Math.max(0, Math.min(1, (value - 20) / 280));
  const stops = [
    [36, 99, 163],
    [57, 184, 190],
    [233, 216, 105],
    [241, 140, 69],
    [230, 64, 54],
  ];
  const index = Math.min(3, Math.floor(fraction * 4));
  const mix = fraction * 4 - index;
  return `rgb(${stops[index].map((channel, axis) => Math.round(channel + mix * (stops[index + 1][axis] - channel))).join(',')})`;
}
