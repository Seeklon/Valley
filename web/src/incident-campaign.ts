import { finite } from './data';

export type IncidentCampaignState =
  'preflight' | 'running' | 'paused' | 'stopped' | 'limited' | 'disk_reserve' | 'failed' | 'completed';

export interface IncidentCampaign {
  progress: {
    dataset_id: string;
    state: IncidentCampaignState;
    total_runs: number;
    completed_runs: number;
    pending_runs: number;
    failed_runs: number;
    elapsed_s: number;
    estimated_remaining_s: number | null;
    mean_completed_run_s: number | null;
    disk_free_gb: number | null;
    last_error: string | null;
    updated_at: string;
  } | null;
  pause_requested: boolean;
}

const labels: Record<IncidentCampaignState, string> = {
  preflight: 'Vérification avant calcul',
  running: 'Génération en cours',
  paused: 'En pause',
  stopped: 'Campagne arrêtée',
  limited: 'Limite de calcul atteinte',
  disk_reserve: 'Espace disque insuffisant',
  failed: 'Campagne interrompue sur erreur',
  completed: 'Campagne terminée',
};

export function incidentCampaignLabel(campaign: IncidentCampaign): string {
  const state = campaign.progress?.state;
  if (!state) return '';
  if (campaign.pause_requested && ['preflight', 'running'].includes(state)) return 'Pause demandée';
  if (!campaign.pause_requested && state === 'paused') return 'Reprise demandée';
  return labels[state] ?? 'État non renseigné';
}

export function incidentCampaignTime(seconds: number | null | undefined): string | null {
  if (!finite(seconds) || seconds < 0) return null;
  if (seconds < 60) return 'moins d’une minute';
  const minutes = Math.ceil(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ''}` : `${minutes} min`;
}
