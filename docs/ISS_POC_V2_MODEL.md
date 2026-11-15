# Réentraînement du POC chaleur/fumée — 15 novembre 2026

Cette version réentraîne **le même U-Net 3D** que le POC ISS v1. Elle conserve les
379 046 paramètres (376 834 entraînables, 2 212 gelés dans la tête globale
inutilisée), la largeur 16, les entrées géométrie/matériaux/source/conditions/temps,
les deux sorties chaleur et fumée, ainsi que `ISSPredictor` dans
`tools/remote/iss_poc_model.py`. Aucun champ FDS observé n'entre dans le réseau.

Le checkpoint garde le même identifiant d'architecture et le même `MODEL_ID`.
`training_version`, l'empreinte des poids et celle du dataset distinguent les
réentraînements. Les artefacts v1 restent intacts.

## Données et portée

Dataset prévu : `iss-poc-20261115-v2`, 384 scénarios, 48 dispositions réparties en
six familles : laboratoire, nœud et module de service inspirés de l'ISS ; soute,
capsule rectangulaire et compartiment à racks centraux simplifiés. Chaque
disposition comporte huit conditions, dont un contrôle à puissance nulle et un
cas terrestre apparié. Le générateur possède son propre plan et son propre audit.

- Entraînement : 240 cas, 30 dispositions.
- Validation : 48 cas, 6 dispositions.
- Test : 96 cas, 12 dispositions.
- Grille de sondes : 12 × 16 × 8 ; chronologie réellement produite par FDS.

Le chargeur refuse un dataset incomplet ou un mélange de partitions. Les contrôles
hérités vérifient les empreintes, reconstruisent les entrées du compilateur FDS,
et vérifient l'ordre des sondes, les masques, les temps et les géométries.
Un contrôle supplémentaire compare **toutes** les nouvelles géométries aux
géométries de toutes les partitions v1, dont le test déjà examiné. La comparaison
des volumes normalisés empêche qu'un simple changement d'échelle, de matériaux ou
de noms masque une réutilisation. Les géométries normalisées sont aussi disjointes
entre les trois nouvelles partitions.

Les six familles figurent dans chaque partition. Le test porte donc sur des
dispositions inédites de familles connues. Certaines valeurs physiques ont déjà
été vues par v1 : la disjonction des nouvelles grilles de conditions n'en fait pas
un test de toutes nouvelles conditions physiques. Ce protocole ne démontre pas
une généralisation à une station réelle ou à des familles entièrement inconnues.

L'encodeur v1 conservé voit la fraction instantanée de la rampe source, mais ne
possède pas de canal explicite pour le retard d'allumage ni l'intégrale passée de
la puissance. Ses canaux temporels utilisent le temps courant et la durée de
source. Des historiques distincts peuvent donc devenir indiscernables après leur
phase transitoire. Les cas retardés du corpus ne démontrent pas une prédiction
correcte pour des historiques arbitraires ; lever cette limite exigerait une
évolution contrôlée de l'encodage, hors de ce réentraînement à architecture et
entrées inchangées.

## Protocole fixé avant le test

Point de départ : poids v1 gelés, SHA-256
`6ab66833116e2b5b1a514a4cf2fa9095e370a38f93a946f9d497fabc4dbd3392`.
Le trainer vérifie cette empreinte et le lien entre le checkpoint et son snapshot.

Les cibles restent : température FDS ≥ ambiance + 5 °C ; suie FDS ≥ 10⁻⁶ kg/m³.
Les comparaisons physiques conservent la précision réelle des observations.
Les temps initiaux et les observations manquantes n'entrent pas dans les métriques.
Les scores sont des scores de classes non calibrés, pas des températures,
concentrations ou probabilités de départ de feu.

Deux références sont évaluées sur exactement les mêmes nouvelles scènes :

1. Les poids et les seuils v1 gelés.
2. Les poids v1 gelés, avec seulement les seuils recalibrés sur la nouvelle
   validation. Cette référence isole le gain d'apprentissage du simple changement
   de seuil.

La seconde référence est candidate à l'étape 0. Après chaque tranche de 1 000
mises à jour, chaque seuil est choisi sur la validation pour maximiser le F1 moyen
par famille en microgravité. Les égalités favorisent moins de faux positifs puis
un seuil plus haut. La moyenne chaleur/fumée sélectionne le checkpoint. Les poids
réentraînés ne remplacent l'étape 0 que si cet objectif s'améliore strictement.
Tous les seuils et poids sont gelés avant la première prédiction du nouveau test.
Les résultats sont rapportés par famille, type d'incident et gravité, avec les
faux positifs des cas sans observation positive.

Si l'étape 0 gagne, le rapport l'indique : un ajustement des seuils ne sera pas
présenté comme une amélioration des poids. Le test sert à mesurer la qualité du
choix déjà gelé ; aucun réglage n'est effectué à partir du test.

## Compute et reproductibilité

Le budget total est de 600 secondes maximum, vérification, entraînement,
évaluation et export compris. L'entraînement utilise au plus 300 secondes et
20 000 mises à jour, avec 240 secondes réservées à la finalisation. La boucle
s'arrête également si le fichier `STOP` apparaît dans son propre dossier.

Optimiseur AdamW, taux initial 0,0003, décroissance cosinus vers 0,00005,
weight decay 0,0001. La BCE et l'échantillonnage sont ceux de v1 : poids identique
pour chaque cas, mélange de temps uniformes et actifs, poids équilibré entre les
deux champs et entre échantillons positifs et négatifs. Ce réentraînement supervisé
ne constitue pas du reinforcement learning.

Un cache CUDA factorisé stocke chaque géométrie une seule fois. Les conditions
temporelles sont diffusées uniquement dans le lot courant. Les tests CPU comparent
exactement les tenseurs reconstruits à l'encodeur v1 sur une source retardée,
un arc et un véritable contrôle 0 W. Les labels ne servent jamais à construire
les entrées. Un benchmark sur les données d'entraînement choisit le lot offrant
le meilleur débit utile parmi 32, 64, 128 et 256, puis restaure les poids.

Le verrou partagé `runtime/compute.lock` couvre toute l'exécution avant toute
allocation CUDA. Le lancement attend la fin de la génération FDS. La télémétrie
`nvidia-smi` mesure l'utilisation réelle, sans charge artificielle. La limite de
mémoire protège le poste Windows ; mémoire allouée et utilisation GPU sont deux
mesures différentes.

Chaque exécution écrit les sources exactes, le snapshot, les sélections de
validation, les comparaisons v1, le checkpoint, la télémétrie et un benchmark
d'inférence. L'export conserve le schéma `iss-poc-1` et des scores non arrondis.
Les 384 scènes sont accessibles ; les scènes proposées par défaut sont choisies
uniquement sur la validation, selon la même règle médiane que v1.

Les scores v1 de validation/test sont également archivés sur le poste dans
`comparison-scores/` afin de permettre une vérification indépendante des deux
comparaisons. Ils ne sont pas nécessaires au viewer. Le dataset FDS et ses NPZ de
labels restent distincts de l'archive de livraison du modèle et des replays.

## État

Trainer : `tools/remote/train_iss_poc_v2.py`. Tests : `tests/test_iss_poc_v2.py`.
Les 12 tests de contrat ont réellement passé sur le Python PyTorch Windows en
2,53 secondes, CPU à un thread. Les contrôles Ruff passent. Sur le VPS sans
PyTorch, ces tests sont explicitement ignorés et ne constituent pas une validation.

Réentraînement terminé le 15 novembre 2026 à **15:16:40 Paris**, sortie 0.
La première mise à jour CUDA a eu lieu à 15:09:06 pendant le benchmark ; la boucle
d'apprentissage a commencé à 15:09:08. Temps mesuré : **511,55 secondes au total**,
dont **300 secondes d'apprentissage**, 14 387 mises à jour, lot 128. Le budget de
600 secondes est respecté. Le checkpoint retenu est celui de l'étape **1 000** :
les mises à jour suivantes réduisaient la perte train sans améliorer la validation.

L'objectif de sélection, moyenne des F1 chaleur/fumée par famille en microgravité,
est passé de **0,29095** pour v1 recalibré à **0,51961** après réentraînement.
Les poids et les seuils ont été gelés à 15:14:08 avant les prédictions du test.
Seuils retenus : chaleur `0.9308615922927856`, fumée `0.9088770151138306`.

Sur les **84 cas test en microgravité** (parmi 96 cas test, dont 12 terrestres), les
comparaisons portent sur exactement les mêmes observations :

| Version | F1 chaleur | F1 fumée |
|---|---:|---:|
| Poids et seuils v1 gelés | 0,151 | 0,298 |
| Poids v1, seuils recalibrés sur validation v2 | 0,246 | 0,276 |
| Poids réentraînés, seuils sélectionnés sur validation v2 | **0,485** | **0,543** |

Le gain est réel sur ce nouveau test, mais la qualité reste modeste : précision /
rappel chaleur **0,451 / 0,524**, fumée **0,479 / 0,627**. Le modèle manque encore
des zones affectées et en signale à tort. Les F1 v1 calculés autrefois sur son
ancien test ne sont pas comparables directement à ceux de ce corpus plus varié.

| Famille test | F1 chaleur réentraîné | F1 fumée réentraîné |
|---|---:|---:|
| Capsule simplifiée | 0,425 | 0,473 |
| Soute | 0,529 | 0,544 |
| Racks centraux | 0,451 | 0,578 |
| Laboratoire inspiré ISS | 0,545 | 0,597 |
| Nœud inspiré ISS | 0,462 | 0,543 |
| Service inspiré ISS | 0,533 | 0,557 |

Les six familles progressent sur les deux sorties par rapport à v1 recalibré.
Les six contrôles 0 W de validation et les douze contrôles 0 W du test ont
**zéro faux positif**, pour les deux champs et les temps évalués (> 0). Cela ne
supprime pas les faux positifs des scénarios avec source active.

La stratification descriptive des cas retardés est conservée dans
`evidence/incidents/iss-poc-v2/model/fit1/diagnostics.json`. Elle ne montre pas de
dégradation monotone avec le retard et ne permet pas d'attribution causale :
retard, famille, disposition et incident ne sont pas isolés. La limite de
représentation temporelle de l'encodeur reste présente indépendamment de ces scores.

Utilisation GPU mesurée sur 509 relevés pendant toute l'exécution : médiane
**98 %**, maximum **99 %**, 54,6 % des relevés ≥ 90 % ; le reste inclut la
vérification et les exports CPU. Sur le cas de validation
`habitat-cargo-v2-05-flame`, une trajectoire de 31 images × 1 536 sondes prend en
médiane **84,7 ms sur CPU**, **52,7 ms sur GPU** (trois mesures à chaud).
L'écart maximal des scores CPU/GPU est 0,002665, avec zéro désaccord binaire sur ce
cas. Ces durées mesurent la préparation des entrées et l'inférence, pas une
simulation FDS ; elles ne garantissent pas les mêmes performances sur toute scène.

Le vérificateur indépendant a contrôlé les **384 exports**, leurs observations
FDS exactes, masques, chronologie, géométries, métriques et comparaisons v1. Rapport :
`evidence/incidents/iss-poc-v2/export-verification.json`. Cette vérification recalcule
les métriques à partir des scores enregistrés ; elle ne réexécute pas le réseau
sur l'ensemble des scènes et ne valide pas expérimentalement FDS.

Artefacts Windows : `E:/IGNIS-Valley-dev/runtime/iss-poc-v2/20261115/fit1/`.
Petits rapports locaux : `evidence/incidents/iss-poc-v2/model/fit1/`.

- Poids SHA-256 : `37bf3e0c5394cbe52fe520ebf85cbf393cd9b4203751d5b1db5c0c79641f987a`.
- État du réseau : `12b155793b74fe6e034f1f9c01c8093da94aacb220a049b000a42809125c42f1`.
- Snapshot dataset : `9f941aaf98c914804f21c68bd623fba908ed9fd8df29d816308c6ca4b51e855f`.
- Index viewer : `94d4c81e9ec55a9178f3d004ad52ece238d67faf9b6318e88aa17664bd68a5a7`.
- Archive : `E:/IGNIS-Valley-dev/runtime/iss-poc-v2/20261115/fit1.zip`,
  447 025 097 octets, SHA-256
  `33f5b0790480d352652dfa9bed4a2a1fd68f3f7542e8d678cb222c28ae07ca0f`.

Les archives de scores v1 restent sur Windows, dans `fit1/comparison-scores/`.
Aucun NPZ de labels FDS n'est ajouté au ZIP de livraison. Les anciens datasets,
poids et scripts v1 sont conservés. À 15:21:31 Paris, les processus du fit étaient
absents et le verrou partagé pouvait être acquis puis libéré ; le GPU global
affichait 0 % d'utilisation / 1 103 MiB. Aucun calcul supplémentaire n'est lancé.
