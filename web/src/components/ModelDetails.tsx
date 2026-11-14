import { finite, format } from '../data';
import type { ModelInfo } from '../types';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function numberAt(value: unknown, ...path: string[]): number | undefined {
  let current = value;
  for (const key of path) current = record(current)[key];
  return finite(current) ? current : undefined;
}

const sceneNames: Record<string, string> = {
  habitat: 'Habitat',
  cargo: 'Cargo',
  crossflow: 'Ventilation traversante',
  soyuz: 'Soyouz',
};

function names(value: unknown, labels: Record<string, string> = {}): string | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map((item) => labels[String(item)] ?? String(item)).join(' · ');
}

export function ModelConsistency({ model, compact = false }: { model: ModelInfo; compact?: boolean }) {
  if (model.kind !== 'spatial_mlp') return null;
  const test = model.metrics?.test;
  const observations = numberAt(test, 'frames');
  const meanAboveMax = numberAt(test, 'consistency', 'mean_above_global_max_frames');
  const sampleAboveMax = numberAt(test, 'consistency', 'sample_above_global_max_frames');
  return (
    <aside className={`model-consistency-note${compact ? ' compact' : ''}`}>
      <strong>Prévisualisation exploratoire</strong>
      <p>
        Le réseau ne contraint pas la cohérence entre la température moyenne, le maximum et les valeurs du
        champ 3D.
      </p>
      {!compact &&
        observations !== undefined &&
        meanAboveMax !== undefined &&
        sampleAboveMax !== undefined && (
          <p className="consistency-observations">
            Sur {format(observations, 0)} instants de test, la moyenne dépasse le maximum dans{' '}
            {format(meanAboveMax, 0)} cas (jusqu’à{' '}
            {format(numberAt(test, 'consistency', 'max_mean_above_global_max_c'), 2)} °C d’écart), et une
            valeur du champ dépasse ce maximum dans {format(sampleAboveMax, 0)} cas (jusqu’à{' '}
            {format(numberAt(test, 'consistency', 'max_sample_above_global_max_c'), 2)} °C).
            {finite(model.consistency_tolerance_c) && (
              <> Seuil de comptage : {format(model.consistency_tolerance_c, 2)} °C.</>
            )}
          </p>
        )}
    </aside>
  );
}

export function ModelDomain({ domain = {} }: { domain?: ModelInfo['domain'] }) {
  const rows: { label: string; value?: string }[] = [
    { label: 'Scènes', value: names(domain.scene_ids ?? domain.scene_id, sceneNames) },
    {
      label: 'Matériaux',
      value: names(domain.materials ?? domain.material_id, { cellulose: 'Cellulose', pmma: 'PMMA' }),
    },
  ];
  if (Array.isArray(domain.gravity_values))
    rows.push({
      label: 'Gravités discrètes',
      value: domain.gravity_values.map((value) => `${format(value, value === 1 ? 0 : 4)} g`).join(' · '),
    });
  if (typeof domain.source_model === 'string')
    rows.push({
      label: 'Source du feu',
      value:
        domain.source_model === 'prescribed_source'
          ? 'Puissance prescrite'
          : domain.source_model === 'coupled_combustion'
            ? 'Combustion couplée'
            : domain.source_model,
    });
  const ranges = { ...domain, ...record(domain.ranges) };
  for (const [key, label, unit, precision] of [
    ['airflow_m_s', 'Ventilation', 'm/s', 2],
    ['oxygen_percent', 'Oxygène', '% vol.', 0],
    ['ignition_power_w', 'Puissance du feu', 'W', 0],
    ['ignition_duration_s', 'Source active', 's', 0],
    ['duration_s', 'Durée du scénario', 's', 0],
  ] as const) {
    const range = ranges[key];
    const limits = Array.isArray(range) ? range : [record(range).min, record(range).max];
    if (limits.length === 2 && limits.every(finite))
      rows.push({
        label,
        value: `${format(limits[0], precision)} à ${format(limits[1], precision)} ${unit}`,
      });
  }
  const visible = rows.filter((row) => row.value);
  return visible.length ? (
    <dl className="definition-list model-domain">
      {visible.map((row) => (
        <div key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  ) : (
    <p className="muted">
      {Object.keys(domain).length
        ? 'Les conditions détaillées sont conservées dans les métadonnées.'
        : 'Domaine non renseigné par le registre. L’applicabilité ne peut pas être établie.'}
    </p>
  );
}

export function ModelEvaluation({ model }: { model: ModelInfo }) {
  const metrics = model.metrics ?? {};
  const hasMainEvaluation = ['validation', 'test'].some((key) => Object.keys(record(metrics[key])).length);
  if (!hasMainEvaluation)
    return (
      <p className="muted">
        {Object.keys(metrics).length
          ? 'Les résultats détaillés sont conservés dans les métadonnées.'
          : 'Aucune mesure de validation publiée.'}
      </p>
    );

  const rows = [
    { label: 'Essais distincts', path: ['runs'], unit: '', precision: 0 },
    { label: 'Observations temporelles', path: ['frames'], unit: '', precision: 0 },
    {
      label: 'Température maximale · MAE',
      path: ['metric_errors', 'temperature_max_c', 'mae'],
      unit: '°C',
      precision: 2,
    },
    {
      label: 'Pic de température par essai · MAE',
      path: ['run_temperature_peak_mae_c'],
      unit: '°C',
      precision: 2,
    },
    {
      label: 'Puissance dégagée · MAE',
      path: ['metric_errors', 'heat_release_w', 'mae'],
      unit: 'W',
      precision: 1,
    },
  ];
  if (model.kind === 'spatial_mlp')
    rows.push(
      {
        label: 'Points chauds · MAE de température',
        path: ['heated_points_temperature_error_c', 'mae'],
        unit: '°C',
        precision: 2,
      },
      {
        label: 'Pic du champ 3D par essai · MAE',
        path: ['spatial_temperature_peak_mae_c'],
        unit: '°C',
        precision: 2,
      },
    );
  const soyuz = [
    { key: 'test_soyuz_microg', label: 'Microgravité' },
    { key: 'test_soyuz_earth', label: 'Terre' },
  ].filter(({ key }) => Object.keys(record(metrics[key])).length);
  return (
    <>
      <table className="model-evaluation-table">
        <caption>Erreur de prédiction par rapport aux simulations FDS</caption>
        <thead>
          <tr>
            <th scope="col">Mesure</th>
            <th scope="col">Validation</th>
            <th scope="col">Test</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {['validation', 'test'].map((split) => (
                <td key={split}>
                  {format(numberAt(metrics[split], ...row.path), row.precision)}
                  {row.unit && <small> {row.unit}</small>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="evaluation-note">
        MAE : erreur absolue moyenne. Les pics donnent un poids égal à chaque essai. Les observations d’un
        même essai sont corrélées ; elles ne représentent pas autant d’expériences indépendantes.
      </p>
      {model.kind === 'spatial_mlp' && (
        <p className="evaluation-note">
          Points chauds : observations de gaz dont la température FDS dépasse l’ambiante de 2 °C.
        </p>
      )}
      {soyuz.length > 0 && (
        <div className="model-coverage-note">
          <h4>Couverture du test Soyouz</h4>
          <table className="model-evaluation-table">
            <thead>
              <tr>
                <th scope="col">Régime</th>
                <th scope="col">Essais</th>
                <th scope="col">MAE du pic</th>
              </tr>
            </thead>
            <tbody>
              {soyuz.map(({ key, label }) => (
                <tr key={key}>
                  <th scope="row">{label}</th>
                  <td>{format(numberAt(metrics[key], 'runs'), 0)}</td>
                  <td>
                    {format(numberAt(metrics[key], 'run_temperature_peak_mae_c'), 2)} <small>°C</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Ce faible nombre d’essais limite la portée de l’évaluation sur Soyouz. L’erreur moyenne globale
            peut masquer des écarts importants sur cette scène.
          </p>
        </div>
      )}
    </>
  );
}
