# Contrats de l’application — v1

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
- IDs des quatre scènes : `habitat`, `cargo`, `crossflow`, `soyuz`.
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

## Paramètres et provenance complémentaires

Le schéma complet est défini par `backend/ignis/schema.py` et exposé par `/docs`
et `/openapi.json`. Les clés inconnues, valeurs non finies et durées incohérentes
sont refusées. Les entrées physiques utilisent des unités SI ; l’oxygène est
exprimé en pourcentage volumique et la gravité en multiples de 9,80665 m/s².

- `ignition_kind` : `thermal` ou `resistive`. Le chauffage résistif exige le
  mode couplé ; `current_a² × resistance_ohm` remplace la puissance de chauffage
  du solide. La puissance chimique libérée est une mesure distincte.
- `mesh_cell_m` : maille cible entre 0,1 et 0,4 m ; les dimensions réelles de
  cellules et les bornes discrétisées figurent dans le manifeste de compilation.
- `sample_shape` : `[8,10,4]` pour cette version. Une frame ajoute `valid_mask`
  et `sample_positions_m` ; les valeurs dans les solides sont `null`.
- `model_id` : `field-mlp-v2` ou `metrics-forest-v2`. Le modèle tabulaire renvoie
  `frames: []`, avec ses métriques et sa réserve explicite.
- Les prédictions contrôlent le domaine, le maillage et l’identité physique
  version 2 de la scène. Les anciennes représentations entières/flottantes
  équivalentes sont normalisées ; les hashes exacts des fichiers FDS restent
  indépendants de cette normalisation.

La provenance du résultat distingue `origin: simulation` et `origin: prediction`,
versions, empreintes, statut scientifique et `warnings`. Les erreurs publiées
des modèles et les limites de cohérence restent dans les exports.

## Campagnes

POST `/api/campaigns` accepte `count` (2–100), `seed`, `scene_ids`,
`base_config` et `ranges`. Les plages portent sur `airflow_m_s`,
`oxygen_percent`, `ignition_power_w` et `gravity_g`. Le plan stratifié
est déterministe pour une même spécification. Le manifeste et ses jobs sont
créés dans une seule transaction ; le calcul est séquentiel.

GET `/api/campaigns/{id}` expose l’avancement ; POST
`/api/campaigns/{id}/cancel` demande l’arrêt. L’export ZIP via GET
`/api/campaigns/{id}/export` devient disponible après terminaison et contient
les entrées, provenances et métriques Parquet des runs terminés. Les champs
spatiaux sont accessibles dans les exports individuels.

## Interprétation NASA avec Codex

POST `/api/insights` accepte `config` et `question` (1 500 caractères maximum).
La réponse contient `summary`, `method`, `model`, `sources`, `facts` et `limits`.
Le classement est calculé avec des critères documentaires explicites.

`method=codex_grounded_in_nasa_evidence` signifie que Codex a reçu les faits
archivés et que le format de citation de sa réponse a passé les contrôles ;
cela ne constitue pas une validation scientifique du texte. Les mesures restent
dans les faits sourcés. Le modèle effectivement utilisé est rapporté lorsqu’il
est fourni par le CLI. L’appel utilise l’authentification Codex Windows existante.

Si Codex est absent, occupé ou échoue, `method=extractive_evidence`, `model=null`
et une explication dans `limits` identifient la synthèse de secours. Une seule
requête Codex s’exécute à la fois ; délai maximal 110 s et cache de 32 réponses.
Le backend n’utilise pas Ollama.

## Attribution de fichiers

- Coordinateur : backend API/runtime/ML, scripts distants, docs générales et intégration.
- Blender : `tools/blender/`, `scenes/`, `docs/SCENES.md`.
- Frontend et lanceurs Windows : `web/`, `backend/ignis/windows_process.py`,
  `tools/windows/` et tests de processus associés.
- Physique : `backend/ignis/physics/`, `tests/physics/`, `docs/PHYSICS.md`.
Les évolutions de contrats sont coordonnées avant modification des appelants.
