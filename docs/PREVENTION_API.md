# Contrat d'intégration prévention v1

Contrat de développement du 14 novembre 2026. Les résultats ne sont jamais des
fixtures en production. Deux calculs distincts : délai d'allumage appris sur des
points expérimentaux publiés dans un protocole restreint ; échauffement et
pyrolyse d'un modèle local exploratoire. Pas de probabilité réelle de feu dérivée
du nombre de scénarios simulés.

## Catalogue : GET /api/prevention/catalog

```typescript
type PreventionCatalog = {
  version: 'ignis-prevention-1';
  scene_ids: string[];
  default_scene_id: string;
  components: PreventionComponent[];
  defaults: PreventionConfig;
  parameters: Record<string, { label: string; unit: string; min: number; max: number; step: number }>;
  models: Record<string, unknown>[];
  limitations: string[];
};
type PreventionComponent = {
  id: string; scene_id: string; name: string;
  kind: 'wire' | 'battery'; material_id: string;
  position_m: [number, number, number]; object_id: string | null;
  current_factor: number;
  supported: boolean;
  provenance: string; limitations: string[];
};
```

Les emplacements sont hypothétiques, exprimés dans le repère physique Z-up.
Les fils de laboratoire ne sont pas les câblages qualifiés d'un Soyouz réel.
Le courant de chaque fil vaut `config.current_a * component.current_factor`.

## Analyse : POST /api/prevention/analyze

```typescript
type PreventionConfig = {
  scene_id: string;
  current_a: number;
  airflow_m_s: number;
  gravity_g: number;
  ambient_temperature_c: number;
  oxygen_percent: number;
  pressure_pa: number;
  duration_s: number;
  observation_cutoff_s: number;
  horizon_s: number;
  cutoff_s: number | null;
};
type ThermalPoint = {
  time_s: number;
  current_a: number;
  conductor_temperature_c: number;
  surface_temperature_c: number;
  pyrolyzed_fraction: number;
};
type PreventionResult = {
  id: string;
  config: PreventionConfig;
  observation_cutoff_s: number;
  horizon_s: number;
  origin: 'simulation_and_published_experiments';
  target: {
    event_kind: 'ignition';
    name: string; unit: 's'; criterion: string;
  };
  components: ComponentAssessment[];
  provenance: Record<string, unknown>;
  limitations: string[];
  export_url: string;
  evidence_snapshot: PreventionEvidence;
  evidence_snapshots_by_component: Record<string, PreventionEvidence>;
};
type ComponentAssessment = {
  component_id: string;
  status: 'available' | 'out_of_domain' | 'unsupported' | 'insufficient_history' | 'model_unavailable';
  reasons: string[];
  current_a: number;
  observations: ThermalPoint[]; // time <= observation_cutoff_s
  forecast: ThermalPoint[]; // modèle physique, time > observation_cutoff_s
  learned_forecast: { time_s: number; surface_temperature_c: number }[];
  estimate: {
    ignition_delay_s: number; // depuis mise sous courant
    remaining_time_s: number; // délai - instant choisi ; peut être négatif
    within_horizon: boolean;
    phase: 'before_estimated_ignition' | 'estimated_ignition_reached';
    model_id: string;
    domain: string;
    conditional_on: string;
  } | null;
  interval: { lower_s: number; upper_s: number; kind: string } | null;
  ignition_probability: null;
  thermal: {
    status: string;
    ignition_supported: false;
    summary: Record<string, unknown>;
    model_id: string | null;
    limitations: string[];
  } | null;
  evidence_ids: string[];
};
```

La prévision d'allumage ne sert que dans les conditions de l'expérience : même
fil, courant constant et maintenu, atmosphère et écoulement compatibles. Une
coupure, un autre matériau ou un écoulement forcé rendent cette prévision hors
domaine. Les modèles thermiques peuvent néanmoins explorer l'échauffement,
avec leur propre statut. `interval=null` signifie incertitude non quantifiée,
pas incertitude nulle. Ne pas transformer `within_horizon` en probabilité.

La courbe physique après l'instant choisi est une projection de scénario ; la
courbe `learned_forecast` est une vraie prédiction apprise utilisant seulement
les observations passées et les commandes futures déclarées. La disponibilité
de ces deux courbes n'établit pas une calibration d'allumage de la physique locale.

## Conclusions : GET /api/prevention/evidence

Query : `component_id`, `gravity_g`, `oxygen_percent`, `airflow_m_s`, `pressure_pa` facultatifs.

```typescript
type PreventionEvidence = {
  findings: {
    id: string; source_id: string; title: string; statement: string;
    epistemic_status: string; relevance: string; reasons: string[];
    evidence_quality: string;
    is_nasa_source: boolean;
    source: { name: string; url: string; locator: string };
    conditions: Record<string, unknown>;
    limitations: string[];
  }[];
  limitations: string[];
};
```

Classement : nombre de conditions explicitement incompatibles, mécanisme,
famille de matériau, gravité, nombre de conditions connues compatibles, puis
nature des preuves. Une condition inconnue n'est pas déclarée compatible.
La carte Guo complémentaire est présentée après les conclusions NASA et porte
`is_nasa_source=false`.
Il n'est pas le classement de risque des composants.

## Explication : POST /api/prevention/interpret

Entrée `{ analysis_id: string, component_id: string, question: string }`.
Sortie `{ summary: string, method: string, model: string|null,
evidence_ids: string[], limitations: string[] }`.
Codex reçoit seulement les résultats publics, limites et conclusions pertinentes.
Le repli extractif reste honnête si Codex est absent/occupé ou sa réponse invalide.

## Export : GET /api/prevention/analyses/{id}/export

ZIP avec `config.json`, `analysis.json`, `thermal_series.csv`,
`evidence_findings.json` et `README.txt`. Les instantanés de preuves et leurs
empreintes sont figés lors de l'analyse, y compris le classement par composant.
Un changement ultérieur du catalogue ne change pas l'export historique.
Les datasets et poids d'entraînement sont conservés séparément sur Windows.
