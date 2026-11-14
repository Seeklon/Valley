import { useEffect, useRef, useState } from 'react';
import { Database, LoaderCircle, Pause, Play } from 'lucide-react';
import { api, messageOf } from '../api';
import { finite, format } from '../data';
import { incidentCampaignLabel, incidentCampaignTime } from '../incident-campaign';
import type { IncidentCampaign } from '../incident-campaign';

export default function IncidentCampaignPanel() {
  const [campaign, setCampaign] = useState<IncidentCampaign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const revision = useRef(0);
  const pending = useRef(false);
  const action = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const current = revision.current;
      try {
        if (!pending.current) {
          const next = await api.incidentCampaign(controller.signal);
          if (!controller.signal.aborted && current === revision.current) {
            setCampaign(next);
            setError(null);
          }
        }
      } catch (reason) {
        if (!controller.signal.aborted && current === revision.current) setError(messageOf(reason));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => void refresh(), 10_000);
      }
    };
    void refresh();
    return () => {
      controller.abort();
      action.current?.abort();
      clearTimeout(timer);
    };
  }, []);

  const togglePause = async () => {
    if (!campaign?.progress || pending.current) return;
    const controller = new AbortController();
    action.current = controller;
    revision.current++;
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      const next = await api.pauseIncidentCampaign(!campaign.pause_requested, controller.signal);
      if (!controller.signal.aborted) setCampaign(next);
    } catch (reason) {
      if (!controller.signal.aborted) setError(messageOf(reason));
    } finally {
      pending.current = false;
      if (!controller.signal.aborted) setSaving(false);
    }
  };

  // A server explicitly reporting no campaign adds no empty panel to the scene.
  if (campaign?.progress === null || (!campaign && !error)) return null;
  const progress = campaign?.progress;
  if (!progress || !campaign)
    return (
      <p className="incident-campaign-error" role="status">
        Suivi de campagne : {error} Nouvelle tentative automatique.
      </p>
    );

  const time = incidentCampaignTime(progress.estimated_remaining_s);
  const canPause = ['preflight', 'running', 'paused'].includes(progress.state);
  return (
    <section
      className="incident-campaign"
      aria-label="Campagne de scénarios"
      data-campaign-state={progress.state}
    >
      <Database size={16} aria-hidden="true" />
      <div className="incident-campaign-summary">
        <div className="incident-campaign-heading">
          <strong>
            {format(progress.completed_runs, 0)} / {format(progress.total_runs, 0)} calculs FDS
          </strong>
          <span>{incidentCampaignLabel(campaign)}</span>
        </div>
        {finite(progress.completed_runs) && finite(progress.total_runs) && progress.total_runs > 0 && (
          <progress
            value={progress.completed_runs}
            max={progress.total_runs}
            aria-label="Calculs FDS terminés"
          />
        )}
        <p>
          {campaign.pause_requested && ['preflight', 'running'].includes(progress.state)
            ? 'Le calcul courant se termine avant la pause.'
            : progress.state === 'paused' && campaign.pause_requested
              ? 'Les prochains calculs de la campagne sont suspendus.'
              : canPause
                ? 'La pause libère le poste après le calcul courant.'
                : null}
          {time && progress.state !== 'completed' && <> Temps de calcul restant estimé : {time}.</>}
          {progress.failed_runs > 0 && <> {format(progress.failed_runs, 0)} calculs en échec.</>}
        </p>
        {progress.last_error && <p className="incident-campaign-error">{progress.last_error}</p>}
        {error && (
          <p className="incident-campaign-error" role="status">
            {error} Nouvelle tentative automatique.
          </p>
        )}
      </div>
      {canPause && (
        <button className="mission-secondary" disabled={saving} onClick={() => void togglePause()}>
          {saving ? (
            <LoaderCircle className="spin" size={13} />
          ) : campaign.pause_requested ? (
            <Play size={13} />
          ) : (
            <Pause size={13} />
          )}
          {saving ? 'Envoi…' : campaign.pause_requested ? 'Reprendre' : 'Pause'}
        </button>
      )}
    </section>
  );
}
