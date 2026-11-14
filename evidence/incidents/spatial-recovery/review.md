# Revue indépendante du protocole de récupération spatiale

Revue du code et des tests le **14 novembre 2026 à 18:51 UTC**, avant les résultats
du nouvel essai. Aucun accès au poste Windows, aucune exécution de FDS ou de
CUDA, aucune modification du code par cette revue. Les tests ont été examinés
sans relancer la suite exécutée par l'agent principal.

**Conclusion : aucun défaut bloquant identifié pour le diagnostic et le lot
compact bornés.** Cette conclusion porte sur la méthode et l'implémentation ;
elle ne démontre pas que le modèle apprend ni qu'il généralise.

## Perte, données et gradients

- `region_balanced_loss` normalise séparément les régions actives et le fond
  observé, pour chaque variable et chaque instant. Les canaux absents ne
  diluent pas les canaux présents. Une région vide ne crée pas de division
  par zéro ; un instant entièrement non observé est refusé.
- Les cibles NaN sont remplacées avant le calcul élémentaire de perte puis
  masquées. Les solides et valeurs manquantes ne deviennent pas des exemples
  d'air froid. Les faux positifs restent pénalisés dans le fond.
- Le test de dilution calcule une propriété exacte : pour un foyer de cible
  transformée 3 et une prédiction nulle, le gradient de ce foyer vaut −0,5,
  indépendamment des 9 ou 9 999 cellules calmes ajoutées. Les autres petits
  tests vérifient des valeurs et gradients analytiques pertinents, et ne
  prétendent pas mesurer la précision du modèle.
- Les deux grilles historiques sont conservées dans leurs coordonnées et
  formes réelles. Chaque batch contient les instants d'un seul cas ; aucune
  interpolation de cibles ni mélange de formes n'est effectué.
- La récupération crée des poids neufs. Le diagnostic ne publie pas de modèle
  utilisable par le service et ne doit pas être pris pour une validation.

## Séparation des données et évaluation

- Les sources historiques ne contribuent que par leur partition `train`.
  Les cas du précédent audit élargi ne sont pas ajoutés au fit.
- Les scènes et artefacts sont vérifiés par le lecteur existant, dont la
  reconstruction du compilateur. La sélection combinée refuse une signature
  physique ou une famille structurelle partagée entre partitions.
- La déduplication utilise la signature physique et le SHA du deck FDS. Les
  paires de gravité restent dans une même partition. Le plan compact conserve
  six familles d'entraînement, deux de validation et deux de test.
- Les époques sont choisies sur la validation compacte ; le test est évalué
  après cette sélection, sans réglage des seuils. Les métriques physiques sont
  confrontées à une seconde implémentation. La somme des TP/FP/FN/TN est une
  statistique de points et instants corrélés, pas un nombre d'incendies.
- Les poids sont hachés avant et après le test. Le chargement public est
  confronté aux prédictions évaluées sur un cas de validation ; il n'utilise
  pas le test pour sélectionner un autre modèle.

## Génération compacte et préservation

- Le runner copie des fichiers vérifiés par empreinte ; il ne crée pas de
  liens modifiables vers le corpus original. Les entrées, versions, identités,
  partitions et empreintes doivent correspondre au plan source.
- Le corpus original doit rester en pause. Le verrou de calcul commun couvre
  le pool de quatre solveurs à un thread. Les cas interrompus sont archivés
  lors d'une reprise ; les artefacts non reconnus ne sont pas écrasés.
- Un cas n'est enregistré comme terminé qu'après simulation, compression et
  vérification. Un index final n'est figé que si tous les cas planifiés sont
  terminés ; l'entraîneur refuse un jeu compact incomplet.
- Les tests du runner vérifient des propriétés utiles : réutilisation sans
  mutation source, refus de corruption, échéance sans nouveau solveur,
  annulation/reprise, échec exclu de la complétude et exclusion mutuelle du
  calcul. Aucun besoin de les dupliquer identifié par cette revue.
- L'identifiant `spatial-recovery-v1` reste séparé. La publication refuse une
  destination déjà existante et les métadonnées indiquent explicitement
  `provisional` et `automatic_ui_activation: false`.

## Limites à conserver dans le compte rendu

1. Les échéances d'entraînement sont vérifiées entre les batches. Vérification,
   évaluation et sérialisation peuvent dépasser le plafond de la phase. Le
   runner FDS annule les solveurs à l'échéance, mais termine prudemment une
   compression déjà commencée. Le budget d'une heure doit donc utiliser les
   durées réelles cumulées, avec marge et temps de test réservés, et non la
   simple somme des plafonds annoncés.
2. Le diagnostic compare les mêmes initialisation, ordre des cas, tirages
   d'instants et plafond d'époques. Un plafond en secondes peut toutefois
   produire des nombres d'époques ou de mises à jour différents. Ces comptes
   figurent dans les résultats ; un écart de résultat ne doit pas être attribué
   exclusivement à la nouvelle perte sans en tenir compte.
3. `choose_small` garantit les cinq types d'incident et ajoute un contrôle
   calme si disponible, mais ne garantit pas les deux gravités. Le petit lot
   n'est pas un échantillon représentatif ; la parité gravitationnelle est
   garantie par le plan compact utilisé ensuite.
4. Le score de validation applique la formule régionale aux **champs décodés
   effectivement délivrés**, avec les bornes physiques du décodeur, puis
   réencodés. Ce n'est donc pas strictement la perte sur les sorties brutes du
   réseau utilisée au fit ; ce choix doit être formulé explicitement.
5. FDS fournit des cibles synthétiques conditionnelles à un incident imposé.
   Une amélioration sur ces cibles ne valide ni une probabilité de panne
   électrique ni les modèles physiques contre des expériences NASA. Les
   grilles de mesure clairsemées ne garantissent pas d'observer tous les pics
   présents sur le maillage interne du solveur.

## Empreintes du code lu

Ces empreintes désignent les fichiers relus à l'instant indiqué. Les évolutions
ultérieures ou la version réellement exécutée doivent être identifiées par
les manifestes propres à l'expérience.

| Fichier | SHA-256 |
| --- | --- |
| `backend/ignis/ml/spatial_training.py` | `74584a3b0abe98e7189918553b4c234b0eb84e2d332f6b93c916b15ceb366575` |
| `backend/ignis/ml/spatial_network.py` | `d03c25cc2aafd90c437222c83bd432bb227fb2fd53bd4100ceee8137b166f1b7` |
| `tools/remote/recover_spatial.py` | `2c598c7ce46e2d4065e61294c5b1f22799291c8946d105ed9a4d3c81584955af` |
| `tools/remote/generate_compact_spatial.py` | `b335d9f88a305a75a1b7e53659db11ec3b1512d11a246d2595acc1a80d6116e6` |
| `tests/test_spatial_recovery.py` | `7bb2d8135090093689d70c4cf44089c31cd973ea8ffe9b80c9ead54b93c699ec` |
| `tests/test_compact_spatial_runner.py` | `dae8ae981210b9e8cb7d4eeff5469c583e207e0e1a92e5d29a9b375b4cf7422a` |

## Addendum — perte de localisation, 19:02 UTC

Le [premier diagnostic](diagnostic-report.json) dure **77,014 s** et porte sur
six cas d'entraînement. Les deux variantes ont réellement effectué **80 époques
et 1 920 mises à jour chacune**. Les comptes ont été relus indépendamment :

| Objectif | Chaleur TP / FP / FN | Rappel / précision | Fumée TP / FP / FN | Rappel / précision |
| --- | --- | --- | --- | --- |
| Historique | 303 / 213 / 140 | 68,40 % / 58,72 % | 1 155 / 1 340 / 234 | 83,15 % / 46,29 % |
| Régions équilibrées | 443 / 6 340 / 0 | 100 % / 6,53 % | 1 373 / 27 686 / 16 | 98,85 % / 4,72 % |

La perte régionale de diagnostic diminue de 0,216 à 0,142, mais la localisation
se dégrade nettement. Cela justifie de ne pas choisir cette variante sur ce
seul score. Ce résultat de surapprentissage ne permet pas d'estimer la
généralisation. L'écart n'est pas dû ici à un nombre d'époques différent.

La nouvelle ablation `localized` conserve l'architecture et les seuils
physiques. Elle ajoute à la régression historique un terme de support souple
pondéré par 0,25 : Tversky avec poids FP = 0,7 et FN = 0,3, plus 0,1 fois une
BCE moyennée sur les cellules observées. Les seuils transformés sont bien
`asinh(5/20)` et `asinh(1e-7/1e-6)`, avec température de lissage fixée à un
huitième du seuil. Il s'agit d'un substitut différentiable de présence,
**pas d'une probabilité calibrée**.

La formule relue neutralise les cellules non observées, traite une région sans
positif par la BCE seule et moyenne les canaux présents. Les nouveaux tests
vérifient qu'une expansion fictive du panache augmente la pénalité à rappel
identique, et que les gradients des cellules absentes restent nuls. Les tests
de sélection des cas couvrent aussi l'exclusion des anciennes partitions
validation/test, la déduplication et le refus de fuite par géométrie ou famille.
Cette revue n'a pas réexécuté les tests Windows.

La sélection d'époque utilise désormais, par cas puis par disposition, le
score encodé composite existant plus `0,5 × (1 − IoU chaleur)` et
`0,5 × (1 − IoU fumée)`. Une union vide vaut IoU = 1. Les seuils ne sont pas
ajustés ; le test reste réservé après sélection. L'ancien score régional reste
disponible pour la comparaison des diagnostics. Cette heuristique de sélection
rend les faux positifs visibles ; son efficacité reste à mesurer et n'est pas
une garantie scientifique de généralisation.

**Aucun blocage identifié pour l'ablation `localized`.** Un défaut de
provenance secondaire a été signalé : dans la version relue, choisir
`--objective historical` au mode `train` inscrit à tort la version de perte
régionale dans `metadata.training.loss`. Le champ `objective` est exact et le
chemin `localized` prévu n'est pas affecté ; cette étiquette doit néanmoins être
corrigée avant de publier un entraînement historique.

Les réserves précédentes sur le budget réel cumulé, les grilles de mesure et
les limites physiques restent applicables. Un deuxième diagnostic est du
calcul additionnel à comptabiliser, même s'il réutilise les données existantes.

| Fichier relu à 19:02 UTC | SHA-256 |
| --- | --- |
| `backend/ignis/ml/spatial_training.py` | `a4db8937de05582a67e9febe224caeef29be46c2022dd11c30ed45e2f6092c73` |
| `tools/remote/recover_spatial.py` | `cf58f326956afc60cac96e525dfbd4da7dc7c6bbebbad83aeefaf89a5cf20ef8` |
| `tests/test_spatial_recovery.py` | `da24a994ef2ae5318f634a7907bb8e5de3a2e43ca53a36bcad03eec46be9c820` |
| `diagnostic-report.json` | `5001532ddbcd51258d76767fd8809c43c91b7e7100e5b7733bf51c3d71270c12` |

## Addendum — corpus terminé et compatibilité, 19:13 UTC

Le relevé [generation-100-progress.json](generation-100-progress.json) indique
un premier corpus compact terminé : **100 cas sur 50 dispositions**, dont
**92 calculés et 8 réutilisés**, en **980,734 s**, sans échec. Il rapporte
60 cas d'entraînement, 20 de validation et 20 de test, dix cas par famille
structurelle et vingt par type d'incident. Ces totaux sont cohérents entre eux.
Il s'agit ici d'une lecture du relevé transféré ; cette revue n'a pas relu les
100 dossiers du poste Windows. Leur vérification d'empreintes et reconstruction
du compilateur restent effectuées par le chargeur avant le fit.

La version réexaminée de `recover_spatial.py` corrige le défaut de métadonnée
signalé ci-dessus : chaque objectif reçoit désormais sa propre version,
notamment `historical-observed-smoothl1-active5` pour l'objectif historique.

- Le scheduler `ReduceLROnPlateau` reçoit seulement le score de validation.
  Son facteur, sa patience, son plancher et la patience d'arrêt sont enregistrés.
  Le taux indiqué pour chaque époque est celui effectivement utilisé avant
  la mise à jour du scheduler. Le test intervient toujours une fois les poids
  de la meilleure époque sélectionnés.
- `--dataset` permet de lire un autre emplacement de corpus compact sans
  modifier le premier. Son identité doit rester `spatial-compact-v1` et sa
  grille doit être 12 × 16 × 8. La grille historique du pilote reste 8 × 10 × 4.
  Le snapshot final conserve les chemins des sources ainsi que leurs
  empreintes et les partitions effectives.
- L'extension éventuelle via `--reuse-compact` exige un corpus source complet
  avec index figé vérifié. La destination est indépendante de la source ; les
  cas copiés doivent correspondre exactement au plan agrandi. La chaîne de
  provenance antérieure est conservée sous `upstream`. Aucun réétiquetage des
  partitions ni duplication d'observations dans le fit n'est introduit.
- Le chargeur des modèles historiques conserve son contrôle d'égalité avec
  l'unique `sample_shape`. Seul l'identifiant `spatial-recovery-v1` consulte
  `supported_sample_shapes`. Le test ajouté vérifie aussi qu'une telle
  métadonnée ne peut pas élargir silencieusement le contrat d'un ancien modèle.
  L'entraîneur historique exclut désormais explicitement le nouvel identifiant
  de récupération de ses choix CLI, tout en conservant ses anciens modèles.
- Ni l'ajout de plusieurs grilles déclarées, ni la possibilité d'importer des
  annotations de scène ne démontrent une généralisation à un fichier Blender
  arbitraire. Les métadonnées maintiennent explicitement cette limite, ainsi
  que l'absence de vitesse interne supervisée et de validation expérimentale
  NASA. Aucune activation automatique du modèle dans l'interface n'est ajoutée.

**Aucune régression du contrat des anciens chargeurs ni fuite de test
identifiée dans ces changements.** Les résultats de la nouvelle ablation et
du modèle final ne sont pas encore audités dans cet addendum. Les durées réelles
de tous les diagnostics, générations et entraînements doivent rester cumulées
pour la limite d'une heure.

| Fichier relu à 19:13 UTC | SHA-256 |
| --- | --- |
| `tools/remote/recover_spatial.py` | `d09bd7ccfd7e09199f14cd997924be4d77294ad60e6771043f1ef5d95103776b` |
| `backend/ignis/ml/spatial_network.py` | `d03c25cc2aafd90c437222c83bd432bb227fb2fd53bd4100ceee8137b166f1b7` |
| `tools/remote/train_spatial.py` | `78c51544cec48e41124a2ae2d2a2a14ca35d8c116486875b46b2c3b5408aa32f` |
| `tools/remote/generate_compact_spatial.py` | `647e48fc5e8969fb2590483c4470e727881e2c0a8942bb40bf48324214dfd780` |
| `tests/test_spatial_network.py` | `3ce9dc84b6784a385b7f61a7f82de3555c2926e2ea762e6a92b928817a87079b` |
| `generation-100-progress.json` | `394fb35c71f16d20e0eb1b0175a227b921e2b8f65bf060b455878f4a6994ca7d` |

## Addendum — deuxième ablation et arrivée de fumée, 19:24 UTC

Le [diagnostic de localisation](localization-diagnostic-report.json) s'est
terminé en **74,947 s**, avec 80 époques et 1 920 mises à jour pour chacune des
deux variantes. Les fichiers `small-set-first.json` et
`small-set-localization.json` sont identiques octet pour octet
(SHA-256 `6f7a91a8c21e46a9347fa2b6e3a30abbe0f96e07292aac440c667cda870a2eda`).
Les comptes et ratios transférés donnent :

| Mesure sur les six cas d'entraînement | Historique | Localisation |
| --- | ---: | ---: |
| Score composite, plus faible préférable | 0,9711 | 1,3564 |
| Rappel chaleur | 88,49 % | 36,34 % |
| Précision chaleur | 26,81 % | 96,99 % |
| IoU chaleur, comptes regroupés | 25,91 % | 35,94 % |
| Rappel fumée | 96,98 % | 27,36 % |
| Précision fumée | 14,89 % | 88,99 % |
| IoU fumée, comptes regroupés | 14,82 % | 26,46 % |
| Erreur moyenne des pics de température, dispositions équipondérées | 69,97 °C | 95,09 °C |

Le terme de localisation supprime beaucoup de faux positifs, mais manque
beaucoup plus de points actifs et reproduit moins bien les amplitudes chaudes.
**Retenir l'objectif historique pour l'essai final est cohérent avec le score
composite et la priorité donnée aux foyers manqués.** Il serait inexact de dire
que toutes les métriques de localisation se dégradent : précision et IoU
regroupée s'améliorent. Il ne s'agit pas d'une preuve que Tversky serait
inadapté en général, mais du rejet de cette recette précise dans cet essai.

La variante historique diffère sensiblement entre les deux exécutions malgré
la même liste de cas, les graines et le nombre de mises à jour. Les manifestes
de sources ne changent que pour `recover_spatial.py` et `spatial_training.py`.
Les algorithmes CUDA déterministes ne sont pas imposés ; les nouveaux champs
de métadonnées enregistrent cette situation explicitement. La cause exacte de
la variation n'est pas isolée par ces essais. Éviter toute comparaison causale
entre exécutions ou toute garantie de reproduction numérique fondée sur la
seule graine. L'essai final combine aussi plus de données, une sélection
différente et un scheduler : un gain éventuel ne serait pas attribuable à la
seule diversité des données.

La fonction `smoke_arrival` a été relue :

- Elle mesure le premier **instant échantillonné** où la suie atteint
  `1e-7 kg/m³`, sans inventer une interpolation temporelle.
- Elle ne retient que les points disposant d'observations finies sur toute la
  fenêtre commune. Le compteur des points exclus inclut aussi les solides,
  qui ne constituent pas des observations gazeuses.
- Les erreurs de temps et leur biais sont conditionnels à une arrivée à la
  fois dans FDS et dans la prédiction. Les arrivées manquées, fausses arrivées
  dans la fenêtre et doubles non-arrivées sont comptées séparément. L'absence
  d'arrivée n'est remplacée ni par zéro ni par le dernier instant.
- La fenêtre et son pas maximal sont fournis. Une non-arrivée signifie
  seulement aucune traversée du seuil avant la fin de cette fenêtre.
- Le test relu utilise des instants irréguliers 0, 2 et 5 s et distingue les
  quatre cas, ainsi qu'une observation incomplète. Le relevé
  [arrival-tests.xml](arrival-tests.xml) indique 11 tests Windows passés,
  sans échec, erreur ou test ignoré. Cette revue ne les a pas relancés.

Le script `replay_spatial_recovery.py` effectue uniquement une inférence avec
poids figés sur les 60 anciens cas diagnostiques. Il vérifie le plan, les cas
chargés, l'absence de leur deck dans l'entraînement et la stabilité des poids
et fichiers du modèle. Il qualifie explicitement ce rejeu de diagnostic déjà
connu, distinct du test compact réservé. Aucune sélection de poids, simulation
supplémentaire ou activation en production n'y est ajoutée.

Un défaut de compte rendu, sans effet sur l'entraînement, a été signalé dans
la version relue de `analyze_spatial_recovery.py` : les groupes du rejeu ne
transmettent pas leurs `per_case_arrival` à `report_summary`, qui les marque
alors indisponibles malgré leur présence dans le rapport source. Il faut
transmettre les enregistrements correspondant aux identifiants du groupe pour
les exposer dans l'analyse consolidée. Le rapport source reste intact.

**Aucun blocage identifié pour l'entraînement final avec l'objectif
historique.** L'interprétation définitive attend les métriques du test réservé
et le contrôle du budget réel cumulé, incluant les deux diagnostics.

| Fichier relu à 19:24 UTC | SHA-256 |
| --- | --- |
| `tools/remote/recover_spatial.py` | `8a5f0a4089d4713e18834cd7f970e40f3a001a4fd802ea76a8d94732483c4976` |
| `tools/remote/replay_spatial_recovery.py` | `9b375fa6956aa52b5f84c92992bfea9aac983dcc40fe278b11ad32732fd0d719` |
| `tools/remote/analyze_spatial_recovery.py` | `9ac13685652d2adcbc799a5140ad220963a0205f9242191ccbd9d565389d8f34` |
| `tests/test_spatial_recovery.py` | `c5ac0f8eed57deec9a352a1bd403abcbf12fe0222872dc865e255766eae641dd` |
| `localization-diagnostic-report.json` | `79d1482cab12d557b397cc3bfc97dc45aabae35c332095da21f4ba48253fa30a` |
| `arrival-tests.xml` | `1d916e6edd0f9db8e6784dd19af8285e43eecd41aa65513205019f3e0b3d8f01` |

## Revue finale des résultats transférés — 19:49 UTC

**Les rapports sont cohérents et traçables, mais le modèle reste insuffisant
pour prédire les foyers chauds et pour fournir une localisation fiable de la
fumée en microgravité.** Aucun défaut bloquant de comptage ou de séparation des
données n'a été identifié. La qualité prédictive constitue en revanche un
obstacle à toute présentation comme outil fiable de sécurité incendie.

Cette dernière revue a seulement lu et recalculé des résumés locaux. Elle n'a
lancé aucune simulation, aucun entraînement et aucune inférence. Elle n'a pas
accédé au poste Windows ni inspecté directement ses fichiers de poids.

### Traçabilité et partitions

Les neuf empreintes de `training-sources.json` correspondent exactement aux
sources actuelles et aux empreintes inscrites dans les métadonnées finales.
L'empreinte canonique de `model-dataset-snapshot.json` correspond à
`dataset_snapshot_sha256` ; son empreinte de fichier correspond aussi à celle
enregistrée par le rejeu. Les identités des poids dans les rapports
d'entraînement et de rejeu sont identiques. Les trois fichiers utilisés par
`analysis.json` correspondent à ses empreintes d'entrée.

| Partition effective | Cas | Dispositions | Origine |
| --- | ---: | ---: | --- |
| Entraînement | 170 | 66 | 120 compacts + 30 pilotes + 20 du corpus historique |
| Validation | 40 | 20 | Compact uniquement |
| Test réservé | 40 | 20 | Compact uniquement |

Chaque partition est équilibrée entre les deux gravités et les cinq types
d'incident : respectivement 85/85 et 34 cas par type à l'entraînement ; 20/20
et huit cas par type en validation comme en test. Les familles de validation
sont `cross-aisle` et `split-bays` ; celles du test sont `baffled` et
`double-island`. Les six autres familles procédurales restent à l'entraînement.

Recalcul indépendant à partir du snapshot : aucun deck ou signature physique
ne traverse les partitions, aucune famille structurelle ne traverse les
partitions et aucun doublon exact n'est présent dans une partition effective.
Chaque cas sélectionné correspond au statut, au split, à la signature et au
SHA du deck de son enregistrement source. Aucune ancienne partition de
validation ou de test n'alimente l'entraînement.

Le meilleur score de validation se trouve bien à l'époque **32 sur 52** ; les
métriques finales de validation correspondent à ce minimum. L'arrêt après
vingt époques sans amélioration est cohérent avec la recette enregistrée. Le
test reste distinct et n'a pas servi à choisir ce checkpoint selon le journal
et le code exécuté.

### Métriques vérifiées et conclusion pour la microgravité

Les moyennes par disposition et les comptes TP/FP/FN/TN ont été recalculés
indépendamment pour la validation, le test, le témoin ambiant et les deux
groupes du rejeu. Ils correspondent aux rapports. Les erreurs des pics des
40 cas exportés correspondent également aux métriques du test.

| Test réservé | Rappel chaleur | Rappel fumée | Précision fumée | IoU fumée |
| --- | ---: | ---: | ---: | ---: |
| Deux gravités, 40 cas | **1,94 %** | 87,09 % | 57,37 % | 52,88 % |
| **Microgravité, 20 cas** | **16,45 %** | **71,99 %** | **18,52 %** | **17,27 %** |
| Terre, 20 cas | **0,042 %** | 87,63 % | 61,11 % | 56,26 % |

Ces valeurs regroupent des observations de points et d'instants corrélés,
avec les seuils exploratoires ambiance + 5 °C et suie ≥ `1e-7 kg/m³`. Il ne
s'agit ni de taux d'incendies détectés ni de seuils de sécurité validés.

La moyenne des deux gravités masque une limite essentielle pour le challenge
NASA : les comptes de fumée positive comprennent **72 641 observations
terrestres contre 2 578 en microgravité**. Les 87,09 % de rappel et 57,37 % de
précision globaux ne doivent donc pas être annoncés comme performances en
microgravité. Dans cette dernière, **environ 81,5 % des alertes de fumée sont
fausses** au seuil retenu.

La chaleur reste très sous-estimée. Parmi les cas réservés,
`procedural-0055-electrical-02-overheating-microg-c1` atteint **407,69 °C** dans
les observations FDS contre **25,45 °C** pour le maximum prédit. La MAE globale
de température de 0,178 °C ne compense pas cet échec : l'erreur dans les régions
chaudes est de 23,99 °C et le rappel global est de 105 observations détectées
sur 5 421 positives.

Le rejeu des 60 anciens diagnostics utilise bien les mêmes poids. Il reste
un diagnostic connu, pas un nouveau test indépendant. Les améliorations de
fumée constatées sur ces cas ne changent pas la conclusion du test réservé.
Les deux familles procédurales de test et vingt dispositions ne suffisent
pas à établir une généralisation à des modèles Blender arbitraires.

### Arrivées de fumée et correction du compte rendu

Le défaut de transmission signalé dans l'addendum précédent est corrigé :
`analyze_spatial_recovery.py` transmet désormais les `per_case_arrival` filtrés
par les identifiants de chaque groupe du rejeu. Les deux listes consolidées
sont exactement égales aux sous-ensembles du rapport source.

Les quatre catégories d'arrivée totalisent bien les points admissibles dans
chaque cas. Sur le test réservé : 4 539 points présentent une arrivée dans les
deux trajectoires, 516 arrivées sont manquées, 2 660 arrivées sont prédites à
tort dans la fenêtre et 52 761 points n'atteignent le seuil dans aucune des
deux trajectoires. Il y a 60 476 points admissibles et 964 points exclus.

Parmi les **4 539 points avec une arrivée des deux côtés uniquement**, la MAE
temporelle pondérée par point vaut 4,787 s et le biais −3,011 s. Ce résumé
conditionnel exclut les arrivées manquées et fausses ; il ne constitue pas une
précision temporelle globale du modèle. Les erreurs absentes restent `null`
quand aucune paire d'arrivées n'est disponible.

### Données générées, temps et état du modèle

Le corpus compact final contient **200 cas sur 100 dispositions**. La première
phase a calculé 92 nouveaux cas et réutilisé huit cas ; la seconde a calculé
100 nouveaux cas et copié les 100 du premier corpus. Cela fait **192 nouvelles
simulations distinctes**, et non 300 : les copies ne sont pas de nouvelles
données indépendantes. Les corpus précédents sont conservés.

| Phase | Durée rapportée |
| --- | ---: |
| Diagnostic historique / équilibré | 77,014 s |
| Premier corpus de 100 cas | 980,734 s |
| Diagnostic historique / localisation | 74,947 s |
| Extension à 200 cas | 1 110,500 s |
| Entraînement final, évaluation et publication provisoire | 452,403 s |
| Rejeu | 2,579 s |
| **Somme des phases** | **2 698,177 s, soit 44 min 58 s** |

Les durées des lanceurs, qui incluent leur initialisation supplémentaire,
totalisent 2 711,110 s. Entre le premier lancement à 18:50:48,923 UTC et la fin
du rejeu à 19:41:44,164 UTC, il s'écoule **3 055,241 s, soit 50 min 55 s**.
La limite d'une heure est donc respectée sur ces deux bases. Ces durées ne
signifient pas 45 minutes d'entraînement GPU : FDS génère les cibles sur CPU,
alors que le réseau s'entraîne et prédit sur la RTX 4070 Ti.

Les métadonnées confirment `provisional: true`,
`automatic_ui_activation: false` et des algorithmes CUDA non forcés au
déterminisme. Aucune nouvelle campagne ni activation en production ne découle
de cette revue. Les seuils, matériaux, sources imposées et références FDS
synthétiques limitent toujours la portée du résultat ; aucune probabilité
réelle de départ de feu ou validation expérimentale NASA n'est établie.

| Artefact final relu | SHA-256 |
| --- | --- |
| `training-report.json` | `6ed509d7c709983f9639e0c1299430a424b82943fae3856cc99ffa64bb714657` |
| `replay-report.json` | `6443427039f523e55212f1edeb5c2e10c2a370006f9f627fe0d0fed321e774eb` |
| `analysis.json` | `a4bf48a7e189562fe8a4cdf9b8a4862608dbe6cfc815b5cc266185f98530fbec` |
| `training-sources.json` | `32a673709fc848bf798b65365c2c249a566f3f66640db3c08540819136db3135` |
| `model-dataset-snapshot.json` | `be7e7578f76251b18377ef5ecb481ce7c4826f0456c082e10110b4d921b61d8f` |
| `tools/remote/recover_spatial.py` | `95d1d6119a386efa08cbdb21a2e3ef47e1edc1cf9659a177408cce7195f2db23` |
| `tools/remote/replay_spatial_recovery.py` | `9b375fa6956aa52b5f84c92992bfea9aac983dcc40fe278b11ad32732fd0d719` |
| `tools/remote/analyze_spatial_recovery.py` | `d40464e7e00da0374470ee5529c348fa6ae3d0821db45061b15ff2fa2eea5ec5` |

## Correctif des fixtures CI — 19:58 UTC

**Diff approuvé à la lecture, sans défaut bloquant.** Seuls les tests de
campagne sont modifiés : leurs fixtures simulent 40 Gio libres pour ne plus
dépendre du disque du runner CI. Le `monkeypatch` est restauré après chaque
test. L'override explicite à 19 Gio s'applique après la fixture et reste
effectif, aussi bien dans le test historique conservé que dans le nouveau
test compact.

Le nouveau test exige `state == "disk_reserve"`, un corpus non prêt pour
l'entraînement et **zéro appel au faux solveur**. Les contrôles réels des deux
runners et de `FDSRunner` ne sont pas modifiés ; la réserve de 20 Gio n'est pas
abaissée. Les sources entraînées restent inchangées. Cette revue n'a exécuté
aucun test ni calcul ; elle ne présume pas du résultat du prochain run CI.

Empreintes des tests relus :

- `tests/test_spatial_corpus.py` : `f4098847869e6755a9ab456d3b66e29d41e5ba5229fc700785be352b0693fa34`.
- `tests/test_compact_spatial_runner.py` : `1777d96cfc57b61ab3184df7100ec4bbb14dc42fc6995d57be4bc0674027b8a9`.
