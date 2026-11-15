# POC chaleur : modèle et contrat d'export

Décision avant entraînement du 14 novembre 2026 : un classifieur spatial 3D
prédit, aux coordonnées réellement échantillonnées par FDS, le dépassement
`T >= température ambiante + 5 °C`. Aucune température ML ni fumée n'est produite.
Le score sigmoïde est non calibré ; ce n'est pas une probabilité de départ de feu.

## Protocole figé avant le premier fit

- Réutilisation du corpus compact vérifié : 120 cas train, 40 validation,
  40 test historiques. Ces derniers ont déjà été consultés ; les qualifier de
  « géométries exclues du fitting », jamais de test vierge.
- U-Net 3D largeur 16, un logit chaleur, 54 entrées géométrie/matériaux/source/
  conditions/temps, aucune entrée issue des températures ou de la fumée.
- BCE équilibrée entre points chauds et fond par frame active ; les frames
  entièrement froides conservent leur perte de fond. Aucun point manquant ne
  contribue. Échantillonnage à masse égale par cas, mélange moitié temps uniforme
  et moitié temps ayant un dépassement observé, seulement sur les cas train.
- Un seuil commun et le checkpoint sont sélectionnés par la **moyenne des F1
  microgravité et Terre sur validation**, sur tous les points/temps observés
  après t=0. Seuils fixés : sigmoid(-12 à +12 par pas 0,1), plus tout froid.
  Égalité de seuil : moins de faux positifs puis seuil supérieur.
- Baselines tout froid et `exp(-distance au patch source en mètres)`, cette
  dernière constante dans le temps. Son seuil suit la même sélection validation.
- Le test historique n'est évalué qu'après gel des poids et de tous les seuils.
  Tous les cas, métriques et candidats validation sont conservés.
- Premier essai borné à 650 secondes, réservation finale de 150 secondes ;
  plafond cumulé autorisé 20 minutes GPU, vérification comprise, au plus une
  correction justifiée par la validation. Aucun FDS supplémentaire lancé.

## JSON servi à la démonstration

`demo/hotspots.json` est l'index léger ; chaque cas est chargé à la demande depuis
`demo/cases/{id}.json`. Noms exacts :

```json
{
  "schema_version": "hotspot-poc-1",
  "generated_at": "ISO-8601 UTC",
  "metrics_time_filter": "time_s > 0",
  "model": {
    "id": "hotspot-poc-20261114",
    "name": "U-Net 3D — classification chaleur",
    "trained_at": "ISO-8601 UTC",
    "device": "NVIDIA GeForce RTX 4070 Ti",
    "heat_delta_c": 5,
    "score_threshold": 0.5,
    "score_semantics": "uncalibrated_hotspot_class_score",
    "training_seconds": 0,
    "total_compute_seconds": 0,
    "weights_sha256": "sha256",
    "dataset_sha256": "sha256"
  },
  "metrics": {"train": {}, "validation": {}, "test": {}},
  "baselines": {},
  "cases": [{
    "id": "case-id", "split": "validation", "layout_id": "layout-id",
    "evaluation_role": "validation", "family": "family",
    "gravity_g": 0.0001, "incident_type": "overheating",
    "ambient_temperature_c": 20, "airflow_m_s": 0.1,
    "peak_temperature_c": 30, "metrics": {}, "url": "./cases/case-id.json"
  }],
  "default_case_id": "case-id",
  "example_cases": {"representative": "case-id", "failure": "case-id", "cold_control": "case-id"},
  "limitations": []
}
```

Les nombres ci-dessus sont uniquement illustratifs du **schéma**, pas des
résultats. Chaque métrique expose `tp`, `fp`, `fn`, `tn`, `n_valid`, `precision`,
`recall`, `f1`, `iou`, `false_positive_rate`. Ratios dans [0,1] ; `null` quand le
dénominateur vaut zéro. Les agrégats ajoutent `groups.microgravity`, `groups.earth`,
`groups.sample_inactive`, `groups.sample_active`, `groups.incident_type`,
`balanced_gravity_f1`, `active_case_macro_f1` et le nombre de contrôles avec alarme.

```json
{
  "schema_version": "hotspot-poc-1", "id": "case-id", "split": "validation",
  "score_threshold": 0.5, "heat_delta_c": 5, "metrics_time_filter": "time_s > 0",
  "scene": {
    "id": "layout-id", "name": "layout name", "bounds_m": [4, 6, 3],
    "objects": [{"id": "object", "role": "equipment", "material_id": "aluminium", "center_m": [1, 1, 1], "size_m": [1, 1, 1]}],
    "vents": [{"id": "vent", "role": "inlet", "center_m": [0, 2, 1], "size_m": [0, 1, 1], "normal": [1, 0, 0]}],
    "source": {"position_m": [1, 1, 1.5]},
    "geometry_semantics": "compiled FDS axis-aligned boxes"
  },
  "conditions": {"ambient_temperature_c": 20, "gravity_g": 0.0001, "airflow_m_s": 0.1, "oxygen_percent": 21, "incident_type": "overheating", "source_position_m": [1, 1, 1.5], "power_w": 100, "source_duration_s": 5, "duration_s": 30},
  "sample_positions_m": [[0.1, 0.1, 0.1]], "shape": [12, 16, 8],
  "metrics": {},
  "frames": [{"time_s": 0, "valid_mask": [true], "temperature_c": [20], "hotspot_score": [0.2], "hotspot_truth": [false], "predicted_hot_mask": [false]}]
}
```

Les objets et évents sont les proxies **compilés FDS**, coordonnées réelles du
simulateur. Les arrays ont la même longueur et le même ordre de points ; t=0
reste visible mais exclu de toutes les métriques. Les valeurs manquantes sont
`null` et masquées, jamais assimilées à froid. Le seuil thermique est inclusif,
comme le seuil ML. Les float32 sont exportés sans arrondi destructeur ; les
masques `hotspot_truth` et `predicted_hot_mask` permettent une contre-vérification
exacte sans PyTorch. Aucun lissage ni interpolation n'est présenté comme mesure.

Le cas affiché par défaut est la médiane inférieure d'IoU parmi les validations
microgravité avec dépassement observé. L'échec proposé est l'IoU minimal du même
groupe et le contrôle le premier identifiant microgravité sans dépassement. Ce
choix évite de mettre le meilleur résultat en vitrine ; tous les 200 cas restent
accessibles, y compris les erreurs. Aucun déploiement de service n'est effectué
par le script ML.

## Une correction motivée par la validation

Au pas 8 000 du premier essai, la perte train continuait à baisser alors que le
meilleur F1 moyen validation restait à 0,324985 (pas 4 000), contre 0,197583 pour
la proximité du patch source. La décision de l'unique correction a été annoncée
avant lecture des résultats du test historique : ajout de 0,5 fois une perte
soft Dice sur les frames actives et augmentation par réflexions horizontales
X/Y indépendantes, chacune de probabilité 0,5. Les coordonnées, positions de
source, déplacements relatifs, vitesses aux évents, géométrie, matériaux, labels
et masques sont transformés ensemble. Aucune réflexion verticale : gravité et
face supérieure du patch sont préservées. Les contrôles froids gardent leur BCE.

Ce sont des pénalités supervisées des erreurs, pas du reinforcement learning.
Le second essai garde les partitions et la sélection par F1 validation ; aucun
troisième essai n'est prévu. Le premier essai complet a consommé 266,703 secondes
avec vérification et export. Le second est plafonné à 600 secondes, soit un
plafond cumulé de 866,703 secondes, inférieur aux 20 minutes autorisées.

Le débit est mesuré sur 25 pas utiles après 3 pas de chauffe par taille de batch,
avec seulement des données train, puis état initial et seed restaurés avant le
fit. Les résultats mesurés sont 2 326, 6 015 et 6 400 exemples/s pour les batchs
32, 64 et 128. Le batch 128 est retenu. Les masques sont vérifiés dans le cache
CPU une fois ; les synchronisations inutiles par pas sont supprimées et le
tirage des indices reste sur CUDA. Les valeurs non finies restent contrôlées
au premier pas, à chaque validation, et avant chaque export.

Mesure effective `nvidia-smi` pendant le second entraînement : 98 % d'utilisation
GPU sur 11 échantillons consécutifs entre 21:33:44,918 et 21:33:47,560 UTC, environ
157 W, 3,65 Go VRAM totale. La charge baisse pendant les validations et exports.
Le plafond de 5 Go de l'allocateur concerne la mémoire, pas le taux d'utilisation
du GPU ; le relever n'était pas nécessaire pour ce réseau de 379 029 paramètres.

Les sources exactes exécutées, tests, poids, candidats de validation, rapports,
logs et exports de chaque essai sont conservés dans les dossiers `fit1` et `fit2`
de `evidence/incidents/hotspot-poc/`, ainsi que dans leurs archives complètes.
Le choix entre ces deux essais utilise exclusivement la validation.

## Résultat retenu et limites mesurées

La décision finale est enregistrée dans `evidence/incidents/hotspot-poc/selection.json`
à **21:37:28 UTC le 14 novembre 2026**, uniquement à partir des deux fichiers de
sélection validation gelés. Le premier essai est retenu : F1 moyen microgravité/
Terre **0,324985**, contre **0,318139** pour la correction. Checkpoint au pas 4 000,
seuil commun **0,9478464126586914**. Aucun troisième essai. Les deux essais, leur
vérification, leur benchmark et leurs exports ont consommé **561,625 secondes**
de calcul au total, soit **9 min 21,6 s**.

Après cette décision, les métriques du test historique ont été lues pour le
diagnostic ; elles n'ont modifié ni les poids, ni les seuils, ni le choix d'essai.

| Géométries et gravité | Précision | Rappel | F1 | IoU | F1 proximité source |
|---|---:|---:|---:|---:|---:|
| Validation, microgravité | 0,396 | 0,396 | 0,396 | 0,247 | 0,377 |
| Validation, Terre | 0,201 | 0,346 | 0,254 | 0,145 | 0,018 |
| Historique exclu du fitting, microgravité | 0,523 | 0,471 | 0,496 | 0,330 | 0,403 |
| Historique exclu du fitting, Terre | 0,524 | 0,088 | 0,150 | 0,081 | 0,007 |

Les contrôles sans point chaud observé ont au moins une fausse alarme dans
**7/18 cas validation** et **8/22 cas historiques**. Une faible fréquence de faux
positifs par point ne signifie donc pas absence d'alarmes au niveau d'une scène.
En microgravité historique, plus de la moitié des points chauds sont manqués ;
sur Terre historique, le rappel n'est que 8,8 %. Le résultat est un **POC visuel
qui montre ses erreurs**, pas un système de sûreté fiable ou un modèle généraliste.

Le cas initial de la démo est
`procedural-0071-electrical-01-flaming-microg-c1`, choisi par la règle de médiane
validation décrite ci-dessus. L'échec et le contrôle proposés restent consultables
à côté des 197 autres cas. Les températures affichées sont toujours celles de FDS.

Poids retenus SHA256 :
`fe4f781dd50f66d27400f87beef91a2ce7c666c3319b143d5cb42c5f577ead60`.
Snapshot du corpus SHA256 :
`917965d170145c8415145e6290939fb1ec554fde85ac1419d2013b895b6ed4f3`.
Le ZIP complet retenu est `evidence/incidents/hotspot-poc/fit1-complete.zip` ;
`fit2-complete.zip` conserve intégralement l'essai correctif non retenu.
