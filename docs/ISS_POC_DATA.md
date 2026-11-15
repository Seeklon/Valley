# Données ciblées ISS pour la démonstration du 15 novembre

Demande de Thomas confirmée le 15 novembre : spécialiser le POC sur des zones de
station à géométrie simple, comparables au parcours de la maquette. Le jeu décrit
ci-dessous est original et synthétique. Il ne reproduit ni les plans ni les
équipements réels de l'ISS et n'est pas constitué de mesures NASA.

Le plan immuable `iss-poc-20261115-v1` contient **108 calculs prévus**, répartis
sur **18 dispositions physiques** : laboratoire à racks, nœud de circulation et
zone technique. Chaque famille possède six variantes. Les coordonnées des racks
changent d'une à deux cellules le long de la pièce, leur largeur varie d'une
cellule et les baffles changent de hauteur. L'échelle physique varie également.
Ce sont bien des dispositions différentes après normalisation spatiale.

Les variantes 0 à 3 sont réservées à l'entraînement (72 cas), la variante 4 à la
validation (18 cas), la variante 5 au test (18 cas). Tous les incidents d'une
même disposition restent dans la même partition. Les trois familles sont
volontairement communes aux partitions : le résultat mesurera une spécialisation
sur ces types de pièces, pas une généralisation à un véhicule inconnu. Les
empreintes des géométries compilées doivent être toutes différentes.

Chaque pièce fournit trois composants électriques annotés. Six scénarios sont
prévus par disposition : feu déclaré, émission thermique/suie de batterie
équivalente, émission couvante équivalente, surchauffe ou arc thermique, contrôle
sans puissance et comparaison terrestre du même feu déclaré. Le plan comprend
90 microgravités (`0,0001 g`), 18 Terres et **18 témoins à 0 W**. Les cinq types
d'incidents électriques du compilateur sont représentés. Leur physique reste
celle d'équivalents imposés : aucune probabilité d'allumage, cinétique de batterie
ou simulation d'arc électrique n'est ajoutée.

Les trois pièces utilisent des ouvertures opposées avec vitesse d'entrée
prescrite (0,08, 0,16 ou 0,24 m/s), des obstacles et des revêtements combustibles
PMMA/cellulose. Les matériaux et coefficients d'émission restent les hypothèses
déjà documentées du compilateur. Chaque calcul dure 30 secondes physiques, avec
une sortie demandée chaque seconde et une grille d'observation **12 × 16 × 8**. Le maillage
FDS compte 13 824 à 17 280 cellules. La source est volontairement résolue près
d'une colonne de sondes pour observer un incident local ; aucune cible n'est
ajoutée artificiellement entre les observations.

Le lancement commence par six cas d'entraînement prédéclarés, couvrant les trois
pièces, un témoin à 0 W, un arc, des flammes et des émissions de suie. Le pilote
est limité à dix minutes, quatre processus FDS à un thread chacun. Son coût et
la densité de points positifs déterminent si les 108 cas seront calculés dans le
budget de la présentation. Le seuil de diagnostic est fixé avant le calcul :
chaleur `T >= température ambiante + 5 °C`, fumée `suie >= 1e-6 kg/m³`, uniquement
sur les observations gazeuses et les temps strictement positifs. Le résumé de
prévalence est produit pour train/validation ; les cibles de test restent
réservées à l'évaluation finale.

Le générateur réutilise `compile_case`, `FDSRunner`, `compress_completed_run`,
les empreintes et les verrous de calcul existants. Les données précédentes sont
conservées et le corpus ancien doit rester en pause. Arrêt/limite de temps
annulent les seuls processus FDS de cette invocation ; les artefacts incomplets
sont conservés puis archivés lors d'une reprise. Un index d'entraînement figé
n'est écrit que lorsque tous les cas attendus ont été achevés et vérifiés.

Artefacts :

- Entrées physiques lisibles : `scenes/iss-poc/`.
- Plan et résultats Windows : `E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v1`.
- Chaque cas : scène, configuration, manifeste de compilation, deck FDS,
  `fields.npz`, résultat JSON compressé, archive brute FDS et empreintes.
- Scripts : `tools/remote/iss_poc_design.py` et `generate_iss_poc.py`.
- Preuves légères : `evidence/incidents/iss-poc/dataset/`.

Validation locale réalisée avant pilote : six tests (déterminisme, partitions,
contrôles sans source et paires Terre/microgravité, compilation des 18 géométries
et 54 sources, budget expiré sans lancement de solveur et seuil fumée float64), Ruff sans erreur.

## Pilote réellement obtenu à 14:02 Paris

Les six simulations prédéclarées ont terminé en **29,83 secondes écoulées**,
compilation, lecture et archivage compris, sans échec. Chaque cas a demandé
11,2 à 13,4 secondes de solveur/lecture ; les quatre premières simulations ont
été exécutées simultanément. Les fichiers complets, decks, sorties FDS et
empreintes sont conservés sur Windows. Le rapport brut et le plan sont copiés
dans `evidence/incidents/iss-poc/dataset/pilot-*.json`.

| Cas pilote | Points-temps chauds | Points-temps enfumés | Maximum T |
|---|---:|---:|---:|
| Laboratoire, flamme | 92 | 178 | 218,84 °C |
| Laboratoire, batterie équivalente | 48 | 195 | 291,04 °C |
| Nœud, flamme | 68 | 121 | 62,09 °C |
| Nœud, arc thermique | 0 | 0 | 20,01 °C |
| Technique, couvant équivalent | 0 | 48 | 20,06 °C |
| Technique, contrôle 0 W | 0 | 0 | 20,00 °C |

Les occurrences positives restent rares : 208 points-temps chauds et 542
points-temps enfumés sur 243 016 observations valides après t=0. Ce pilote prouve
que les labels existent et que la génération est rapide ; il ne mesure aucune
performance ML. L'arc sans inflammation et le témoin froid sont conservés comme
résultats, sans transformer artificiellement leur cible. Le volume complet n'est
pas déclaré produit avant la fin et la vérification de la campagne.

## Campagne complète vérifiée à 14:12 Paris

Les **108/108 cas** sont achevés, sans échec. La reprise a duré 408,047 secondes,
soit **437,875 secondes de génération cumulée avec le pilote (7 min 18 s)**.
Ce temps est du CPU FDS/lecture/archivage ; il ne contient aucun entraînement GPU.
Les sept fichiers de chacun des 108 cas ont été revérifiés par empreinte et les
contrats de provenance, coordonnées, masques et temps ont été contrôlés. Le
répertoire contient 365 152 899 octets de cas archivés. Le générateur et ses FDS
étaient tous arrêtés avant de passer le relais à l'entraînement.

| Partition | Cas | Cas avec chaleur | Cas avec fumée | Points-temps chauds | Points-temps enfumés | Observations valides |
|---|---:|---:|---:|---:|---:|---:|
| Entraînement | 72 | 39 | 53 | 3 524 | 55 342 | 2 880 710 |
| Validation | 18 | 9 | 13 | 1 348 | 13 960 | 700 560 |
| Test réservé | 18 | — | — | — | — | — |

Les 15 contrôles à puissance nulle d'entraînement/validation ne contiennent
aucune occurrence chaude ou enfumée aux seuils fixés. Les trois témoins de test
et les autres sorties de test ne sont pas résumés ni employés pour adapter le
plan de génération. Les classes restent déséquilibrées : environ 0,12 % de
positifs thermiques et 1,92 % de positifs fumée en entraînement.

Les timestamps réels FDS font autorité. La cadence demandée de 1 seconde ne
contraint pas chaque pas du solveur : le premier laboratoire flamme fournit
27 frames entre 0 et 30 s, principalement espacées de 1,1964 s. Les impulsions
d'arc d'une seconde sont donc peu résolues temporellement dans ce benchmark.
L'absence de chaleur observée dans un tel cas n'établit pas l'absence de risque
physique. La démonstration doit privilégier les foyers et émissions soutenus.
Aucune frame n'a été interpolée pour remplir artificiellement la chronologie.

Empreintes finales :

- Manifeste : `b119a200985e936ec3d0ff36d878850165bb345c42df5d6be97da653954592fb`.
- Plan : `12d0b5b88d206627c38217d5f6cf985b989bc3c7b111d91ce793b1ca04c94139`.
- Index figé : `f4648d1466804a180065e35375edb79027115877ea46371fbea682823b96a670`.

Le rapport `verification.json`, le registre `compute-ledger.json`, le plan,
les index et les journaux réels sont copiés sous
`evidence/incidents/iss-poc/dataset/`. Aucun autre calcul FDS n'est lancé après
cette campagne.
