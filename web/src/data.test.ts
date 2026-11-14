import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CONFIG,
  domainWarnings,
  fieldAvailable,
  format,
  metricPath,
  nearestByTime,
  toWorld,
  usableModel,
  voxelPosition,
} from './data';
import type { Frame, Metric, ModelInfo } from './types';

describe('repère physique et grille FDS', () => {
  it('conserve les axes physiques lors du passage Z-up vers Y-up', () => {
    expect(toWorld([2, 5, 3])).toEqual([2, 3, -5]);
  });
  it('lit z en premier dans les tableaux aplatis et place les valeurs aux centres', () => {
    expect(voxelPosition(0, [2, 2, 2], [4, 6, 8])).toEqual([1, 1.5, 2]);
    expect(voxelPosition(1, [2, 2, 2], [4, 6, 8])).toEqual([1, 1.5, 6]);
    expect(voxelPosition(2, [2, 2, 2], [4, 6, 8])).toEqual([1, 4.5, 2]);
    expect(voxelPosition(7, [2, 2, 2], [4, 6, 8])).toEqual([3, 4.5, 6]);
  });
});

describe('absence de mesures', () => {
  const base: Frame = { time_s: 0, shape: [1, 1, 2], bounds_m: [1, 1, 2] };
  it('préserve le zéro mesuré et ne transforme pas null en zéro', () => {
    expect(format(0, 0)).toBe('0');
    expect(format(null)).toBe('—');
    expect(format(Number.NaN)).toBe('—');
    expect(fieldAvailable({ ...base, smoke_kg_m3: [0, 0] }, 'smoke')).toBe(true);
    expect(fieldAvailable({ ...base, smoke_kg_m3: [null, null] }, 'smoke')).toBe(false);
  });
  it('exclut les cellules solides et les vecteurs incomplets', () => {
    expect(
      fieldAvailable({ ...base, temperature_c: [100, null], valid_mask: [false, true] }, 'temperature'),
    ).toBe(false);
    expect(fieldAvailable({ ...base, velocity_m_s: [1, null, 1, null, null, null] }, 'airflow')).toBe(false);
    expect(fieldAvailable({ ...base, velocity_m_s: [0, 0, 0, null, null, null] }, 'airflow')).toBe(true);
  });
  it('ne relie pas deux observations séparées par une mesure manquante', () => {
    const rows: Metric[] = [
      { time_s: 0, temperature_max_c: 20 },
      { time_s: 1 },
      { time_s: 2, temperature_max_c: 40 },
    ];
    const path = metricPath(rows, 'temperature_max_c', 100, 100, [0, 100], 2);
    expect(path).toBe('M0.00,80.00 M100.00,60.00');
  });
  it('sélectionne une observation réelle sans inventer une frame intermédiaire', () => {
    const frames = [
      { time_s: 0, id: 'a' },
      { time_s: 2, id: 'b' },
    ];
    expect(nearestByTime(frames, 1.7)?.id).toBe('b');
    expect(nearestByTime([], 1)).toBeUndefined();
  });
});

describe('disponibilité et domaine du modèle réellement choisi', () => {
  const models: ModelInfo[] = [
    {
      id: 'first',
      loaded: true,
      status: 'ready',
      domain: { airflow_m_s: [0.1, 0.3], material_id: ['cellulose'], scene_id: ['habitat'] },
    },
    {
      id: 'second',
      loaded: true,
      status: 'ready',
      domain: { airflow_m_s: { min: 0.5, max: 0.8 }, material_id: ['pmma'] },
    },
  ];
  it('exige des poids chargés, pas seulement des métadonnées présentes', () => {
    expect(usableModel({ id: 'metadata-only', status: 'ready' })).toBe(false);
    expect(usableModel({ id: 'failed', loaded: true, status: 'failed' })).toBe(false);
    expect(usableModel(models[0])).toBe(true);
  });
  it('accepte les bornes et signale la sortie du domaine numérique ou catégoriel', () => {
    expect(domainWarnings({ ...DEFAULT_CONFIG, mode: 'prediction', airflow_m_s: 0.1 }, models)).toEqual([]);
    expect(
      domainWarnings(
        { ...DEFAULT_CONFIG, mode: 'prediction', airflow_m_s: 0.7, material_id: 'pmma' },
        models,
      ),
    ).toHaveLength(2);
  });
  it('vérifie le modèle sélectionné et ne bloque pas la simulation physique', () => {
    expect(
      domainWarnings(
        { ...DEFAULT_CONFIG, mode: 'prediction', model_id: 'second', airflow_m_s: 0.6, material_id: 'pmma' },
        models,
      ),
    ).toEqual([]);
    expect(domainWarnings({ ...DEFAULT_CONFIG, mode: 'physics', airflow_m_s: 0.9 }, models)).toEqual([]);
    expect(
      domainWarnings({ ...DEFAULT_CONFIG, mode: 'prediction', model_id: 'removed-model' }, models),
    ).toEqual(['Le modèle sélectionné n’est plus chargé. Choisissez un modèle disponible.']);
  });
  it('contrôle le domaine imbriqué du registre et la gravité discrète', () => {
    const registered: ModelInfo = {
      id: 'spatial',
      loaded: true,
      domain: {
        scene_ids: ['habitat'],
        materials: ['cellulose'],
        source_model: 'prescribed_source',
        gravity_values: [0.0001, 1],
        ranges: { airflow_m_s: [0.05, 0.4], duration_s: [2, 60] },
      },
    };
    expect(domainWarnings({ ...DEFAULT_CONFIG, mode: 'prediction' }, [registered])).toEqual([]);
    expect(
      domainWarnings(
        {
          ...DEFAULT_CONFIG,
          mode: 'prediction',
          gravity_g: 0.2,
          scene_id: 'soyuz',
          duration_s: 120,
          source_model: 'coupled_combustion',
        },
        [registered],
      ),
    ).toHaveLength(4);
  });
});
