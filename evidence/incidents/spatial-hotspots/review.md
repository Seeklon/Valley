# Revue indépendante — apprentissage des points chauds

## Analyse initiale, 14 novembre 2026 à 20:12 UTC

Lecture seule du code et des preuves du précédent essai. Aucun entraînement,
simulation, accès Windows ou changement des sources par cette revue. Les
recommandations ci-dessous sont un protocole proposé ; elles ne décrivent pas
des calculs déjà exécutés. La nouvelle implémentation `hotspot_spatial.py`
n'est pas encore relue à ce stade.

### Constats établis

Le jeu d'entraînement précédent contient 170 cas, dont 85 en microgravité et
85 terrestres. Recalcul à partir du survey et des configurations du snapshot,
sans déduire la gravité du seul nom de fichier :

| Mesure sur les trajectoires d'entraînement, après t = 0 | Ensemble | Microgravité | Terre |
| --- | ---: | ---: | ---: |
| Observations de température disponibles | 6 475 156 | 3 211 696 | 3 263 460 |
| Observations ≥ ambiance + 5 °C | 20 440 | 2 234 | 18 206 |
| Fraction chaude | 0,3157 % | **0,0696 %** | 0,5579 % |
| Cas dont le pic dépasse 50 °C | 31 | 24 | 7 |
| Cas dont le pic dépasse 100 °C | 14 | 13 | 1 |
| Cas dont le pic dépasse 200 °C | 6 | 6 | 0 |

Ces comptes représentent des points et instants corrélés, pas des événements
indépendants. L'entraînement comporte des pics observés jusqu'à 445,07 °C :
il existe donc des cibles chaudes à apprendre. Les mesures gazeuses restent
clairsemées ; elles ne représentent pas le maximum de chaque cellule FDS.

L'objectif historique attribue un poids cinq aux valeurs actives, mais divise
par la somme des poids de tous les points et des deux champs. En cumulant les
comptes microgravité, les observations chaudes représentent seulement environ
**0,172 % de cette masse de pondération**. C'est un indicateur de dilution,
pas la contribution exacte aux gradients : ceux-ci dépendent de l'erreur, de
la normalisation par batch, des poids par disposition et de l'ordre des mises
à jour.

La transformation de température est `asinh((T − ambiance)/20)`. Des excès de
20, 100 et 400 °C deviennent environ 0,881, 2,312 et 3,690. La SmoothL1 sature
ensuite son gradient par rapport à l'erreur transformée au-delà de un. Cette
combinaison comprime l'importance des fortes amplitudes ; c'est une cause
plausible supplémentaire, qui reste à départager expérimentalement.

En revanche, il n'y a pas de plafond architectural à 25 °C : la tête de champ
est linéaire et le décodeur accepte jusqu'à 2 500 °C. L'initialisation nulle
des têtes empêche le gradient d'atteindre leur tronc à la toute première mise
à jour, mais ne l'y bloque pas après la mise à jour des poids de tête. Elle
ne démontre donc pas, à elle seule, une panne durable d'apprentissage.

Le tirage de 16 instants sur 30 par cas et par époque peut raréfier le signal
du pic dans un batch. Après 52 époques, ce n'est cependant pas une preuve que
les instants chauds n'ont jamais été vus. Une sélection explicite d'instants
chauds doit être testée à budget de mises à jour contrôlé, en conservant des
instants calmes et l'évaluation des trajectoires entières.

### Ce que l'ancien essai ne permet pas de conclure

- Les métriques physiques finales des 170 cas d'entraînement ne sont pas
  publiées : seule une perte globale mixte est suivie. Sans lecture de leurs
  pics et de leur localisation, on ne peut pas séparer proprement
  sous-apprentissage et échec sur des scènes nouvelles.
- Le petit diagnostic à six cas améliore fortement certains rappels, mais
  conserve des erreurs d'amplitude et varie entre exécutions historiques.
  Une graine identique n'a pas garanti le déterminisme CUDA. Les comparaisons
  entre exécutions ne sont donc pas une ablation causale propre.
- La perte équilibrée par régions a atteint 100 % de rappel chaleur avec
  seulement 6,53 % de précision. Le résultat montre pourquoi une pénalité
  sur le fond et des contrôles froids doivent accompagner toute mise en
  avant des pics.
- Le score de validation associait chaleur, fumée, statistiques globales et
  localisation. Son minimum à l'époque 32 n'est pas nécessairement celui du
  meilleur modèle de pics. Les époques ultérieures augmentaient le rappel
  chaud, mais surtout les fausses alertes : prolonger sans changer le
  diagnostic ne résout pas le compromis.
- Une représentation par fractions de voxels peut perdre des détails fins
  de géométrie ; le réseau n'a pas de champ de vitesse interne supervisé.
  Cela constitue une limite plausible de généralisation, pas une raison
  démontrée d'agrandir immédiatement le réseau. Il faut d'abord vérifier
  qu'il ajuste correctement des cibles connues.

### Protocole minimal discriminant proposé

1. **Vérifier l'observation et ajuster une trajectoire connue.** Choisir
   uniquement parmi les cas `train` une trajectoire dont le pic échantillonné
   est nettement supérieur à 100 °C, ainsi qu'un cas froid. Vérifier le point
   gazeux, l'instant, les masques, l'encodage et le décodage de ce pic avant
   optimisation. Ajuster volontairement ce petit lot puis évaluer la
   trajectoire complète, pas seulement les instants choisis pour le fit.

2. **Comparer une seule modification à la référence.** Sur environ huit cas
   `train` de plusieurs amplitudes et des deux gravités, comparer la perte
   historique et une correction ciblant les points chauds. Utiliser le même
   état initial, la même liste ordonnée de batches et le même nombre de mises
   à jour. Séparer une modification de perte d'une modification du tirage des
   instants. Si le temps le permet, répéter avec une seconde graine ; sinon,
   conserver explicitement la limite d'un seul essai. Le mode CUDA
   déterministe, s'il est activable, aide cette comparaison mais son surcoût
   fait partie du budget.

3. **Vérifier les amplitudes, les positions et les faux positifs.** Une perte
   supplémentaire au point du vrai pic, ou sur un petit ensemble de points
   chauds choisis à partir des cibles d'entraînement, peut tester l'hypothèse
   de dilution. Une perte sur le seul maximum global ne suffit pas : un pic
   prédit au mauvais endroit pourrait la satisfaire. Conserver une mesure
   explicite des fortes prédictions dans le fond, plutôt qu'accepter une
   nappe chaude partout.

4. **Étendre seulement après le diagnostic.** Entraîner sur les données
   existantes, avec un panel fixe de cas d'entraînement évalué physiquement.
   La comparaison train/validation doit montrer si le défaut persiste sur
   les exemples vus ou apparaît surtout sur des dispositions nouvelles. Ne
   modifier ni seuil ni sélection d'époques après lecture d'un test final.

Les critères à fixer avant ce diagnostic sont des critères d'ingénierie,
pas des normes de sécurité. Un exemple de porte de passage est la
reproduction de l'excès thermique maximal d'un cas connu à ±20 %, un maximum
prédit à moins d'un pas d'échantillonnage de sa position, et l'absence de zone
chaude étendue sur les contrôles froids. Si ce niveau n'est pas atteint sur
un cas déjà vu, davantage de scènes ou de paramètres ne constitue pas une
réponse établie.

### Mesures nécessaires

Pour chaque trajectoire chaude : température prédite **à la coordonnée et à
l'instant du pic FDS**, maximum global prédit, rapport des excès thermiques,
erreur de localisation en mètres et en pas de grille, et décalage temporel
du pic. Ajouter les erreurs dans les régions actives et les faux positifs du
fond. Le rappel au seul seuil ambiance + 5 °C ne prouve pas la récupération
d'un pic à 100 ou 400 °C.

Une perte sur le pic du champ doit utiliser le maximum des **observations
gazeuses échantillonnées**. La cible globale `temperature_max_c` provient
indépendamment des statistiques FDS du domaine complet ; elle peut dépasser
ce maximum clairsemé. La forcer comme maximum du champ prédit créerait une
contradiction avec les cibles ponctuelles et pourrait inventer un foyer dans
une cellule de mesure qui n'en observe pas.

Présenter les métriques par cas/disposition et par gravité, avec dénominateurs.
Les précédents 87,09 % de rappel fumée regroupés masquaient une précision de
18,52 % en microgravité. Ne pas compenser de nouveau une faiblesse sur les
scènes microgravité par davantage d'observations terrestres.

### Réserves et budget

Les quarante anciens cas de test ont maintenant été examinés pour concevoir
cette correction : ils constituent des **diagnostics connus** de ce nouvel
essai. Pour revendiquer une nouvelle mesure de généralisation indépendante,
réserver des dispositions jusque-là inédites, par exemple des indices
procéduraux ≥ 100, avec familles et conditions fixées avant leurs résultats.
À défaut, qualifier honnêtement la nouvelle évaluation de diagnostic sur des
cas connus. Un partage aléatoire d'instants d'une même trajectoire ne crée pas
un test de généralisation géométrique.

Les masques chauds tirés des cibles peuvent piloter la perte ou le tirage des
exemples `train`, mais ne doivent jamais devenir des entrées du modèle à
l'inférence. Les caches GPU doivent préserver coordonnées, formes, dtypes,
masques et partition ; un regroupement en batches ne justifie pas
d'interpoler les deux grilles historiques.

La nouvelle heure de calcul couvre les diagnostics, l'entraînement, les
éventuelles nouvelles références et l'évaluation, avec une marge réservée
à la fin. Elle ne recommence pas pour chaque variante. Les neuf sources
entraînées, les corpus et modèles précédents doivent rester inchangés ; le
nouveau runner et ses artefacts nécessitent leur identité propre.

### Empreintes des éléments lus

| Élément | SHA-256 |
| --- | --- |
| `tools/remote/recover_spatial.py` | `95d1d6119a386efa08cbdb21a2e3ef47e1edc1cf9659a177408cce7195f2db23` |
| `backend/ignis/ml/spatial_network.py` | `d03c25cc2aafd90c437222c83bd432bb227fb2fd53bd4100ceee8137b166f1b7` |
| `spatial-recovery/final-training-survey.json` | `2aea0a04dffd7095ffc3d4580acf56267616075b97357d46785c8bfba594c084` |
| `spatial-recovery/training-report.json` | `6ed509d7c709983f9639e0c1299430a424b82943fae3856cc99ffa64bb714657` |

## Revue du runner de diagnostic, 14 novembre 2026 à 20:21 UTC

Lecture complète de `tools/remote/hotspot_spatial.py` et de ses tests, plus
vérification des interfaces héritées (`prepared`, `masked_loss`, `assess`,
`predict_case`, `require_cuda`). Aucun calcul CUDA, accès Windows ou test
supplémentaire exécuté par cette revue. Le responsable de l'exécution a
signalé six tests ciblés réussis sur Windows avec PyTorch ; ce résultat est
rapporté, pas reproduit indépendamment ici.

**Verdict avant exécution : aucun blocage identifié pour le diagnostic
`uniform`/`hot`, avec les réserves de comparaison ci-dessous.** Ce verdict
porte sur un surapprentissage diagnostique de huit cas d'entraînement, pas
sur un entraînement généralisable ni une activation dans l'interface.

### Contrats vérifiés

- La sélection prend six événements de types surchauffe, flamme et batterie,
  dans les deux gravités, et deux contrôles sans observation active. Elle
  refuse les cas hors `train`. Le chargement interdit la partition `test` ;
  la vérification d'intégrité du corpus peut lire ses fichiers sans les
  employer pour entraîner ou mesurer le diagnostic.
- Les deux recettes partent d'une copie identique des paramètres, dont
  l'empreinte est contrôlée, avec même réseau, optimiseur, batch et objectif.
  La seule différence prévue entre `uniform` et `hot` est le tirage temporel.
  Chaque cas garde une masse de probabilité égale. La recette `hot` mélange
  des temps uniformes et le quartile chaud supérieur ; chaque instant après
  `t = 0` conserve une probabilité strictement positive.
- Les cibles ne sont employées que pour l'apprentissage, son tirage et les
  métriques. Le cache ne change ni coordonnées ni grille, et refuse les
  formes hétérogènes. Les entrées restent celles de `input_tensor`.
- `peak_alignment` compare la température au lieu **et** à l'instant du pic
  réellement observé, mesure les déplacements et le retard du pic prédit,
  et exclut les valeurs absentes et `t = 0`. Le maximum global FDS n'est
  jamais substitué à une cible de voxel. Les déplacements sur champs plats
  sont explicitement signalés comme non informatifs.
- Les métriques héritées conservent les erreurs physiques, détections et
  faux positifs par cas sur les trajectoires complètes. Elles permettent
  de contrôler une éventuelle nappe chaude artificielle sur les cas froids.
- Le runner exige CUDA, applique le plafond de l'allocateur hérité, refuse
  d'écraser un dossier de preuves et exige le fichier `PAUSE` du corpus
  historique ainsi que le verrou de calcul. Il publie uniquement ses
  artefacts de diagnostic. Les neuf sources gelées correspondent toujours
  aux empreintes du modèle précédent.
- Les tests lus vérifient la conservation des temps calmes et de la masse
  par cas, le refus de cibles validation/test, l'ancrage au bon point avec
  gradients, les masques manquants et la détection d'un pic prédit au mauvais
  lieu/instant. Ils n'établissent aucune précision du modèle.

### Réserves transmises avant lancement

1. **Nombre de mises à jour.** Le docstring annonce le même nombre de mises
   à jour, mais une échéance par recette peut interrompre chacune à des
   étapes différentes. Le rapport enregistre effectivement `steps`. Si les
   nombres finaux diffèrent, les résultats ne constituent pas une ablation
   contrôlée à budget de mises à jour égal ; comparer à une étape commune
   avec un état sauvegardé, ou qualifier cette limite. Les évaluations et
   sauvegardes après la boucle peuvent aussi dépasser l'échéance de phase :
   le budget global doit rester surveillé par le processus responsable.
2. **Recette optionnelle `hot_peak`.** Son ancrage agit sur le pic de chacun
   des deux champs actifs, température **et** fumée, dans l'espace transformé.
   Il ne constitue donc pas une correction thermique isolée. Cette recette
   n'est pas requise pour la comparaison initiale `uniform`/`hot`. Si elle
   est ensuite essayée, il faut en tenir compte au regard de la domination
   des gradients fumée observée dans le diagnostic précédent.
3. **Portée statistique.** Une graine et un sous-ensemble choisi pour ses pics
   servent à vérifier l'aptitude à apprendre les observations connues. Ils
   ne mesurent pas la généralisation. Le mode déterministe avec avertissement
   conserve une variabilité possible du backward trilinéaire CUDA, ce que le
   rapport indique correctement.

### Version relue

| Élément | SHA-256 |
| --- | --- |
| `tools/remote/hotspot_spatial.py` | `9883455a8714bafd7fe27f0e97dfd4adcfa7abf0a3fbf3a49f8ccb2177961698` |
| `tests/test_hotspot_spatial.py` | `0264f9b7092be1ff306a22aaebcac2f08d4af35f8c8344cfcfe9c14c5680e63a` |

La revue de cette version ne couvre pas les résultats d'un futur calcul,
ni une éventuelle extension d'entraînement ou modification du runner.

## Revue de l'extension d'entraînement, 14 novembre 2026 à 20:26 UTC

Périmètre : lecture complète de `fit_hotspot_spatial.py` et de
`tests/test_hotspot_fit.py`, relecture de l'isolation dans `CaseStore`, puis
calculs légers sur les rapports JSON du diagnostic terminé. Aucun accès
Windows, apprentissage ou exécution supplémentaire de tests par cette revue.

**Aucun blocage identifié pour l'essai annoncé : recette `hot`, 120 cas
train, 40 cas validation, jusqu'à 20 000 mises à jour dans une enveloppe
annoncée de 900 s.** Cela autorise méthodologiquement un essai de développement,
pas une déclaration de généralisation ou une publication du modèle.

### Isolation, sélection et exports

- `fit_cases` exige l'identité `spatial-compact-v1`, la grille exacte
  `12 × 16 × 8` et les comptes 120/40. Le snapshot du diagnostic contient
  60 dispositions train, 20 validation et 20 test. Le contrôle hérité
  `CaseStore` interdit le partage d'identifiants de disposition, de famille
  structurelle et de signatures géométriques entre partitions.
- Seuls les cas train alimentent `DeviceCache` et le tirage favorisant les
  instants chauds. La validation est chargée pour les métriques. L'ancien
  test est vérifié pour son intégrité par `CaseStore.verify`, mais aucun
  chemin du runner ne le passe à une métrique ou à l'optimisation.
- `validation_assessment` refuse explicitement des cas train ou test. Le
  checkpoint minimise la métrique existante
  `localization_selection_error`, dont la valeur doit être finie. La même
  règle s'applique à chaque évaluation ; les pertes d'entraînement ne
  choisissent pas directement le checkpoint.
- Le modèle repart d'une initialisation neuve. Les meilleurs checkpoints
  intermédiaires sont enregistrés exclusivement, puis le meilleur état est
  rechargé avant les métriques finales train/validation et leurs figures.
  L'évaluation doit conserver l'empreinte des poids. Le fichier final est
  relu dans un nouveau réseau avec vérification d'identité exacte de l'état.
- Les exports restent des artefacts hors ligne ; aucun appel à `publish`
  ni changement de modèle actif. Un dossier préexistant ou une sortie sous
  le corpus source est refusé. Les empreintes des sources et du manifeste
  source sont revérifiées en fin d'exécution.
- Le verrou de calcul et le maintien du fichier `PAUSE` sont requis. La
  boucle réserve jusqu'à 120 s aux mesures et exports finaux. Cette marge
  n'est pas une borne dure : le rapport indique explicitement le temps réel
  et tout dépassement. Le budget global de la campagne doit comptabiliser
  les 143,31 s du diagnostic précédent et les autres phases éventuelles.

Les dix cas de test ciblés, dénombrés avec leurs paramètres, couvrent la
sélection des partitions, le refus de validation sur train/test, la métrique
de sélection, l'ancrage optionnel, les écritures exclusives/rechargement,
les bornes CLI et le refus d'exporter sous le dataset. Ils sont lus ici ;
leur exécution est laissée au responsable de l'entraînement.

L'entraînement étendu change également le corpus utilisé (120 cas compacts
au lieu de 170 cas de plusieurs sources pour le modèle précédent), le tirage
des batches et le nombre de mises à jour. Une différence avec l'ancien modèle
ne pourra pas être attribuée au seul tirage chaud. Le petit A/B ci-dessous
est la seule comparaison qui isole cette modification dans le présent essai.

### Résultats du diagnostic A/B effectivement vérifiés

Le rapport confirme **3 000 mises à jour pour chaque recette**, batch 32,
largeur 24, même état initial
`d55fdd783ee55badcc11a6c3bca0e4f5349454e1d0d5c442432510a3af3d3b8f`.
L'enveloppe complète a pris **143,31 s**, sur RTX 4070 Ti ; les deux boucles
et leurs métriques finales sont déclarées à 57,51 s et 54,88 s. Les dix
empreintes de sources du rapport correspondent aux fichiers locaux relus,
y compris les neuf sources historiques gelées. La réserve initiale sur
des nombres de mises à jour différents ne s'est donc pas réalisée ici.

Température prédite au lieu **et** à l'instant du véritable pic échantillonné :

| Cas microgravité connu | Pic FDS échantillonné | `uniform` | `hot` |
| --- | ---: | ---: | ---: |
| Surchauffe, disposition 0003 | 372,06 °C | 258,10 °C | 342,61 °C |
| Flamme, disposition 0029 | 190,04 °C | 187,17 °C | 191,56 °C |
| Batterie, disposition 0099 | 49,68 °C | 46,70 °C | 49,88 °C |

Pour `hot`, le pic spatial coïncide avec le point observé sur ces trois cas.
Le premier conserve un retard du maximum global prédit de 0,78 s. Les deux
contrôles froids ont zéro faux positif chaleur et fumée pour les deux recettes.
Il existe donc une amélioration observée de l'ajustement des pics connus,
sans nappe chaude détectée sur ces deux contrôles. Ce résultat ne signifie
pas que tous les champs s'améliorent :

| Mesure sur les huit cas connus | `uniform` | `hot` |
| --- | ---: | ---: |
| Rappel chaleur, 904 observations actives | 87,17 % | 73,67 % |
| Précision chaleur | 63,29 % | 72,95 % |
| IoU chaleur | 57,90 % | 57,86 % |
| Rappel fumée, 16 530 observations actives | 98,31 % | 98,28 % |
| Précision fumée | 84,48 % | 77,20 % |
| IoU fumée | 83,27 % | 76,17 % |

En microgravité seule, parmi 242 observations chaudes et 626 observations
enfumées, l'IoU chaleur passe de 82,59 % à 83,87 %, tandis que l'IoU fumée
passe de 74,38 % à 69,23 %. Le rappel chaud passe de 100 % à 96,69 %. Ces
dénominateurs sont des points/instants corrélés issus de quatre cas, dont
un contrôle ; ce ne sont pas des essais indépendants ni des taux de sûreté.

La conclusion admissible est donc le passage d'une porte d'apprentissage
des pics, avec un compromis sur les régions chaudes et enfumées. Une seule
graine et le déterminisme CUDA incomplet limitent encore la portée du A/B.
La prochaine évaluation doit vérifier ce compromis sur validation, puis sur
des dispositions réellement nouvelles avant toute revendication générale.

### Empreintes de cette revue

| Élément | SHA-256 |
| --- | --- |
| `tools/remote/fit_hotspot_spatial.py` | `49297272e6e161a96339b8c0eea8728149301f73ff9d5fdaafcba7bca177a9eb` |
| `tests/test_hotspot_fit.py` | `d25d3165557e4d41731f1b80c3e91d3d9135de1261334747bc9447bd6d70457e` |
| `diagnostic/report.json` | `21a0999a30a32b000cac3d67e472d0bd2490da37aaf0b869b65200037ba5fe73` |
| `diagnostic/dataset-snapshot.json` | `928acebaa9d43de013b76b60ab2809c0b6f7e535a0aa3fed839f3f3fd12a2651` |
| `diagnostic/sources.json` | `64cfbd1e9b4638bd29dcdd91a7ddb6c786e01724f84f9f91e16d62717139c646` |

Cette section ne préjuge pas du résultat de l'entraînement étendu, qui n'est
pas encore audité à la date indiquée.

## Revue du test prospectif, 14 novembre 2026 à 20:35 UTC

Lecture seule de `evaluate_hotspots.py`, de ses tests et du fichier
`prospective-membership.json`, sans génération, inférence ou accès Windows.
Les signatures des sources historiques restent identiques. Les commentaires
ci-dessous précèdent les nouvelles simulations et leurs résultats.

**Pas de blocage dans la logique d'évaluation relue. Deux preuves de protocole
complémentaires restent nécessaires : le gel des modèles avant la génération
et l'absence de recoupement avec les géométries historiques hors corpus compact.**
Ces points ont été transmis au responsable de la campagne avant son lancement.

### Ensemble de test et séparation

Le JSON gelé contient exactement 100 identifiants distincts sur les 50
dispositions `procedural-0100` à `procedural-0149`, deux cas par disposition.
Ses labels natifs comptent 60 train, 20 validation et 20 test. Dans ce protocole,
**les 100 cas sont tous des cas de test prospectif** : les labels natifs
conservent seulement les strates de familles du générateur. Aucun d'eux ne
sert à l'entraînement ou à choisir un checkpoint dans l'évaluateur.

Le runner exige les 300 cas complets, vérifie exactement les identifiants,
empreintes, partitions natives et le hash du plan gelé. Il refuse donc une
évaluation opportuniste des seuls cas ayant fini rapidement. Après le contrôle
hérité du compilateur et des observations, il exige 50 géométries nouvelles
distinctes et disjointes des 100 premières géométries du corpus compact, les
deux gravités 0,0001 et 1 sur chaque nouvelle disposition, ainsi que 20 cas
pour chacun des cinq types d'incident.

Le contrôle `CaseStore.verify` lit aussi les anciens cas, dont l'ancien test,
pour vérifier fichiers, compilation et géométrie. En revanche, la liste
passée à `aligned_assessment` est exclusivement celle des 100 identités
prospectives gelées : aucune ancienne cible de test n'est utilisée comme
métrique ou signal d'ajustement par ce runner.

Le modèle historique comparé a été entraîné sur 170 cas et 66 géométries,
dont **six géométries du pilote `incidents-v1` absentes du compact**. Les
quatre géométries du corpus historique `spatial-corpus-v1` sont déjà couvertes
par le compact. Le contrôle automatique actuel ne compare pas les nouveaux
cas aux six géométries supplémentaires. Il faut compléter la comparaison
des signatures avec le snapshot historique, idéalement ses douze géométries
pilotes connues, avant de qualifier les nouveaux cas d'inédits pour les deux
modèles. Cela se vérifie à partir des métadonnées, sans consulter les anciens
résultats de test. Aucun recoupement n'est établi à ce stade ; les nouvelles
signatures ne sont pas encore disponibles dans les preuves locales.

### Poids, métriques et délai

- Le runner charge un à trois checkpoints explicitement nommés et une
  référence analytique à température ambiante. Il vérifie le schéma des
  caractéristiques, l'architecture, la finitude et l'identité exacte des
  poids, puis désactive leurs gradients et active le mode inférence. Aucun
  optimiseur ni sélection de modèle n'est appelé.
- Il contrôle les fichiers de poids avant et après l'évaluation, leur état
  en mémoire, puis leur rechargement exact sur CPU. Ces contrôles prouvent
  l'immutabilité pendant la comparaison ; **ils ne prouvent pas à eux seuls
  que le choix des poids précède la génération FDS**. Une preuve séparée,
  horodatée, doit donc fixer chemins et SHA-256 des candidats avant FDS. Toute
  décision d'essayer `hot_peak` doit provenir des seuls train/validation et
  précéder ce gel.
- Les métriques, diagnostics, pics, arrivées lorsqu'elles sont présentes et
  figures doivent correspondre exactement aux identifiants gelés. Les
  identités de dispositions sont également contrôlées dans les lignes de
  métriques. Les résumés sont calculés par strate native, par gravité et par
  croisement strate/gravité ; les métriques héritées ajoutent les groupes par
  type d'incident et les lignes par cas.
- L'erreur d'amplitude, la distance et le retard du pic sont moyennés d'abord
  par disposition, uniquement parmi les cas dont la vérité possède un pic
  chaud. Les nombres de cas et dispositions concernés sont exposés ; une
  strate sans pic chaud fournit `null`, jamais une erreur artificiellement
  nulle. Les classifications gardent leurs dénominateurs de points/instants,
  qui restent corrélés. La localisation d'un maximum sur la référence
  ambiante plate demeure non informative.
- L'échéance, au maximum 180 s, est contrôlée pendant la vérification du
  corpus, avant chaque batch CUDA et aux frontières de phases. Une opération
  CPU ou une écriture en cours n'est pas préemptée instantanément. Si la
  limite est atteinte, des preuves partielles peuvent subsister, mais aucun
  rapport final `completed: true` ne doit être émis. Le test de délai lu
  couvre explicitement cette interruption avant inférence.
- Les tests lus couvrent notamment le gel sans modification du plan, les
  variations d'identité/fingerprint/partition, les cas manquants, la
  duplication géométrique sous un nouveau nom, les agrégations, les poids
  incompatibles/non finis, les sorties exclusives et le délai. Leur résultat
  d'exécution n'est pas reproduit par cette revue.

### Version relue

| Élément | SHA-256 |
| --- | --- |
| `tools/remote/evaluate_hotspots.py` | `c46048dc472ff705b676d8f94c4a11ce551238d5ee68b65b5c64f9827d21f338` |
| `tests/test_hotspot_evaluation.py` | `ce4bdd5409313d54b59a25b3da9fe14b3b3e076608d866b038347491e7eca3ef` |
| `prospective-membership.json` | `67288b3073cfc2acb2514a65a3bf6c75beb40bc6c5bdb81bbe0533d067e09bcf` |

Le hash de plan contenu dans ce membership est
`a4bae632290b17abb758899f3181fd7ac73d7fa9449be5980a2bb21ade4142a0`.
La présente revue ne constitue pas une vérification des résultats futurs.
