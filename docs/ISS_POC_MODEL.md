# Modèle ISS : POC chaleur et fumée du 15 novembre 2026

Le livrable ciblé est une détection spatiale de chaleur et de suie dans trois
familles de volumes inspirés des modules de l'ISS. Il complète le POC chaleur
du 14 novembre, dont les poids, données et service restent préservés. Il ne
constitue pas une reproduction validée de l'ISS ni une prédiction d'allumage.

## Contrat fixé avant le premier entraînement

- Entrées : géométrie compilée, matériaux, zone source électrique imposée,
  ventilation aux frontières, gravité, conditions ambiantes et instant.
- Réseau : U-Net 3D existant de largeur 16, encodeur partagé et deux sorties
  logits indépendantes. Les observations FDS n'entrent jamais dans les entrées.
- Chaleur : température FDS supérieure ou égale à l'ambiante + 5 °C.
- Fumée : concentration de suie FDS supérieure ou égale à `1e-6 kg/m³`.
  La comparaison utilise la valeur physique du seuil en float64, y compris
  lorsque les observations source sont stockées en float32.
- Sorties : deux scores de classification non calibrés et les masques obtenus
  avec leurs seuils figés. Aucune température, concentration quantitative ou
  probabilité d'incendie n'est déduite des scores.
- Les temps initiaux et les mesures manquantes sont exclus des métriques.
  Chaque champ conserve son propre masque d'observation.

Le corpus prévu contient 108 trajectoires de 30 secondes, sur une grille de
12 × 16 × 8 sondes : 18 dispositions, trois familles de modules et six cas par
disposition. Les partitions prévues sont 72 / 18 / 18 pour apprentissage,
validation et test. Les familles sont communes aux partitions ; les
dispositions et signatures physiques compilées doivent être disjointes.
Ces effectifs sont un contrat prévu : le rapport d'exécution donne les
effectifs effectivement vérifiés et entraînés.

`ISSCaseStore` autorise ce protocole uniquement pour le dataset
`iss-poc-20261115-v1`. Il reprend sans modification la reconstruction FDS,
les signatures physiques, les contrôles de coordonnées et les empreintes de
`CaseStore`. Il ne modifie pas les règles des anciennes campagnes.

## Apprentissage et sélection

La BCE équilibre les deux champs, puis les points positifs et négatifs de
chaque champ observé. Les cas sans point positif conservent une perte sur leurs
fausses alertes. Chaque cas d'apprentissage reçoit la même masse de tirage ;
ses temps mélangent moitié uniforme et moitié avec au moins un champ actif.
Aucune sélection d'exemple d'apprentissage n'utilise le test.

Les seuils chaleur et fumée sont choisis séparément sur la validation. Leur
objectif est la moyenne des F1 des modules en microgravité. Un module sans
positif contribue zéro à cet objectif ; ses ratios sans dénominateur restent
`null` dans le rapport. Un seuil donnant toutes les observations froides est
un candidat explicite. Les égalités sont départagées par moins de faux
positifs, puis par un seuil plus élevé. Les candidats sont fixés avant fit :
sigmoïde des logits de −12 à 12, par pas de 0,1, plus le seuil tout-froid.

Le checkpoint maximise la moyenne des objectifs chaleur et fumée. Les mesures
Terre sont rapportées séparément et ne sélectionnent pas le modèle ISS.
Poids et seuils sont figés avant toute prédiction sur le test. Les baselines
« tout froid » et proximité de la source sont évaluées sur exactement les
mêmes sondes et instants ; les seuils de proximité suivent la même sélection
sur validation.

## Budget et GPU

La première tranche est limitée à 1 200 secondes, vérification du corpus et
export compris. La boucle réserve trois minutes pour l'évaluation finale,
l'export et la mesure d'inférence. Elle dispose de 20 000 étapes maximum,
avec validation toutes les 500 étapes. Une demande d'arrêt via `STOP` dans
le seul dossier de ce fit termine la boucle puis exporte le meilleur modèle
déjà validé.

Un verrou système exclusif sur le `runtime/compute.lock` du développement est
détenu pendant toute la vérification, l'entraînement et l'export. Il est acquis
avant CUDA, partagé avec l'API et le générateur, et relâché automatiquement en
cas d'arrêt du processus. `compute-lock.json` enregistre le chemin et le PID.

Un benchmark de 15 étapes mesurées par batch, après trois étapes de chauffe,
compare 32, 64, 128 et 256 exemples sur les données d'entraînement réelles.
Les poids sont réinitialisés après ce benchmark. Le batch maximise le débit
utile, sans charge artificielle. L'allocation PyTorch est bornée au minimum
de 82 % de la mémoire totale et 85 % de la mémoire libre initiale.

`gpu-telemetry.csv` mesure l'utilisation effective du GPU toutes les secondes.
La synthèse inclut les phases de vérification, validation et export : ces
phases ne doivent pas être présentées comme du calcul GPU à 100 %. Le premier
événement `cuda_optimizer_started` désigne le benchmark, et le premier
`cuda_training_started` confirme la première mise à jour du fit définitif.

## Intégration dans la maquette

Les fichiers sont exportés sous `demo/index.json` et `demo/cases/<id>.json`,
destinés à `/poc/iss/`. Chaque cas possède son empreinte SHA-256 dans l'index.
Le navigateur peut donc rejeter un ancien fichier mélangé à un nouvel index.

Chaque frame contient `heat_score`, `smoke_score`, `heat_valid_mask`,
`smoke_valid_mask`, `predicted_hot_mask` et `predicted_smoke_mask`. La vérité
de simulation reste distincte : `temperature_c`, `soot_kg_m3`,
`hotspot_truth` et `smoke_truth`. Les nombres exportés conservent les valeurs
exactes float32, et les absences restent `null`. Le transport peut être
compressé sans arrondir ces données.

Les positions sont exprimées en mètres, dans l'ordre XYZ du solveur, avec Z
vertical. Les boîtes, matériaux, évents et zone source sont les objets
effectivement compilés pour FDS. Le rendu 3D peut ajouter des éléments
décoratifs, mais doit superposer les prédictions dans ce même repère.

La maquette parcourt des prédictions enregistrées. Une entrée séparée permet
une vraie nouvelle inférence, sans FDS ni données de vérité :

```python
from pathlib import Path
from iss_poc_model import ISSPredictor

model = ISSPredictor(Path("weights.pt"), device="cpu", expected_sha256="empreinte vérifiée")
prediction = model.predict_scene(scene, config, times=[1, 5, 10, 20, 30])
# prediction['scores'] : [instants, sondes, 2], canaux chaleur puis fumée
# config.sample_shape doit rester [12, 16, 8].
```

La compilation ci-dessus prépare seulement la géométrie et les conditions ;
elle ne lance pas le solveur. `predict_arrays` accepte aussi un manifeste
déjà compilé et sa configuration effective. L'inférence est disponible sur
CPU et CUDA, avec vérification des poids et des dimensions.

## Preuves et mesures

Le fit produit `report.json`, `frozen-selection.json`, `weights.pt`,
`dataset-snapshot.json`, `sources.json`, les validations intermédiaires,
la télémétrie GPU et `inference-benchmark.json`. Ce dernier sépare le
chargement CPU, la première inférence CPU, les inférences CPU suivantes et
les inférences GPU avec réseau déjà chargé. Le temps de simulation FDS doit
être son temps de calcul mesuré, jamais ses 30 secondes de temps physique.

Les tests de contrat ne prouvent pas une précision prédictive ; ils vérifient
les masques, partitions, unités, seuils, gradients, exports et l'inférence sans
labels. Les 18 tests ciblés ont passé sur le Python PyTorch du Windows, y
compris l'inférence d'un vrai manifeste FDS avec une source désactivée.

## Résultats du fit terminé à 14 h 21, heure de Paris

Le fit `fit1-retry` a terminé avec le code 0 : **234,7 secondes dans la boucle
d'apprentissage, 295,2 secondes pour l'exécution complète**. Les 20 000 étapes
ont été parcourues ; la sélection préétablie a conservé l'étape 1 000, les
étapes suivantes n'améliorant pas l'objectif de validation. Le test a été
prédit après cette sélection définitive. Aucun second entraînement n'a été
lancé à partir de ces résultats.

| Partition, microgravité | Champ | Précision | Rappel | F1 modèle | F1 proximité |
| --- | --- | ---: | ---: | ---: | ---: |
| Validation | Chaleur | 87,0 % | 43,8 % | 58,3 % | 38,4 % |
| Validation | Fumée | 63,0 % | 65,6 % | 64,2 % | 40,5 % |
| Test | Chaleur | 63,6 % | 71,4 % | 67,3 % | 36,8 % |
| Test | Fumée | 58,5 % | 79,6 % | 67,4 % | 33,5 % |

Il s'agit des comptages agrégés des sondes observées après t=0. Le test
contient trois nouvelles dispositions, dans les trois familles connues ;
ce n'est pas une validation de généralisation à n'importe quelle station.
Le rapport conserve aussi les métriques Terre, par module et par incident.
Des erreurs persistent : un cas sans fumée observée déclenche une fausse
alerte fumée en validation ; un cas sans chaleur observée déclenche une
fausse alerte chaleur sur le test. Les autres cas et les erreurs restent
consultables dans les 108 replays.

Le benchmark a choisi le batch 64, à environ 6 154 exemples par seconde ;
128 donnait environ 6 134 et 256 environ 5 854. La télémétrie observée sur
l'exécution entière comporte 293 échantillons : **GPU au maximum à 99 %,
médiane à 96 %**, phases de lecture et d'export incluses. Ce sont des mesures
du périphérique, pas une promesse d'utilisation constante à 100 %.

Sur `iss-laboratory-v04-flame`, 31 instants × 1 536 sondes :

- Chargement du checkpoint CPU : 12,6 ms ; premier appel CPU : 104,6 ms.
- Inférence CPU suivante : médiane de trois mesures à 81,8 ms, quatre threads.
- Inférence GPU, réseau déjà chargé : médiane de trois mesures à 103,2 ms.
- Simulation FDS du même cas : temps de calcul enregistré de 8,984 secondes.

La comparaison donne environ 110 fois moins de temps pour l'inférence CPU
sur cet exemple. Les sorties du modèle sont des classes approchées ; FDS
résout la simulation physique complète. Le petit volume ne rend pas ici le
GPU plus rapide qu'un CPU déjà chargé. CPU et GPU ont produit les mêmes
masques binaires sur ce cas de mesure, malgré des différences numériques de
score atteignant 0,00123.

Poids : `6ab66833116e2b5b1a514a4cf2fa9095e370a38f93a946f9d497fabc4dbd3392`.
Snapshot de données :
`886535ae37231e4da51645cbb6590acab8c00a484c5151272e4e8e4657f09e69`.
Archive Windows :
`E:/IGNIS-Valley-dev/runtime/iss-poc/20261115/fit1-retry.zip`,
126 456 840 octets ; SHA-256
`82ac5163789d19938f6968661250ecb54080fff4cdf7a3247e9e546f65261aad`.
Elle conserve les poids, les 108 replays, les rapports, les sources vérifiées
par leurs empreintes, les logs et le lancement exact.

Le dossier `fit1` garde l'échec préalable de préparation : aucune étape
d'optimisation n'avait eu lieu. Le cas source 0 W produit légitimement une
rampe FDS vide ; l'encodeur ISS lui attribue maintenant une caractéristique
de rampe nulle sans modifier le manifeste ni les anciennes implémentations.
La correction a été testée et contre-relue avant la relance.
