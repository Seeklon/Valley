# Campagne appariée : ventilation en microgravité

Cette campagne isole l'effet du débit et du sens de ventilation sur chaleur et
suie simulées. Elle complète les données v2 sans les modifier. Elle ne mesure
pas une probabilité de départ de feu et ne constitue pas une validation NASA.

## Plan figé avant observation

`iss-poc-20261115-vent` contient 216 simulations FDS de 30 secondes sur 24
dispositions originales : six familles, quatre dispositions chacune. Douze
dispositions servent au train (108 cas), six à la validation (54), six au test
final inédit (54). Géométries physiques et normalisées restent disjointes des
v1/v2 et entre partitions. Les familles, elles, sont communes aux partitions.
Les quatre états de ventilation sont aussi communs aux partitions : le test
mesure leur effet sur des dispositions nouvelles, pas sur des vitesses inédites.

Chaque disposition comporte deux quartets avec source électrique imposée :
un incident flaming et un autre type tournant parmi battery, smoldering,
overheating et arc. Les sources longues durent 24 ou 26 secondes ; les arcs
durent 8 secondes. Les deux supports actifs ont une couche combustible réelle.
Un contrôle puissance nulle complète chaque disposition.

Dans chaque quartet, géométrie, matériaux, composant, puissance, durée, gravité,
oxygène, température, pression et seed FDS restent strictement identiques :

| État | Vitesse imposée | Modification physique |
| --- | ---: | --- |
| `still` | 0 m/s | Débit nul aux deux mêmes ouvertures |
| `slow` | 0,12 m/s | Entrée basse coordonnée, sortie opposée |
| `fast` | 0,36 m/s | Même circulation, débit triplé |
| `reverse` | 0,36 m/s | Rôles entrée/sortie échangés, ouvertures inchangées |

Les ouvertures opposées ont la même aire. La permutation conserve le débit
absolu ; elle ne se réduit pas à changer une étiquette ou une normale dessinée.
L'axe X ou Y varie entre dispositions. La gravité vaut 0,0001 g selon Z.

## Contrat pour l'entraînement et l'évaluation

Chaque record fournit `layout_id`, `ventilation_group_id`, `ventilation_state`,
`ventilation_axis` et `reverse_ventilation`. Les contrôles ont un groupe nul et
un état `control`. Chaque groupe actif a exactement quatre membres. Les champs
NPZ, masques et manifests suivent l'interface v2 ; `scene.json` contient la
scène effective, y compris les rôles inversés. Son SHA et le fingerprint se
rapportent aux entrées effectives du solveur.

Les comparaisons préannoncées sont still/slow, still/fast et fast/reverse.
Rapporter rappel, précision et faux négatifs par état et incident, puis
différence spatiale FDS et différence prédite entre membres. Pour le transport,
les déplacements du barycentre de suie et le recouvrement spatial permettent
de distinguer sensibilité au débit et simple répétition de la même prédiction.
Les temps FDS réels peuvent différer : aucune comparaison par indice seul.
Documenter la correspondance temporelle et les masques communs employés.
L'absence d'effet observé est un résultat possible ; aucune différence ne doit
être fabriquée pour démontrer une sensibilité.

Les étiquettes test ne servent ni à choisir le design, ni aux seuils, ni aux
poids. L'audit d'intégrité test vérifie fichiers, timestamps et provenance sans
produire de synthèse de labels. La sélection utilise seulement train/validation.

## Signes physiques et encodeur

FDS reçoit un `VOLUME_FLOW` négatif pour l'entrée, positif pour la sortie. Le
compilateur calcule débit = vitesse × aire d'entrée. L'encodeur projette les
vitesses prescrites dans `boundary_u_scaled`, `boundary_v_scaled` et
`boundary_w_scaled` à partir de la normale **sortante de la paroi** × débit/aire,
et conserve les fractions d'aire d'entrée/sortie. La normale annotée dans la
scène ne décide pas du sens du flux FDS. `airflow_scaled` porte aussi la vitesse
scalaire. L'écoulement intérieur est résolu par FDS, pas fourni comme une mesure
au réseau. Le contrôle numérique doit vérifier zéro, ×3 et changement de signe
des canaux de vitesse ; changer le sens permute aussi les canaux d'ouverture.

## Symétries admissibles

Les réflexions X, Y ou XY sont physiquement admissibles pour ces conditions
isotropes et gravité selon Z : conserver la face +Z des sources/coatings et
transformer objets, positions sources, ouvertures et champs. Les canaux de
coordonnées absolues deviennent `1-x` ou `1-y`, les deltas source et composantes
de vitesse correspondants changent de signe ; les dimensions et masques
suivent la même transformation. Un simple flip de tous les canaux est faux.
Les permutations X/Y imposent aussi de permuter dimensions, axes, canaux vectoriels
et grille ; la grille 12×16×8 impose des précautions supplémentaires. Une
réflexion Z serait invalide ici sans transformer gravité et faces combustibles.
Les géométries symétriques doivent rester dans leur partition d'origine.

Les positions de sondes sont arrondies aux centres de cellules FDS. Elles ne
sont donc pas toujours centrosymétriques : une réflexion des champs donne des
observations sur la **grille de sondes réfléchie**, qui peut différer de celle
recréée par le compilateur standard. Transformer explicitement les coordonnées
et ne pas présenter ces augmentations comme de nouveaux calculs FDS. Une
comparaison à une scène recompilée exige un alignement spatial explicite.

## Ressources et lancement

Quatre processus FDS, un thread chacun, grille 12×16×8 observée et environ
14–17 k cellules résolues. D'après les 384 calculs v2 (1 433 s actifs), 216 cas
représentent environ 13 min 30 ; réserve jusqu'à 20 min génération + audit.
Le lanceur garde le verrou OS `compute.lock`, l'ancien corpus en pause, une
réserve disque de 20 Gio et les artefacts existants intacts.

```text
python tools/remote/generate_iss_poc_vent.py --home E:/IGNIS-Valley-dev --workers 4 --budget-s 1140
```

La génération emploie le CPU FDS. Le GPU reste réservé au réseau ML. Un budget
est une limite de calcul, pas une promesse de qualité scientifique.

## Premières vérifications réelles

L'encodeur a été exécuté sur le PC Windows avec PyTorch, sur CPU : les axes X/Y,
les vitesses nulles, le facteur trois, l'inversion du signe et la permutation
des canaux d'ouverture sont vérifiés dans `prelaunch-encoder.json`.

Les douze cas pilotes prédéclarés train/validation confirment les débits FDS
observés, avec les mêmes signes et valeurs que les débits prescrits à l'arrondi
près. Dans le quartet laboratoire X, la vitesse moyenne des sondes gazeuses
sur 20–30 s vaut environ 0,0001 / 0,0199 / 0,0607 / −0,0612 m/s dans l'ordre
still / slow / fast / reverse. Il s'agit d'une moyenne aux sondes, pas d'une
moyenne volumique complète. Voir `pilot-flow-observations.json`.

Le préflight de l'évaluateur apparié accepte les 21/31/31/31 observations du
quartet laboratoire, à des instants réellement non entiers. Les six horizons
5–30 s sont couverts sans gap rejeté ; le plus grand intervalle vaut 1,5153 s.
Les trois contrastes comportent 64 changements de classe chaleur et 81 de suie.
`paired-preflight.json` emploie des scores artificiels dérivés des labels train
pour vérifier le branchement : **ce n'est pas une mesure de performance ML**.

## Résultat de la génération du 15 novembre 2026

Les 216 cas sont complets et l'audit est passé le 15 novembre à 16:02:20 Paris.
Le verrou de calcul était disponible et aucun FDS actif à 16:02:40 ; le relais
au processus ML a alors été transmis. Durées mesurées : 820,984 s de génération
(13 min 41), 829,125 s génération + audit (13 min 49). Depuis le premier essai
de lancement : 1 044,561 s (17 min 24), dont 123,827 s d'attente d'un autre
travail qui détenait le verrou. Aucun processus externe n'a été interrompu.
Le premier lancement SSH s'était arrêté pendant le préflight sans produire de
cas ; le lancement effectif a utilisé un processus Windows détaché.

Les 1 512 fichiers archivés sont vérifiés par SHA-256, pour 779 737 245 octets.
Les manifestes, plans et index des corpus v1/v2 ont conservé leurs empreintes.

| Partition | Cas | Observations valides | Positifs chaleur | Positifs suie |
| --- | ---: | ---: | ---: | ---: |
| Train | 108 | 4 382 364 | 23 141 | 51 470 |
| Validation | 54 | 2 197 852 | 13 338 | 26 391 |
| Test final | 54 | Non synthétisé avant sélection | — | — |

Les 18 contrôles à puissance nulle train/validation n'ont aucun label positif.
Les seuils sont appliqués en float64 : chaleur ≥ ambiance + 5 °C, suie
≥ 10⁻⁶ kg/m³ ; les instants t=0 et valeurs non observées sont exclus.

Preuves locales : `evidence/incidents/iss-poc-vent/dataset/verification.json`,
`compute-ledger.json`, `ready-for-training.json`, plus les plans/index gelés.

```text
manifest 04bf8aafb870938c26c93fa475b3ee96394ab4159d79ed3624a4a07852567598
plan     d97230537a88d1e24481465afb31451038fd8340f4f6fea1c90016ddaf86c2c3
index    ccdfff19ebe738a6f50123905038253e0fb064f3fdb24afe6db6482d8d563540
```
