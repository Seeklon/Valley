# Adaptation ventilation du modèle chaleur/fumée — 15 novembre 2026

État après exécution : entraînement terminé le 15 novembre à 16:10:47 Paris,
sortie 0. L'audit indépendant du coordinateur a validé les 216 replays et leurs
comparaisons contre FDS. Le candidat est éligible à la livraison, sous réserve
de la QA de l'interface pilotée par le coordinateur. Aucun déploiement n'a été
effectué par le trainer.

## Résultat de l'exécution figée

Les 216 nouvelles simulations et leur audit ont pris 829,125 s. Le fit complet,
vérifications, évaluations et exports compris, a pris **452,031 s** sur les
600 s autorisées. La fenêtre d'entraînement a duré 301,922 s, validations
intermédiaires incluses : l'ultime validation commencée dans le budget de
300 s a été terminée avant la sortie de la boucle. Il y a eu 13 000 mises à
jour ; le checkpoint **5 000** a été retenu. Les deux tâches représentent
21 min 21 s de calcul cumulé, hors attente entre les processus.

Premier pas d'optimisation effectif : 15:03:54,536 UTC. Gel des poids et seuils :
15:08:55,973 UTC. Le nouveau test a été ouvert ensuite. Le modèle retenu porte
les empreintes :

- Poids : `ce0ffc80e51d9be2da94fc50f098fc4ac3c223203d09c8908ea8bbd6f4eff292`.
- État du réseau : `edad77f5098e632fa48d2bc32f54b73597cb7a06e9278e5ca4f3e8fa2d28b3bb`.
- Snapshot du nouveau dataset : `2f78251a2265822541373d7ad5233924bb1e79a95f7bcf26868f93245bea9115`.
- Seuil chaleur : 0,9088770151138306 ; seuil fumée : 0,8320183753967285.

La sélection préannoncée est satisfaite : composite validation 0,322977 →
0,432505 ; réponse appariée macro-famille 0,115347 → 0,267451 ; aucun garde-fou
violé. Le tableau suivant concerne uniquement les **54 nouveaux cas de test**,
dont six contrôles 0 W, évalués après le gel. Le V2 est recalibré sur exactement
la même validation autorisée, jamais sur ce test.

| Champ / modèle | TP | FP | FN | Précision | Rappel | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Chaleur, V2 recalibré | 3 004 | 3 841 | 5 654 | 0,438860 | 0,346962 | 0,387538 |
| Chaleur, candidat | 5 203 | 4 971 | 3 455 | 0,511402 | 0,600947 | 0,552570 |
| Fumée, V2 recalibré | 7 555 | 9 898 | 13 473 | 0,432877 | 0,359283 | 0,392661 |
| Fumée, candidat | 12 497 | 9 662 | 8 531 | 0,563969 | 0,594303 | 0,578739 |

La chaleur gagne 2 199 vrais positifs et manque 2 199 points chauds de moins,
mais produit aussi **1 130 faux positifs supplémentaires**. Sa précision
s'améliore car les vrais positifs augmentent plus vite. Ce résultat ne signifie
donc pas moins d'alertes chaudes erronées en valeur absolue. La fumée améliore
simultanément vrais positifs, faux positifs et faux négatifs. Les six contrôles
0 W du test produisent zéro faux positif dans les deux champs.

Avec ses seuils déployés inchangés, le V2 obtient sur ce même nouveau test un
F1 chaleur de 0,354143 et fumée de 0,378378. La comparaison recalibrée du tableau
isole mieux l'effet du réentraînement de celui du choix des seuils.

| Réponse aux changements de ventilation, test | V2 recalibré | Candidat |
|---|---:|---:|
| F1 des changements signés, chaleur | 0,126167 | 0,374217 |
| F1 des changements signés, fumée | 0,126766 | 0,448336 |
| Erreur moyenne de déplacement du centroïde chaleur | 0,501366 m | 0,301890 m |
| Couverture du déplacement chaleur | 179/196 (91,33 %) | 188/196 (95,92 %) |
| Erreur moyenne de déplacement du centroïde fumée | 0,597693 m | 0,320772 m |
| Couverture du déplacement fumée | 202/206 (98,06 %) | 204/206 (99,03 %) |

Ces F1 appariés de test regroupent les décomptes des 36 contrastes ; ce ne sont
pas les F1 macro-famille utilisés dans la sélection. La couverture explicite
empêche d'interpréter une disparition de prédictions comme une meilleure
précision de déplacement. Les changements signés restent imparfaitement
prédits ; le gain n'établit pas un modèle fiable de sécurité spatiale réelle.

Sur l'ancienne validation V2, le candidat obtient F1 chaleur 0,599950 et fumée
0,601798, contre 0,465573/0,538305 pour le V2 recalibré avec les seuils issus de
la validation combinée. L'ancien test V2 n'a pas été réutilisé.

Télémétrie NVIDIA : entre le premier pas d'optimisation et le gel, 299 mesures,
médiane **98 %**, maximum **99 %**, moyenne **85,27 %**. Cette fenêtre inclut
les validations intermédiaires ; les logs ne permettent pas d'isoler exactement
chaque passe d'optimisation des opérations de validation. Sur les 423 mesures
de la télémétrie globale de l'exécution, médiane 98 %, maximum 99 % et 60,28 %
des mesures à au moins 90 %. La télémétrie commence à l'initialisation CUDA,
après les premières vérifications CPU ; elle n'est pas une trace des 452 s
depuis le démarrage du processus. L'utilisation concerne le périphérique,
pas une mesure du pourcentage de FLOPS crête atteint.

Benchmark réel sur une trajectoire de validation de 20 frames × 1 536 sondes :
CPU quatre threads, médiane 55,7 ms ; GPU déjà chargé, médiane 33,4 ms. Le
chargement CPU prend 12,2 ms. Écart maximal de score CPU/GPU 0,003919 et zéro
désaccord de classe sur **cette trajectoire**. Cela ne prouve pas une égalité
numérique de toutes les prédictions CPU et GPU.

Artefacts Windows :
`E:/IGNIS-Valley-dev/runtime/iss-poc-vent/20261115/fit1`.
Le `report.json`, les scores NPZ, les poids et les replays permettent de
recalculer les comparaisons ; la preuve indépendante de livraison est conservée
séparément par le coordinateur dans
`evidence/incidents/iss-poc-vent/export-verification.json`.

## Diagnostic utilisé pour décider

Seule la validation V2 a été utilisée : 48 cas, dont 42 en microgravité.
Sources : `evidence/incidents/iss-poc-v2/model/fit1/report.json`, partition
`metrics.validation`, `evidence/incidents/iss-poc-v2/dataset/plan.json`, et les
replays `web/public/poc/iss/cases/*-v2-05-*.json`. Le test V2 n'a pas été lu pour
ce diagnostic ni pour sélectionner cette adaptation.

Les décomptes ci-dessous sont les décomptes des sondes observées après t=0,
agrégés sur les cas microgravité. Ils ne sont pas des taux par événement réel.

| Vitesse | Chaleur TP / FP / FN | Précision chaleur | Rappel chaleur | Fumée TP / FP / FN | Précision fumée | Rappel fumée |
|---|---:|---:|---:|---:|---:|---:|
| 0,08 m/s | 638 / 744 / 224 | 0,462 | 0,740 | 1 372 / 1 554 / 401 | 0,469 | 0,774 |
| 0,18 m/s | 587 / 641 / 710 | 0,478 | 0,453 | 1 413 / 1 278 / 1 202 | 0,525 | 0,540 |
| 0,28 m/s | 517 / 510 / 742 | 0,503 | 0,411 | 1 443 / 1 186 / 1 282 | 0,549 | 0,530 |

Les vitesses, puissances, sources et géométries varient ensemble dans V2 : ces
écarts motivent une expérience appariée, sans isoler causalement la ventilation.

| Famille | Rappel chaleur | Rappel fumée | F1 chaleur | F1 fumée |
|---|---:|---:|---:|---:|
| ISS laboratory | 0,509 | 0,591 | 0,489 | 0,555 |
| ISS node | 0,735 | 0,777 | 0,596 | 0,589 |
| ISS service | 0,384 | 0,511 | 0,441 | 0,546 |
| Habitat cargo | 0,530 | 0,624 | 0,487 | 0,553 |
| Habitat capsule | 0,574 | 0,609 | 0,541 | 0,564 |
| Habitat central racks | 0,384 | 0,506 | 0,390 | 0,486 |

Les arcs sont particulièrement faibles : rappel chaleur 0,103, F1 0,099 ; rappel
fumée 0,256, F1 0,185. La source `electrical-02` a un rappel chaleur/fumée de
0,328/0,501, contre 0,656/0,707 pour `electrical-00`. Ces identifiants désignent
des emplacements propres à chaque géométrie, pas un effet universel d'un type de
composant. Les six contrôles 0 W ont zéro faux positif.

La direction a été déduite du plan physique de l'entrée et du signe du flux,
pas de la seule annotation `normal`. Rappel chaleur/fumée : X+ 0,530/0,624,
X− 0,552/0,635, Y+ 0,547/0,601, Y− 0,384/0,511. Y− correspond uniquement à
ISS service dans cette validation. Deux familles en X− ont des rappels chaleur
très différents (node 0,735 ; central racks 0,384). Aucun diagnostic causal
d'axe ou de sens n'est donc établi sur V2 seul.

## Modification bornée

Le même U-Net 3D à 54 canaux est réutilisé, sans changement d'encodeur ou
d'architecture : 379 046 paramètres, dont 376 834 entraînables. Le départ est le
checkpoint V2 de SHA-256
`37bf3e0c5394cbe52fe520ebf85cbf393cd9b4203751d5b1db5c0c79641f987a`.

- 240 anciens cas d'entraînement V2 et 108 nouveaux cas appariés de ventilation.
- 50 % de masse d'échantillonnage par corpus ; cas équiprobables dans chaque
  corpus ; mélange précédent des temps uniformes et des temps actifs conservé.
- Quatre transformations équiprobables par batch : identité, reflet X, reflet Y,
  reflet XY. Aucun reflet Z, permutation d'axes ou interpolation des labels.
- BCE équilibrée chaleur/fumée et positif/fond conservée. Les temps froids et
  contrôles 0 W restent présents. Pas de pondération supplémentaire des positifs
  ni de renforcement artificiel à partir des erreurs du test.
- AdamW, taux initial 1e−4, cosine vers 2e−5, batch 128, clipping 5.
- Optimisation limitée à 300 s dans une exécution de 600 s au maximum ; réserve
  de 200 s pour vérification et export ; validation tous les 1 000 pas.

Chaque réflexion transforme spatialement tous les canaux, les deux cibles et
leurs masques individuels. Puis elle transforme `x_over_width` ou
`y_over_depth` et `source_x_scaled` ou `source_y_scaled` par 1−coordonnée,
inverse `source_dx` ou `source_dy` et le signe de `boundary_u_scaled` ou
`boundary_v_scaled`. Matériaux, fractions de volume/surface, temps, dimensions
et scalaires gardent leurs valeurs attachées à la géométrie déplacée.

Les sondes FDS sont ajustées aux cellules. Leurs positions ne sont pas toujours
centrées symétriquement ; le reflet conserve leurs positions physiquement
transformées. Il ne recrée pas une grille régulière. Les tests reconstruisent
les géométries réfléchies avec le compilateur et réattachent explicitement les
sondes réfléchies avant de comparer les 54 canaux. Quatre vues d'une simulation
ne comptent pas comme quatre nouvelles simulations FDS indépendantes.

L'encodeur conserve ses limitations : historique de source incomplet, notamment
absence de canal dédié au délai et à l'énergie cumulée. L'augmentation n'ajoute
aucune information physique manquante.

## Sélection préannoncée

La validation comporte les 48 cas V2 et les 54 nouveaux cas. Le nouveau test de
54 cas n'est lu qu'après gel des poids et des seuils ; le test V2 n'est jamais
chargé. Les manifestes d'entrée sont autorisés pour exclure les géométries
identiques, normalisées ou réfléchies entre partitions.

Les seuils chaleur/fumée sont choisis avec la même maximisation du F1 moyen par
famille en microgravité sur les 102 validations. Le V2 est recalibré exactement
avec cette règle et constitue le candidat au pas 0. Les métriques du V2 avec
ses seuils déjà déployés sont également conservées.

Le score d'un checkpoint est composé de 75 % du F1 macro-famille combiné et de
25 % du F1 macro-famille des changements **signés** de régions affectées dans
les nouveaux quartets. Chaque champ a une masse égale. Les comparaisons sont
sans flux → lent, sans flux → rapide, rapide → inversé. L'évaluateur indépendant
aligne les observations aux horizons 5, 10, 15, 20, 25 et 30 s : interpolation
linéaire des mesures physiques avant seuillage et des scores, sans
extrapolation, avec masque aux extrémités et refus des intervalles >2,5 s.

Un checkpoint peut remplacer le V2 seulement si, sur validation :

1. Le composite et le F1 de réponse à la ventilation dépassent tous deux le V2 recalibré.
2. Le F1 moyen sur l'ancienne validation baisse d'au plus 0,02.
3. Chaque rappel chaleur/fumée agrégé en microgravité est au moins celui du V2 recalibré.
4. Chaque précision correspondante baisse d'au plus 0,03.
5. Les douze contrôles explicites 0 W ont zéro faux positif.

La précision, le rappel, les TP/FP/FN et la couverture des déplacements de
centroïdes restent publiés. Une prédiction vide ne peut améliorer silencieusement
l'erreur de déplacement. Un gain sur le nouveau test ne peut rattraper une
sélection refusée sur validation. Sans candidat admissible, les poids V2 restent
le résultat sélectionné et le déploiement V2 stable est conservé.

## Preuve des tests avant entraînement

Exécuté sur Windows, Python `E:/IGNIS-Valley/.venv/Scripts/python.exe`, checkout
`E:/IGNIS-Valley-dev/app`, `PYTHONPATH=E:/IGNIS-Valley-dev/app/backend`,
`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`. Le fixture pytest force aussi
`torch.set_num_threads(1)`. Aucun entraînement ni calcul CUDA dans ces tests.

Commande :

```text
python -m pytest tests/test_iss_poc_vent.py -q -x
......................                                                   [100%]
22 passed in 2.73s
pytest_exit=0
```

Sortie constatée pendant la session, puis empreintes des fichiers réellement
présents sur Windows contrôlées par `Get-FileHash` à 15:00:32 UTC pour le
trainer final et à 14:52:13 UTC pour les tests et l'évaluateur inchangés :

| Fichier testé | SHA-256 |
|---|---|
| tools/remote/train_iss_poc_vent.py | `ebdcf76451b9a0371dc92a9bef9beca57afe38e251a311a7dbf9f7cec38b6731` |
| tests/test_iss_poc_vent.py | `03a70e3d9913dc0b2e157629adaecaa039fd400d15569f88bdc22d68136aa55b` |
| tools/remote/evaluate_iss_ventilation.py | `a8b55f57e1b76c3c27285b8d149410ab9cd0c9fda2eac1e0fe00e41b89890b10` |

Les six parités de réflexion (deux axes de ventilation × X/Y/XY), le sampler
50/50, les contrôles 0 W, les six refus de promotion, le refus de sélection sur
test, l'exclusion des copies réfléchies, la complétude des quartets et la
non-mutation du snapshot figé après vérification du test sont couverts.
`ruff check` et compilation Python passent également localement.

La version précédente avait déjà passé les 22 tests en 2,59 s ; le second
passage ci-dessus vérifie la version finale après ajout du benchmark d'inférence
CPU/GPU sur les poids sélectionnés. Ce benchmark sera exécuté après le gel du
checkpoint et écrit dans `inference-benchmark.json`, dans le même budget de
600 s. Il n'a pas encore été exécuté au moment de cette preuve des tests CPU.

Les premières tentatives de tests ont révélé une dépendance non copiée puis
des fixtures dont l'évent croisait un rack et dont la source était sur une
limite de cellule. La dépendance a été copiée, les fixtures ont été corrigés et
les 22 tests ci-dessus ont alors passé. Aucun de ces tests n'a modifié le
dataset FDS ou l'encodeur déployé.

## Contrat des artefacts

L'export contient seulement les 216 nouveaux cas ; aucune duplication des
384 replays V2. `weights.pt`, `dataset-snapshot.json` et les métadonnées d'export
portent le même hash de snapshot préselection. La copie de snapshot enrichie
par la vérification du test est écrite séparément. Le checkpoint porte aussi
le hash du corpus V2, et sa copie complète est archivée à côté.

Les scores bruts sont archivés sous `comparison-scores/` :
`v2-validation.npz`, `candidate-validation.npz`, `v2-test.npz`,
`candidate-test.npz`. Chaque fichier contient les 54 identifiants du split
concerné, contrôles inclus. `frozen-selection.json` précède tout accès aux
observations du nouveau test. `sources.json` épingle aussi l'évaluateur apparié
et les fonctions de choix des seuils/comptage héritées.

Le modèle reste un substitut de simulations synthétiques à source électrique
imposée. Les scores ne représentent ni une température, ni une concentration
de fumée, ni la probabilité d'un départ de feu réel. Cette adaptation ne prouve
pas une validation expérimentale NASA ou la fiabilité sur une station réelle.
