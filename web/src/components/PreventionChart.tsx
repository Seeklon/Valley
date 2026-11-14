import { Activity } from 'lucide-react';
import { finite, format } from '../data';
import { futureSuffix, observationPrefix } from '../prevention';
import type { ComponentAssessment } from '../prevention';

type Point = { time_s: number; surface_temperature_c: number };

export default function PreventionChart({
  assessment,
  cutoff,
  horizon,
  duration,
}: {
  assessment?: ComponentAssessment;
  cutoff: number;
  horizon: number;
  duration: number;
}) {
  const observed = observationPrefix(assessment?.observations ?? [], cutoff);
  const projected = futureSuffix(assessment?.forecast ?? [], cutoff);
  const learned = futureSuffix(assessment?.learned_forecast ?? [], cutoff);
  const all = [...observed, ...projected, ...learned];
  const values = all.map((point) => point.surface_temperature_c).filter(finite);
  const startY = values.length ? Math.floor(Math.min(...values) / 20) * 20 : 0;
  const endY = values.length ? Math.max(startY + 20, Math.ceil(Math.max(...values) / 20) * 20) : 100;
  const endX = Math.max(duration, cutoff + horizon, 1);
  const x = (time: number) => 50 + (time / endX) * 610;
  const y = (temperature: number) => 183 - ((temperature - startY) / (endY - startY)) * 145;
  const path = (points: Point[]) => {
    let started = false;
    return points
      .map((point) => {
        if (!finite(point.surface_temperature_c)) {
          started = false;
          return '';
        }
        const command = started ? 'L' : 'M';
        started = true;
        return `${command}${x(point.time_s).toFixed(2)},${y(point.surface_temperature_c).toFixed(2)}`;
      })
      .join(' ');
  };
  const series = [
    { id: 'observed', label: 'Historique simulé', points: observed, color: '#8bdbcf', dash: undefined },
    { id: 'physical', label: 'Projection physique', points: projected, color: '#e5b77e', dash: '9 4' },
    { id: 'learned', label: 'Prévision ML', points: learned, color: '#b6a3e9', dash: '2 5' },
  ];

  return (
    <section className="panel prevention-chart" aria-label="Échauffement du composant">
      <div className="panel-heading">
        <div>
          <Activity size={16} />
          <h2>Température de surface</h2>
        </div>
        <span>°C</span>
      </div>
      <div className="prevention-chart-legend">
        {series.map((line) => (
          <span key={line.id}>
            <i style={{ background: line.color }} />
            {line.label}
          </span>
        ))}
      </div>
      {values.length ? (
        <>
          <svg
            viewBox="0 0 690 222"
            role="img"
            aria-label={`Historique simulé jusqu’à ${format(cutoff, 2)} secondes, puis projections disponibles. Aucune mesure réelle.`}
          >
            <rect
              x={x(cutoff)}
              y="25"
              width={x(cutoff + horizon) - x(cutoff)}
              height="158"
              fill="#91b9d5"
              opacity="0.045"
            />
            {[0, 0.5, 1].map((fraction) => {
              const value = startY + fraction * (endY - startY);
              return (
                <g key={fraction}>
                  <line x1="50" x2="660" y1={y(value)} y2={y(value)} stroke="#293646" strokeDasharray="3 5" />
                  <text x="42" y={y(value) + 4} textAnchor="end">
                    {format(value, 0)}
                  </text>
                </g>
              );
            })}
            {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
              <text key={fraction} x={x(endX * fraction)} y="205" textAnchor="middle">
                {format(endX * fraction, 1)} s
              </text>
            ))}
            <line x1={x(cutoff)} x2={x(cutoff)} y1="25" y2="183" stroke="#aab9ca" strokeDasharray="3 4" />
            <text x={Math.min(x(cutoff) + 7, 570)} y="17">
              Prévision à {format(cutoff, 2)} s
            </text>
            {series.map((line) => (
              <g key={line.id} data-series={line.id}>
                <path
                  d={path(line.points)}
                  stroke={line.color}
                  fill="none"
                  strokeWidth="2"
                  strokeDasharray={line.dash}
                />
                {line.points.length === 1 && finite(line.points[0].surface_temperature_c) && (
                  <circle
                    cx={x(line.points[0].time_s)}
                    cy={y(line.points[0].surface_temperature_c)}
                    r="3"
                    fill={line.color}
                  />
                )}
              </g>
            ))}
          </svg>
          <div className="prevention-coverage">
            {series.map((line) => (
              <span key={line.id} data-coverage={line.id}>
                {line.label} :{' '}
                {line.points.length
                  ? `${format(line.points[0].time_s, 2)}–${format(line.points.at(-1)?.time_s, 2)} s`
                  : 'indisponible'}
              </span>
            ))}
          </div>
          <p className="prevention-note">
            Les courbes s’arrêtent aux derniers points disponibles, y compris à la limite de validité
            thermique. La pyrolyse calculée ne constitue pas une preuve d’allumage.
          </p>
        </>
      ) : (
        <div className="prevention-empty">
          {assessment
            ? 'Aucune série thermique disponible pour ce composant et ce scénario.'
            : 'Lancez une analyse pour afficher l’historique simulé et les prévisions disponibles.'}
        </div>
      )}
    </section>
  );
}
