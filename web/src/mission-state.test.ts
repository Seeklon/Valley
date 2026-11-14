import { describe, expect, it } from 'vitest';
import { componentTemperature, sceneReplays } from './mission-state';
import type { ComponentAssessment } from './prevention';
import type { Run } from './types';

describe('mission data boundaries', () => {
  const assessment = {
    observations: [
      { time_s: 0, surface_temperature_c: 20 },
      { time_s: 1, surface_temperature_c: 40 },
    ],
    learned_forecast: [
      { time_s: 2, surface_temperature_c: 60 },
      { time_s: 3, surface_temperature_c: 80 },
    ],
  } as ComponentAssessment;
  it('distinguishes observed synthetic history from learned future', () => {
    expect(componentTemperature(assessment, 0.5, 1)).toEqual({ value: 30, kind: 'history' });
    expect(componentTemperature(assessment, 1.5, 1)).toEqual({ value: 50, kind: 'prediction' });
  });
  it('does not extrapolate past thermal validity or invent an unavailable prediction', () => {
    expect(componentTemperature(assessment, 3.1, 1)).toBeNull();
    expect(componentTemperature({ ...assessment, learned_forecast: [] }, 1.5, 1)).toBeNull();
    expect(componentTemperature(assessment, -1, 1)).toBeNull();
  });
  it('filters scene/status before preferring physical replay', () => {
    const runs = [
      { id: 'other', status: 'completed', config: { scene_id: 'cargo', mode: 'physics', duration_s: 60 } },
      {
        id: 'prediction',
        status: 'completed',
        config: { scene_id: 'soyuz', mode: 'prediction', duration_s: 60 },
      },
      { id: 'incomplete', status: 'running', config: { scene_id: 'soyuz', mode: 'physics' } },
      { id: 'physics', status: 'completed', config: { scene_id: 'soyuz', mode: 'physics', duration_s: 30 } },
    ] as Run[];
    expect(sceneReplays(runs, 'soyuz').map((run) => run.id)).toEqual(['physics', 'prediction']);
    expect(sceneReplays(runs, 'missing')).toEqual([]);
  });
});
