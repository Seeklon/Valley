import { useEffect, useState } from 'react';
import {
  ArrowDownToLine,
  Check,
  ChevronDown,
  Database,
  Layers,
  LoaderCircle,
  Play,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { api, ApiError, messageOf } from '../api';
import { finite, format } from '../data';
import type { Campaign, CampaignRequest, RunConfig, Scene } from '../types';

type RangeKey = 'airflow_m_s' | 'oxygen_percent' | 'ignition_power_w' | 'gravity_g';
const parameters: { key: RangeKey; label: string; unit: string; min: number; max: number; step: number }[] = [
  { key: 'airflow_m_s', label: 'Ventilation', unit: 'm/s', min: 0, max: 1, step: 0.01 },
  { key: 'oxygen_percent', label: 'Oxygène', unit: '% vol.', min: 15, max: 30, step: 0.5 },
  { key: 'ignition_power_w', label: 'Puissance thermique', unit: 'W', min: 100, max: 10_000, step: 50 },
  { key: 'gravity_g', label: 'Gravité', unit: 'g', min: 0, max: 1, step: 0.0001 },
];

function savedId(): string | null {
  try {
    return localStorage.getItem('ignis:last-campaign');
  } catch {
    return null;
  }
}

export default function CampaignPanel({
  config,
  scenes,
  available,
  busy,
}: {
  config: RunConfig;
  scenes: Scene[];
  available: boolean;
  busy: boolean;
}) {
  const [count, setCount] = useState(12);
  const [seed, setSeed] = useState(314);
  const [selected, setSelected] = useState<string[]>([]);
  const [ranges, setRanges] = useState<Record<RangeKey, [number, number]>>({
    airflow_m_s: [0.1, 0.4],
    oxygen_percent: [18, 24],
    ignition_power_w: [300, 1000],
    gravity_g: [0.0001, 0.0001],
  });
  const [varyGravity, setVaryGravity] = useState(false);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = campaign && ['queued', 'running'].includes(campaign.status);
  const locked = submitting || Boolean(active);
  const invalid =
    count < 2 ||
    count > 100 ||
    !Number.isInteger(count) ||
    Object.entries(ranges).some(
      ([key, [min, max]]) =>
        (key !== 'gravity_g' || varyGravity) && (!finite(min) || !finite(max) || min > max),
    );

  useEffect(() => {
    if (scenes.length)
      setSelected((previous) => (previous.length ? previous : scenes.map((scene) => scene.id)));
  }, [scenes]);

  useEffect(() => {
    const id = savedId();
    if (id)
      void api
        .campaign(id)
        .then(setCampaign)
        .catch(() => {
          /* No synthetic reconstruction of missing jobs. */
        });
  }, []);

  useEffect(() => {
    if (!campaign || !['queued', 'running'].includes(campaign.status)) return;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const id = campaign.id;
    const poll = async () => {
      try {
        const next = await api.campaign(id, controller.signal);
        if (controller.signal.aborted) return;
        setCampaign(next);
        setError(null);
        if (['queued', 'running'].includes(next.status))
          timer = setTimeout(() => {
            void poll();
          }, 3000);
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (reason instanceof ApiError && reason.status === 404) {
          setCampaign(null);
          setError('Cette campagne n’existe plus dans le registre.');
          return;
        }
        setError(messageOf(reason));
        timer = setTimeout(() => {
          void poll();
        }, 5000);
      }
    };
    timer = setTimeout(() => {
      void poll();
    }, 500);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [campaign?.id, campaign?.status]);

  const launch = async () => {
    if (invalid || !selected.length || !available || locked) return;
    setSubmitting(true);
    setError(null);
    const rangesToSend: CampaignRequest['ranges'] = {
      airflow_m_s: ranges.airflow_m_s,
      oxygen_percent: ranges.oxygen_percent,
    };
    if (config.ignition_kind !== 'resistive') rangesToSend.ignition_power_w = ranges.ignition_power_w;
    if (varyGravity) rangesToSend.gravity_g = ranges.gravity_g;
    try {
      const next = await api.launchCampaign({
        count,
        seed,
        scene_ids: selected,
        base_config: { ...config, mode: 'physics', model_id: null },
        ranges: rangesToSend,
      });
      setCampaign(next);
      try {
        localStorage.setItem('ignis:last-campaign', next.id);
      } catch {
        /* Storage may be disabled. */
      }
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!campaign || cancelling) return;
    setCancelling(true);
    try {
      setCampaign(await api.cancelCampaign(campaign.id));
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setCancelling(false);
    }
  };

  const updateRange = (key: RangeKey, index: 0 | 1, value: number) =>
    setRanges((previous) => ({
      ...previous,
      [key]: index === 0 ? [value, previous[key][1]] : [previous[key][0], value],
    }));

  return (
    <details className="panel campaign-panel">
      <summary>
        <span className="campaign-heading-icon">
          <Layers size={18} />
        </span>
        <div>
          <strong>Générer une campagne de scènes</strong>
          <span>Variantes reproductibles · simulations physiques · dataset exportable</span>
        </div>
        <span className={`status-chip ${available ? 'success' : ''}`}>
          <span className="status-dot" />
          {available ? 'Disponible' : 'Worker requis'}
        </span>
        <ChevronDown size={16} />
      </summary>
      <div className="campaign-body">
        <div className="campaign-setup">
          <h3>
            <Database size={14} /> Plan d’échantillonnage
          </h3>
          <div className="two-inputs">
            <label>
              Nombre d’essais{' '}
              <span className="number-wrap">
                <input
                  type="number"
                  min={2}
                  max={100}
                  value={count}
                  onChange={(event) => setCount(Number(event.target.value))}
                  disabled={locked}
                />
              </span>
            </label>
            <label>
              Graine{' '}
              <span className="number-wrap">
                <input
                  type="number"
                  min={0}
                  max={2147483647}
                  value={seed}
                  onChange={(event) => setSeed(Number(event.target.value))}
                  disabled={locked}
                />
              </span>
            </label>
          </div>
          <div className="campaign-scene-list">
            {scenes.map((scene) => (
              <label key={scene.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(scene.id)}
                  disabled={locked}
                  onChange={(event) =>
                    setSelected((previous) =>
                      event.target.checked
                        ? [...previous, scene.id]
                        : previous.filter((id) => id !== scene.id),
                    )
                  }
                />
                <span>{scene.name}</span>
              </label>
            ))}
          </div>
          <p>
            La durée, le matériau et le modèle de combustion reprennent la configuration du laboratoire. Les
            familles et graines restent conservées pour préparer les partitions d’apprentissage.
          </p>
        </div>
        <div className="campaign-ranges">
          <h3>Plages des variables</h3>
          <div className="campaign-range-head">
            <span>Variable</span>
            <span>Minimum</span>
            <span>Maximum</span>
          </div>
          {parameters
            .filter(
              (parameter) =>
                (parameter.key !== 'gravity_g' || varyGravity) &&
                (parameter.key !== 'ignition_power_w' || config.ignition_kind !== 'resistive'),
            )
            .map((parameter) => (
              <div className="campaign-range" key={parameter.key}>
                <label htmlFor={`campaign-${parameter.key}-min`}>
                  {parameter.label}
                  <small>{parameter.unit}</small>
                </label>
                {([0, 1] as const).map((index) => (
                  <input
                    key={index}
                    id={`campaign-${parameter.key}-${index === 0 ? 'min' : 'max'}`}
                    aria-label={`${parameter.label} ${index === 0 ? 'minimum' : 'maximum'}`}
                    type="number"
                    min={parameter.min}
                    max={parameter.max}
                    step={parameter.step}
                    value={ranges[parameter.key][index]}
                    disabled={locked}
                    onChange={(event) => updateRange(parameter.key, index, Number(event.target.value))}
                  />
                ))}
              </div>
            ))}
          <label className="vary-gravity">
            <input
              type="checkbox"
              checked={varyGravity}
              disabled={locked}
              onChange={(event) => setVaryGravity(event.target.checked)}
            />
            Faire varier la gravité
          </label>
          <p className="field-help">
            {varyGravity
              ? 'Les gravités partielles sont exploratoires ; elles ne disposent pas de données de combustion dans PSI.'
              : `Gravité fixe : ${format(config.gravity_g, 4)} g.`}
            {config.ignition_kind === 'resistive'
              ? ` Chauffage résistif fixe : ${format(config.current_a ** 2 * config.resistance_ohm, 0)} W.`
              : ''}
          </p>
        </div>
        <div className="campaign-execution">
          <h3>Exécution & collecte</h3>
          <p>
            Les essais passent par la file du poste de calcul. Un essai interrompu conserve son statut ; les
            résultats invalides ne deviennent pas des exemples d’apprentissage.
          </p>
          <button
            className="button primary full-width"
            disabled={!available || locked || busy || invalid || !selected.length}
            onClick={() => {
              void launch();
            }}
          >
            {submitting ? (
              <LoaderCircle className="spin" size={14} />
            ) : (
              <Play size={13} fill="currentColor" />
            )}
            Générer {count} essais
          </button>
          {!available && (
            <p className="field-help">
              La génération sera activée quand le moteur physique et l’ordonnanceur de campagnes seront
              disponibles.
            </p>
          )}
          {invalid && (
            <p className="campaign-error">Vérifiez le nombre d’essais (2–100) et l’ordre des bornes.</p>
          )}
          {campaign && (
            <div className={`job-status ${campaign.status}`}>
              <div>
                <span>
                  {active ? (
                    <LoaderCircle className="spin" size={13} />
                  ) : campaign.status === 'completed' ? (
                    <Check size={13} />
                  ) : (
                    <TriangleAlert size={13} />
                  )}
                  {campaign.status === 'completed'
                    ? 'Campagne terminée'
                    : campaign.status === 'failed'
                      ? 'Campagne en échec'
                      : campaign.status === 'cancelled'
                        ? 'Campagne annulée'
                        : 'Campagne en cours'}
                </span>
                <code>{campaign.id.slice(0, 8)}</code>
              </div>
              <p>
                {campaign.completed_runs ?? 0} / {campaign.total_runs ?? count} essais terminés ·{' '}
                {campaign.failed_runs ?? 0} échecs · {campaign.cancelled_runs ?? 0} annulations
              </p>
              {active && (
                <>
                  <progress
                    max={1}
                    value={finite(campaign.progress) ? campaign.progress : undefined}
                    aria-label="Progression de la campagne"
                  />
                  <button
                    className="text-button"
                    onClick={() => {
                      void cancel();
                    }}
                    disabled={cancelling}
                  >
                    <Square size={10} />
                    {cancelling ? 'Annulation…' : 'Annuler la campagne'}
                  </button>
                </>
              )}
              {campaign.message && <p>{campaign.message}</p>}
              {['completed', 'failed', 'cancelled'].includes(campaign.status) && (
                <a
                  href={api.campaignExportUrl(campaign.id)}
                  download
                  className="button secondary full-width campaign-export"
                >
                  <ArrowDownToLine size={13} />
                  Exporter les résultats disponibles
                </a>
              )}
            </div>
          )}
          {error && (
            <div className="inline-error" role="alert">
              <TriangleAlert size={14} />
              <p>{error}</p>
            </div>
          )}
        </div>
      </div>
    </details>
  );
}
