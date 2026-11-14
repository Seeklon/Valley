# Contrats initiaux — v1

Coordonnées physiques : mètres, repère Blender Z vers le haut. Taille du
compartiment de référence : X=5.6, Y=8.0, Z=3.2 ; origine au coin inférieur.
Le GLB exporté par Blender applique la convention glTF Y-up ; la conversion des
points physiques pour Three.js est `(x, z, -y)`.

## Scènes

`scenes/catalog.json` contient `schema_version: 1`, `materials: [...]`, `scenes: [...]`.
Chaque scène contient `id`, `name`, `description`, `asset_url`, `bounds_m: [x,y,z]`,
`objects`, `vents`, `sensors`, `source_position_m`, `defaults`, `provenance`.

- Objet : `id`, `name`, `role`, `material_id`, `center_m`, `size_m`.
  `role` vaut `obstacle`, `fuel`, `wall` ou `decoration` ; décoration non physique.
- Vent : `id`, `role` (`inlet`/`outlet`), `center_m`, `size_m`,
  `normal`, `nominal_speed_m_s`. Bouches aux frontières du proxy initial.
- Capteur : `id`, `name`, `position_m`.
- Matériau : `id`, `name`, `description`, `color`, `provenance` ; propriétés
  physiques définies dans le backend et reliées aux sources, pas à la couleur.
- IDs des trois scènes : `habitat`, `cargo`, `crossflow`.
- Matériaux combustibles de départ : `cellulose`, `pmma` ; autres `aluminium`,
  `steel`, `glass`, `insulation`. Valeurs génériques identifiées comme telles.

## Requête d'exécution

POST `/api/runs` avec JSON :

```json
{
  "scene_id": "habitat",
  "mode": "physics",
  "source_model": "prescribed_source",
  "gravity_g": 0.0001,
  "airflow_m_s": 0.2,
  "oxygen_percent": 21,
  "material_id": "cellulose",
  "ignition_power_w": 500,
  "ignition_duration_s": 15,
  "duration_s": 60,
  "seed": 42
}
```

`mode` : `physics` ou `prediction`. `source_model` : `prescribed_source` ou
`coupled_combustion` ; ne pas promettre un mode avant disponibilité réelle.
Réponse immédiate `{id,status}`. GET `/api/runs/{id}` : `id`, `status`
(`queued`, `running`, `completed`, `failed`, `cancelled`), `progress`, `message`,
`config`, `result` lorsque terminé. POST `/api/runs/{id}/cancel` pour annuler.

## Résultat normalisé

`result` contient `provenance` (`engine`, `engine_version`, `model_id`,
`scientific_status`, `source_model`, `warnings`), `metrics`, `frames`, `summary`.

`metrics` : lignes avec `time_s`, `temperature_max_c`, `temperature_mean_c`,
`oxygen_mean_percent`, `smoke_mean_kg_m3`, `heat_release_w`, et `sensors`
(`sensor_id` vers mesure structurée).

`frames` : observations spatiales avec `time_s`, `shape: [nx,ny,nz]`, `bounds_m`,
`temperature_c`, `oxygen_percent`, `smoke_kg_m3`, `velocity_m_s`.
Les arrays scalaires sont aplatis avec z variant le plus vite, puis y, puis x.
`velocity_m_s` est aplati avec 3 composantes physiques par voxel. Les valeurs
non mesurées ne sont pas inventées ; une absence est indiquée dans la provenance.
Le format peut évoluer vers un endpoint binaire en conservant cette sémantique.

GET `/api/scenes` : catalogue. GET `/api/materials` : matériaux.
GET `/api/models` : modèles réellement disponibles, domaine, métriques et statut.
GET `/api/health` : statut worker/runtime et capacités réelles.
GET `/api/sources` : sources NASA et observations traçables.
GET `/api/runs/{id}/export` : archive avec config, métriques, provenance.

## Attribution de fichiers

- Coordinateur : backend API/runtime/ML, scripts distants, docs générales et intégration.
- Blender : `tools/blender/`, `scenes/`, `docs/SCENES.md`.
- Frontend : `web/` uniquement.
- Physique : `backend/ignis/physics/`, `tests/physics/`, `docs/PHYSICS.md`.
Les évolutions de contrats sont coordonnées avant modification des appelants.
