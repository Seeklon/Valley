import { describe, expect, it } from 'vitest';
import {
  missionBracket,
  missionGridAxes,
  missionPosition,
  missionSampleIndices,
  missionScalar,
  missionScales,
  missionVelocity,
} from './mission-rendering';
import type { Frame } from './types';

const first: Frame = {
  time_s: 1,
  shape: [1, 1, 3],
  bounds_m: [1, 1, 2],
  sample_positions_m: [
    [0.5, 0.5, 0.2],
    [0.5, 0.5, 0.75],
    [0.5, 0.5, 1.8],
  ],
  valid_mask: [true, true, false],
  temperature_c: [20, 80, 1000],
  smoke_kg_m3: [0, 0.0001, 2],
  velocity_m_s: [0, 0, 0, 1, 0, 0, 30, 40, 0],
};

const second: Frame = {
  ...first,
  time_s: 3.5,
  temperature_c: [40, 160, 1000],
  smoke_kg_m3: [0.00002, 0.0003, 2],
  velocity_m_s: [0, 0.4, 0, 0, 0, 1, 30, 40, 0],
};

describe('interpolation temporelle des champs enregistrés', () => {
  it('interpole aux vrais timestamps irréguliers sans déplacer les échantillons', () => {
    const bracket = missionBracket([second, first], 2)!;
    expect(bracket.mix).toBe(0.4);
    expect(missionScalar(bracket, 1, 'temperature_c')).toBe(112);
    expect(missionScalar(bracket, 0, 'smoke_kg_m3')).toBeCloseTo(0.000008);
    expect(missionVelocity(bracket, 1)).toEqual([0.6, 0, 0.4]);
    expect(missionPosition(bracket.from, 1)).toEqual([0.5, 0.5, 0.75]);
  });

  it('ne crée ni observation hors enregistrement ni feu dans un champ absent', () => {
    expect(missionBracket([], 2)).toBeNull();
    expect(missionBracket([first], Number.NaN)).toBeNull();
    expect(missionBracket([first, second], -20)?.from).toBe(first);
    expect(missionBracket([first, second], 200)?.from).toBe(second);
    const bracket = missionBracket([{ ...first, smoke_kg_m3: undefined }], 1)!;
    expect(missionScalar(bracket, 0, 'smoke_kg_m3')).toBeNull();
  });

  it('garde un zéro mesuré, rejette null et les cellules solides à chacun des deux instants', () => {
    const missing: Frame = { ...second, temperature_c: [null, 160, 1000], valid_mask: [true, false, false] };
    const between = missionBracket([first, missing], 2)!;
    expect(missionScalar(between, 0, 'temperature_c')).toBeNull();
    expect(missionScalar(between, 1, 'temperature_c')).toBeNull();
    expect(missionScalar(between, 2, 'temperature_c')).toBeNull();
    expect(missionScalar(missionBracket([first, missing], 1)!, 0, 'smoke_kg_m3')).toBe(0);
    expect(missionVelocity(missionBracket([first], 1)!, 0)).toEqual([0, 0, 0]);
  });

  it('rejette un vecteur partiellement absent et un masque tronqué', () => {
    const broken: Frame = { ...second, velocity_m_s: [1, null, 1, 0, 0, 1], valid_mask: [true] };
    expect(missionVelocity(missionBracket([first, broken], 2)!, 0)).toBeNull();
    expect(missionScalar(missionBracket([first, broken], 2)!, 1, 'temperature_c')).toBeNull();
  });

  it('refuse de fondre des grilles décalées même si leur forme est identique', () => {
    const moved: Frame = {
      ...second,
      sample_positions_m: [
        [0.5, 0.5, 0.3],
        [0.5, 0.5, 0.75],
        [0.5, 0.5, 1.8],
      ],
    };
    const bracket = missionBracket([first, moved], 2)!;
    expect(bracket.compatible).toBe(false);
    expect(missionScalar(bracket, 1, 'temperature_c')).toBeNull();
    expect(missionVelocity(bracket, 1)).toBeNull();
    expect(missionScalar(missionBracket([first, moved], 3.5)!, 1, 'temperature_c')).toBe(160);
  });
});

describe('échelles et masque spatial de mission', () => {
  it('fixe les bornes sur toute la séquence et exclut les maxima solides', () => {
    const scales = missionScales([first, second]);
    expect(scales.temperature).toEqual({ min: 20, max: 200, unit: '°C', available: true });
    expect(scales.smoke.max).toBeCloseTo(0.0003);
    expect(scales.airflow.max).toBe(1);
    expect(missionScales([second, first])).toEqual(scales);
    expect(missionScales([]).smoke.available).toBe(false);
    expect(missionScales([{ ...first, smoke_kg_m3: [0, 0, 0] }]).smoke.available).toBe(true);
  });

  it('conserve les axes réels nonuniformes pour masquer les cellules sans donnée', () => {
    expect(missionGridAxes(first)).toEqual([[0.5], [0.5], [0.2, 0.75, 1.8]]);
    expect(
      missionGridAxes({
        ...first,
        sample_positions_m: [
          [0.5, 0.5, 0.2],
          [0.51, 0.5, 0.75],
          [0.5, 0.5, 1.8],
        ],
      }),
    ).toBeNull();
    expect(
      missionGridAxes({
        ...first,
        sample_positions_m: [
          [0.5, 0.5, 0.2],
          [0.5, 0.5, 1.8],
          [0.5, 0.5, 0.75],
        ],
      }),
    ).toBeNull();
  });

  it('reconnaît le repère z-fast 3D et ne remplace pas des positions explicites manquantes', () => {
    const grid: Frame = { time_s: 0, shape: [2, 2, 2], bounds_m: [2, 4, 6] };
    expect(missionGridAxes(grid)).toEqual([
      [0.5, 1.5],
      [1, 3],
      [1.5, 4.5],
    ]);
    expect(missionPosition({ ...first, sample_positions_m: [] }, 0)).toBeNull();
  });

  it('borne le rendu sans retirer les grands maxima des échelles', () => {
    const frame: Frame = { time_s: 0, shape: [30, 30, 30], bounds_m: [3, 3, 3] };
    const indices = missionSampleIndices(frame);
    expect(indices).toHaveLength(12_000);
    expect(new Set(indices).size).toBe(12_000);
    expect(indices[0]).toBe(0);
    expect(indices.at(-1)).toBeLessThan(27_000);
    expect(missionSampleIndices({ ...frame, shape: [0, 30, 30] })).toEqual([]);
  });
});
