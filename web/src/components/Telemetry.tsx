import { Activity, Droplets, Flame, Thermometer, Wind } from 'lucide-react';
import { finite, format, metricPath } from '../data';
import type { Metric, Run } from '../types';

export type MetricKey =
  'temperature_max_c' | 'temperature_mean_c' | 'oxygen_mean_percent' | 'smoke_mean_kg_m3' | 'heat_release_w';

const options: { key: MetricKey; name: string; unit: string; color: string }[] = [
  { key: 'temperature_max_c', name: 'Température max.', unit: '°C', color: '#f3ad70' },
  { key: 'oxygen_mean_percent', name: 'Oxygène moyen', unit: '%', color: '#6ad5cc' },
  { key: 'heat_release_w', name: 'Puissance thermique', unit: 'W', color: '#b09bea' },
  { key: 'smoke_mean_kg_m3', name: 'Fumée moyenne', unit: 'kg/m³', color: '#a7bdd7' },
];

export function MetricCards({ metric, previous }: { metric?: Metric; previous?: Metric }) {
  const cards = [
    {
      label: 'Température maximale',
      key: 'temperature_max_c' as const,
      unit: '°C',
      icon: Thermometer,
      decimals: 1,
      color: 'amber',
    },
    {
      label: 'Oxygène moyen',
      key: 'oxygen_mean_percent' as const,
      unit: '%',
      icon: Wind,
      decimals: 2,
      color: 'cyan',
    },
    {
      label: 'Puissance thermique',
      key: 'heat_release_w' as const,
      unit: 'W',
      icon: Flame,
      decimals: 0,
      color: 'violet',
    },
    {
      label: 'Fumée moyenne',
      key: 'smoke_mean_kg_m3' as const,
      unit: 'mg/m³',
      icon: Droplets,
      decimals: 2,
      color: 'slate',
    },
  ];
  return (
    <div className="metric-grid">
      {cards.map(({ label, key, unit, icon: Icon, decimals, color }) => {
        const scale = key === 'smoke_mean_kg_m3' ? 1e6 : 1;
        const value = metric?.[key];
        const before = previous?.[key];
        const delta = finite(value) && finite(before) ? (value - before) * scale : null;
        return (
          <div className={`metric-card ${color}`} key={key}>
            <div className="metric-label">
              <Icon size={15} />
              <span>{label}</span>
            </div>
            <div className="metric-number">
              {finite(value) ? format(value * scale, decimals) : '—'}
              <small>{unit}</small>
            </div>
            <div className="metric-caption">
              {delta === null
                ? metric
                  ? `Mesure à t = ${format(metric.time_s, 1)} s`
                  : 'En attente d’un résultat'
                : `${delta > 0 ? '+' : ''}${format(delta, decimals)} ${unit} vs réf. t = ${format(previous?.time_s, 1)} s`}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface Props {
  run: Run | null;
  baseline: Run | null;
  time: number;
  metricKey: MetricKey;
  onMetricChange: (key: MetricKey) => void;
}

export default function Telemetry({ run, baseline, time, metricKey, onMetricChange }: Props) {
  const option = options.find((item) => item.key === metricKey)!;
  const rows = run?.result?.metrics ?? [];
  const before = baseline?.result?.metrics ?? [];
  const allValues = [...rows, ...before].map((row) => row[metricKey]).filter(finite);
  const min = allValues.length ? Math.min(...allValues) : 0;
  const max = allValues.length ? Math.max(...allValues) : 1;
  const pad = Math.max((max - min) * 0.15, Math.abs(max) * 0.01, 1e-8);
  const domain: [number, number] = [Math.max(0, min - pad), max + pad];
  const maxTime = Math.max(1, ...[...rows, ...before].map((row) => row.time_s));
  const width = 820;
  const height = 142;
  const currentPath = metricPath(rows, metricKey, width, height, domain, maxTime);
  const baselinePath = metricPath(before, metricKey, width, height, domain, maxTime);
  const yLabel = (value: number) =>
    Math.abs(value) > 0 && Math.abs(value) < 0.01
      ? value.toExponential(1)
      : format(value, value < 10 ? 2 : 0);
  return (
    <section className="panel telemetry-panel">
      <div className="panel-heading">
        <div>
          <Activity size={16} />
          <h2>Télémétrie</h2>
          <span className="muted small">
            {rows.length ? `${rows.length} observations` : 'Séries temporelles'}
          </span>
        </div>
        <div className="chart-legend">
          <i style={{ background: option.color }} /> Essai courant
          {baseline && (
            <>
              <i className="baseline-key" /> Référence
            </>
          )}
        </div>
      </div>
      <div className="chart-tabs">
        {options.map((item) => (
          <button
            key={item.key}
            className={metricKey === item.key ? 'active' : ''}
            onClick={() => onMetricChange(item.key)}
          >
            {item.name}
          </button>
        ))}
      </div>
      {!allValues.length ? (
        <div className="chart-empty">
          <Activity size={26} strokeWidth={1} />
          <div>
            <strong>
              {run?.status === 'completed'
                ? 'Cette mesure n’est pas disponible'
                : 'Vos courbes apparaîtront ici'}
            </strong>
            <p>
              {run?.status === 'completed'
                ? 'Le résultat ne contient pas de valeurs pour ce champ.'
                : 'Lancez un essai pour observer l’évolution physique ou la prédiction du modèle.'}
            </p>
          </div>
        </div>
      ) : (
        <div className="chart-wrap">
          <div className="chart-y-labels">
            {[domain[1], (domain[0] + domain[1]) / 2, domain[0]].map((value, index) => (
              <span key={index}>{yLabel(value)}</span>
            ))}
          </div>
          <div className="chart-plot">
            <svg
              viewBox={`0 0 ${width} ${height}`}
              preserveAspectRatio="none"
              role="img"
              aria-label={`Évolution de ${option.name.toLowerCase()} en ${option.unit}`}
            >
              <defs>
                <linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={option.color} stopOpacity="0.14" />
                  <stop offset="100%" stopColor={option.color} stopOpacity="0" />
                </linearGradient>
              </defs>
              {[0, 0.5, 1].map((fraction) => (
                <line
                  key={fraction}
                  x1="0"
                  x2={width}
                  y1={height * fraction}
                  y2={height * fraction}
                  stroke="#28313e"
                  strokeDasharray="3 5"
                />
              ))}
              {[0.25, 0.5, 0.75].map((fraction) => (
                <line
                  key={fraction}
                  x1={width * fraction}
                  x2={width * fraction}
                  y1="0"
                  y2={height}
                  stroke="#1e2a36"
                />
              ))}
              {baselinePath && (
                <path
                  d={baselinePath}
                  fill="none"
                  stroke="#71829c"
                  strokeWidth="2"
                  strokeDasharray="5 5"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {currentPath && (
                <path
                  d={currentPath}
                  fill="none"
                  stroke={option.color}
                  strokeWidth="2"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              <line
                x1={(time / maxTime) * width}
                x2={(time / maxTime) * width}
                y1="0"
                y2={height}
                stroke="#b7c7da"
                opacity="0.65"
                strokeDasharray="2 4"
              />
            </svg>
            <div className="chart-x-labels">
              {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
                <span key={fraction}>{format(maxTime * fraction, 0)} s</span>
              ))}
            </div>
          </div>
          <span className="chart-unit">{option.unit}</span>
        </div>
      )}
    </section>
  );
}
