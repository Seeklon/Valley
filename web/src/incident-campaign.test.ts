import { describe, expect, it } from 'vitest';
import { incidentCampaignLabel, incidentCampaignTime } from './incident-campaign';
import type { IncidentCampaign } from './incident-campaign';

const campaign: IncidentCampaign = {
  pause_requested: false,
  progress: {
    dataset_id: 'incidents-bulk-v1',
    state: 'running',
    total_runs: 3400,
    completed_runs: 3400,
    pending_runs: 0,
    failed_runs: 0,
    elapsed_s: 24000,
    estimated_remaining_s: 0,
    mean_completed_run_s: 7,
    disk_free_gb: 120,
    last_error: null,
    updated_at: '2026-11-14T10:00:00Z',
  },
};

describe('incident campaign status is confirmed by the worker', () => {
  it('does not declare completion from a full counter or a zero estimate', () => {
    expect(incidentCampaignLabel(campaign)).toBe('Génération en cours');
    expect(incidentCampaignTime(0)).toBe('moins d’une minute');
    expect(
      incidentCampaignLabel({
        ...campaign,
        progress: { ...campaign.progress!, state: 'completed' },
      }),
    ).toBe('Campagne terminée');
  });

  it('distinguishes a requested pause from an applied pause and a requested resume', () => {
    expect(incidentCampaignLabel({ ...campaign, pause_requested: true })).toBe('Pause demandée');
    const paused = { ...campaign, progress: { ...campaign.progress!, state: 'paused' as const } };
    expect(incidentCampaignLabel({ ...paused, pause_requested: true })).toBe('En pause');
    expect(incidentCampaignLabel(paused)).toBe('Reprise demandée');
  });

  it('preserves terminal failures even when a pause marker exists', () => {
    expect(
      incidentCampaignLabel({
        ...campaign,
        pause_requested: true,
        progress: { ...campaign.progress!, state: 'failed' },
      }),
    ).toBe('Campagne interrompue sur erreur');
    expect(incidentCampaignLabel({ progress: null, pause_requested: false })).toBe('');
  });

  it('never invents a missing estimate and formats the supplied duration', () => {
    for (const value of [undefined, null, NaN, Infinity, -1]) expect(incidentCampaignTime(value)).toBeNull();
    expect(incidentCampaignTime(22320)).toBe('6 h 12 min');
    expect(incidentCampaignTime(3600)).toBe('1 h');
    expect(incidentCampaignTime(65)).toBe('2 min');
  });
});
