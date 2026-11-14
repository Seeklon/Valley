import { ChevronDown, Flame, Orbit, SlidersHorizontal, Wind, Zap } from 'lucide-react';
import { format } from '../data';
import type { Material, RunConfig, Scene, SourceModel } from '../types';

interface Props {
  config: RunConfig;
  onChange: (config: RunConfig) => void;
  scenes: Scene[];
  materials: Material[];
  onSceneChange: (id: string) => void;
  disabled: boolean;
  sourceModels: SourceModel[];
}

interface RangeProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (value: number) => void;
  disabled?: boolean;
  precision?: number;
}

function Range({ label, value, min, max, step, unit, onChange, disabled, precision = 1 }: RangeProps) {
  const id = label.toLowerCase().replaceAll(' ', '-');
  return (
    <div className="range-control">
      <div className="range-heading">
        <label htmlFor={id}>{label}</label>
        <span className="range-value">
          {format(value, precision)} <small>{unit}</small>
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        disabled={disabled}
        style={{ '--range-progress': `${((value - min) / (max - min)) * 100}%` } as React.CSSProperties}
      />
      <div className="range-extents">
        <span>
          {min} {unit}
        </span>
        <span>
          {max} {unit}
        </span>
      </div>
    </div>
  );
}

export default function Parameters({
  config,
  onChange,
  scenes,
  materials,
  onSceneChange,
  disabled,
  sourceModels,
}: Props) {
  const patch = (key: keyof RunConfig, value: string | number) => onChange({ ...config, [key]: value });
  return (
    <aside className="panel parameters-panel" aria-label="Paramètres de simulation">
      <div className="panel-heading">
        <div>
          <SlidersHorizontal size={16} />
          <h2>Configuration</h2>
        </div>
        <span className="eyebrow">SI</span>
      </div>
      <div className="parameter-section scene-section">
        <label className="control-label" htmlFor="scene-select">
          Environnement
        </label>
        <div className="select-wrap">
          <select
            id="scene-select"
            value={config.scene_id}
            onChange={(event) => onSceneChange(event.target.value)}
            disabled={disabled || !scenes.length}
          >
            {!scenes.length && <option value="habitat">Catalogue indisponible</option>}
            {scenes.map((scene) => (
              <option key={scene.id} value={scene.id}>
                {scene.name}
              </option>
            ))}
          </select>
          <ChevronDown size={15} />
        </div>
        <p className="field-help">
          {scenes.find((scene) => scene.id === config.scene_id)?.description ??
            'Connectez le service pour charger les scènes et leurs propriétés.'}
        </p>
      </div>
      <fieldset disabled={disabled} className="parameter-section">
        <legend>
          <Orbit size={15} /> Gravité & atmosphère
        </legend>
        <div className="segmented gravity-switch">
          <button
            className={config.gravity_g < 0.01 ? 'active' : ''}
            onClick={() => patch('gravity_g', 0.0001)}
            type="button"
          >
            Microgravité <span>10⁻⁴ g</span>
          </button>
          <button
            className={config.gravity_g >= 0.01 ? 'active' : ''}
            onClick={() => patch('gravity_g', 1)}
            type="button"
          >
            Terre <span>1 g</span>
          </button>
        </div>
        <Range
          label="Oxygène"
          value={config.oxygen_percent}
          min={15}
          max={30}
          step={0.5}
          unit="% vol."
          onChange={(value) => patch('oxygen_percent', value)}
        />
      </fieldset>
      <fieldset disabled={disabled} className="parameter-section">
        <legend>
          <Wind size={15} /> Ventilation
        </legend>
        <Range
          label="Vitesse d’entrée"
          value={config.airflow_m_s}
          min={0}
          max={1}
          step={0.01}
          unit="m/s"
          precision={2}
          onChange={(value) => patch('airflow_m_s', value)}
        />
        <p className="field-help">Les positions et directions des bouches sont définies par la scène.</p>
      </fieldset>
      <fieldset disabled={disabled} className="parameter-section">
        <legend>
          <Flame size={15} /> Combustible & allumage
        </legend>
        <label className="control-label" htmlFor="material-select">
          Matériau de l’échantillon
        </label>
        <div className="select-wrap">
          <select
            id="material-select"
            value={config.material_id}
            onChange={(event) => patch('material_id', event.target.value)}
          >
            {!materials.length && <option value="cellulose">En attente du catalogue</option>}
            {materials
              .filter((material) => ['cellulose', 'pmma'].includes(material.id))
              .map((material) => (
                <option key={material.id} value={material.id}>
                  {material.name}
                </option>
              ))}
          </select>
          <ChevronDown size={15} />
        </div>
        <div className="segmented ignition-switch">
          <button
            type="button"
            className={config.ignition_kind === 'thermal' ? 'active' : ''}
            onClick={() => patch('ignition_kind', 'thermal')}
          >
            <Flame size={12} />
            Thermique
          </button>
          <button
            type="button"
            className={config.ignition_kind === 'resistive' ? 'active' : ''}
            disabled={!sourceModels.includes('coupled_combustion')}
            onClick={() =>
              onChange({ ...config, ignition_kind: 'resistive', source_model: 'coupled_combustion' })
            }
          >
            <Zap size={12} />
            Résistif
          </button>
        </div>
        {config.ignition_kind === 'resistive' ? (
          <>
            <div className="two-inputs">
              <label>
                Intensité{' '}
                <span className="number-wrap">
                  <input
                    type="number"
                    value={config.current_a}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(event) => patch('current_a', Number(event.target.value))}
                  />
                  <span>A</span>
                </span>
              </label>
              <label>
                Résistance{' '}
                <span className="number-wrap">
                  <input
                    type="number"
                    value={config.resistance_ohm}
                    min={0.1}
                    max={1000}
                    step={1}
                    onChange={(event) => patch('resistance_ohm', Number(event.target.value))}
                  />
                  <span>Ω</span>
                </span>
              </label>
            </div>
            <div className="power-readout">
              <Zap size={12} />
              <span>
                I²R = <strong>{format(config.current_a ** 2 * config.resistance_ohm, 0)} W</strong>
              </span>
            </div>
            <p className="field-help">
              Échauffement résistif du solide, avec coupure à la fin de l’allumage. Ce modèle ne couvre pas
              les arcs ni les batteries.
            </p>
          </>
        ) : (
          <Range
            label={
              config.source_model === 'prescribed_source'
                ? 'Puissance du feu imposée'
                : 'Puissance d’allumage'
            }
            value={config.ignition_power_w}
            min={100}
            max={3000}
            step={50}
            unit="W"
            precision={0}
            onChange={(value) => patch('ignition_power_w', value)}
          />
        )}
        <div className="two-inputs">
          <label>
            {config.source_model === 'prescribed_source' ? 'Source active' : 'Allumage'}{' '}
            <span className="number-wrap">
              <input
                type="number"
                value={config.ignition_duration_s}
                min={1}
                max={Math.min(120, config.duration_s)}
                step={1}
                onChange={(event) => patch('ignition_duration_s', Number(event.target.value))}
              />
              <span>s</span>
            </span>
          </label>
          <label>
            Simulation{' '}
            <span className="number-wrap">
              <input
                type="number"
                value={config.duration_s}
                min={5}
                max={180}
                step={5}
                onChange={(event) => patch('duration_s', Number(event.target.value))}
              />
              <span>s</span>
            </span>
          </label>
        </div>
      </fieldset>
      <details className="advanced-settings">
        <summary>
          <Zap size={13} /> Modèle de source & reproductibilité
          <ChevronDown size={13} />
        </summary>
        <div>
          <label className="control-label" htmlFor="source-model">
            Source de combustion
          </label>
          <div className="select-wrap">
            <select
              id="source-model"
              value={config.source_model}
              disabled={disabled || !sourceModels.length}
              onChange={(event) =>
                onChange({
                  ...config,
                  source_model: event.target.value as SourceModel,
                  ignition_kind:
                    event.target.value === 'prescribed_source' ? 'thermal' : config.ignition_kind,
                })
              }
            >
              <option value="prescribed_source" disabled={!sourceModels.includes('prescribed_source')}>
                Puissance prescrite
              </option>
              <option value="coupled_combustion" disabled={!sourceModels.includes('coupled_combustion')}>
                Combustion couplée
              </option>
            </select>
            <ChevronDown size={13} />
          </div>
          <p className="field-help">
            {config.source_model === 'prescribed_source'
              ? 'Le feu est imposé : ce mode calcule le transport de ses effets.'
              : 'L’échauffement et la réaction dépendent des propriétés du matériau.'}
          </p>
          <label className="control-label" htmlFor="seed">
            Graine de génération
          </label>
          <input
            id="seed"
            className="text-input"
            type="number"
            value={config.seed}
            min={0}
            max={2147483647}
            step={1}
            disabled={disabled}
            onChange={(event) => patch('seed', Number(event.target.value))}
          />
        </div>
      </details>
    </aside>
  );
}
