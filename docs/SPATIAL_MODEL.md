# Réseau spatial 3D et apprentissage CUDA

Le modèle spatial-pilot-v1 teste la chaîne d’apprentissage sur les 60 simulations
FDS du pilote, à leurs 8×10×4 positions réelles. spatial-corpus-v1 est réservé au
corpus procédural à 12×16×8 positions. Les identifiants séparent les preuves ;
aucune performance sur un petit pilote ne démontre la généralisation aux habitats.

Avant apprentissage, l’identifiant est lié strictement au dataset et à sa grille :
spatial-pilot-v1 exige incidents-v1 en 8×10×4 ; spatial-corpus-v1 exige
spatial-corpus-v1 en 12×16×8. Sans --dataset, la CLI choisit le répertoire du
dataset correspondant sous datasets/. Une autre association est refusée.

Le U-Net 3D contient 834 486 paramètres, avec des largeurs 24/48/96. Il prédit
directement température et suie à un instant conditionné, ainsi que quatre
statistiques FDS indépendantes. Il reçoit 54 canaux : positions normalisées,
masque de gaz, fractions géométriques des solides, matériaux et revêtements,
densité/Cp/conductivité/émissivité et paramètres combustibles du substrat,
épaisseur, patch et distance à la source, limites de ventilation vectorielles,
dimensions, temps, profil de source, gravité, oxygène, pression et ambiance.

Les petits solides sont représentés par leur intersection avec le support des
échantillons, même sans point placé à l’intérieur. Ce codage fractionnaire des
propriétés n’est pas une loi de mélange physique. Les revêtements sont encodés
par catégorie et épaisseur. La ventilation est une condition de frontière :
aucun champ de vitesse n’est prédit. Son signe est déduit du plan de frontière
et de la convention FDS VOLUME_FLOW, pas de la normale descriptive du modèle 3D.

L’ordre cartésien x,y,z avec z rapide est vérifié avant reshape. Les coordonnées
FDS, parfois non uniformément espacées, sont conservées ; les convolutions
opèrent sur leur grille d’indices. Les dimensions sont complétées jusqu’au
multiple de quatre puis les sorties recoupées ; aucune cible n’est interpolée.

## Statut mesuré du pilote hors interface

Le 14 novembre 2026, le pilote a réellement été entraîné sur la NVIDIA GeForce
RTX 4070 Ti du PC Windows : 20 époques en 118,2 s, époque 19 retenue sur
validation, minibatch de 4. Le premier pas CUDA synchronisé est horodaté à
16:10:29,752 UTC dans le [journal](../evidence/incidents/spatial-pilot/training.jsonl).
Les pics de l’allocateur PyTorch sont 34 106 368 octets alloués et 41 943 040
réservés ; ils excluent le contexte CUDA et les bibliothèques.

Les erreurs du test, équilibrées par disposition puis par cas, sont publiées
dans l’[évaluation](../evidence/incidents/spatial-pilot/evaluation.json) et les
[métadonnées](../evidence/incidents/spatial-pilot/metadata.json) :

| Métrique — plus faible est meilleur | Réseau | Référence ambiante |
| --- | ---: | ---: |
| Critère composite encodé | 0,3785 | 0,4501 |
| MAE du champ de température (°C) | 0,1184 | 0,0171 |
| MAE de température en région chaude (°C) | 5,9349 | 6,0496 |
| MAE du champ de suie (kg/m³) | 8,523 × 10⁻⁸ | 3,477 × 10⁻⁸ |
| MAE du dégagement de chaleur global (W) | 161,25 | 91,21 |

Le gain du critère composite ne compense pas les régressions de température,
suie et dégagement de chaleur moyens. Le modèle reste hors interface : ce
pilote démontre le fonctionnement de la chaîne GPU, avec une qualité encore
insuffisante. Il ne constitue pas un entraînement du grand corpus ni une preuve
de généralisation physique.

## Mémoire, provenance et partitions

Le lecteur charge un cas NPZ à la fois, ou le result.json historique du pilote.
Le cache LRU garde deux cas. Les minibatches contiennent 2–8 instants ; la limite
par défaut est 20 000 instants d’entraînement par époque, avec un budget équilibré
par disposition puis par cas. Les instants retenus changent à chaque époque.
Validation et test sont évalués intégralement, sans sous-échantillonnage.

Les fichiers, configurations, géométries compilées et provenances sont vérifiés
avant apprentissage. Les dispositions physiques restent séparées entre train,
validation et test, même si leurs noms changent. La partition crossflow du
pilote reste au test. L’option --allow-incomplete autorise explicitement un
instantané des seuls cas achevés d’une campagne en cours. Les IDs, partitions
et empreintes sont figés dans dataset-snapshot.json avec une empreinte canonique
distincte de celle du manifeste source.

CUDA est obligatoire. L’allocateur PyTorch est plafonné à environ 5 Gio ; le
contexte CUDA et les bibliothèques ont une consommation additionnelle. Les
données du corpus restent en RAM hôte, cas par cas. GPU réellement utilisé,
versions CUDA/PyTorch et pics alloués/réservés sont enregistrés. L’inférence
SpatialSurrogate.predict_arrays utilise le CPU par défaut. Cette première
version n’est pas activée automatiquement dans l’interface.

## Apprentissage et erreurs publiées

Les cibles utilisent asinh avec des échelles physiques fixes. La perte SmoothL1
masque les solides et chaque mesure absente ; elle pondère 1+4 les observations
d’entraînement actives (température ≥ ambiance+5 °C ou suie ≥ 10⁻⁷ kg/m³). Les
cibles validation/test ne fournissent aucune pondération d’entraînement.
La tête globale pèse 0,25 dans la perte. AdamW, clipping de gradient et arrêt
anticipé sur validation limitent l’entraînement à 20 époques par défaut.

Le critère de sélection est la moyenne par disposition puis par cas des erreurs
absolues encodées : champ + 0,5 région chaude + 0,5 région avec suie + 0,25
statistiques globales. Une région absente ne contribue pas à ce critère et ses
métriques sont null, jamais une fausse erreur nulle. Cela s’applique également
aux moyennes et pics d’un canal entièrement absent : seules les observations
disponibles contribuent au critère. Le test n’est mesuré qu’une
fois après restauration des poids choisis. Les erreurs physiques moyennes,
régions actives et pics sont publiées, globalement et par famille, avec une
référence ambiance constante/suie nulle/HRR nulle. Un modèle moins bon que cette
référence est signalé ; l’existence d’un entraînement ne suffit pas à le valider.

Le premier état est imposé à ambiance/suie nulle. L’inverse asinh est borné, les
températures prédites limitées à [-20,2500] °C et suie/HRR à des valeurs positives
ou nulles ; ces post-traitements ne modifient jamais les observations de test.
Les sorties température/suie sont des valeurs de gaz échantillonnées. Les quatre
statistiques FDS apprises indépendamment ne sont pas confondues avec leur moyenne.

## Exécution sur le PC Windows

Depuis l’application installée, avec le Python du venv CUDA existant :

    python tools/remote/train_spatial.py --home E:/IGNIS-Valley-dev --dataset E:/IGNIS-Valley-dev/datasets/incidents-v1 --model-id spatial-pilot-v1 --epochs 20 --batch-size 4

La CLI prend le verrou runtime/compute.lock. La fonction train() ne reprend pas
ce verrou afin de permettre une orchestration externe sans verrou imbriqué.
Aucun entraînement réel n’est exécuté sur le VPS. Les tests CPU utilisent
seulement des tenseurs et données synthétiques minuscules pour les contrats.

Le journal JSONL est créé exclusivement dans runtime/training. L’événement
cuda_available annonce seulement la disponibilité ; cuda_training_started
est émis après le premier vrai forward/backward/pas d’optimisation synchronisé.
Il sert de preuve du démarrage GPU, avec son horodatage UTC.

La publication écrit poids, métadonnées, évaluation et instantané dans un nouveau
répertoire temporaire puis renomme l’ensemble. Elle refuse toute version déjà
présente. Les poids sont hachés puis chargés avec torch.load(weights_only=True).
Un échec conserve les fichiers partiels pour inspection et ne remplace pas un
modèle existant.

Les prochains entraînements enregistrent, dès leur démarrage, les SHA-256 des
six sources utilisées : script d’entraînement, réseau, lecteur de dataset,
compilateur, incidents et matériaux. Les clés sont relatives à la racine du
code ; les modules importés doivent provenir de cette même copie. Les arguments
effectifs, l’interpréteur et la commande CLI lorsqu’elle existe accompagnent ces
empreintes dans les métadonnées et le journal. Le pilote historique présenté
plus haut reste inchangé et ne possède pas ces empreintes source.

Il s’agit d’un substitut des hypothèses exploratoires FDS, pas d’observations
NASA ni d’une probabilité de panne électrique, d’une simulation électrochimique
de batterie ou d’une certification de sécurité.

## Vérification indépendante de l’inférence et test élargi

Le 14 novembre 2026, les poids sauvegardés ont été rechargés sur CUDA et les
15 cas de test historiques rejoués en 0,404 s d’inférence cumulée. Les erreurs
publiées sont reproduites ; les poids, données et partitions sont inchangés.
Ce contrôle de reproductibilité ne constitue pas un nouveau test indépendant.

Un second contrôle a produit **60 nouvelles simulations FDS** : 30 cas dans
trois dispositions similaires avec nouvelles conditions, puis 30 cas dans trois
géométries inédites. Quatre solveurs CPU mono-thread ont terminé en 477,27 s ;
l’inférence sur RTX 4070 Ti a pris 4,41 s cumulées. Aucun entraînement.
Le modèle ne détecte aucun point chaud au seuil ambiance + 5 °C et seulement
20–21 % de ses alertes de fumée sont correctes. Il reste hors interface.
Le [rapport de pertinence et ses comparaisons 3D](../evidence/incidents/spatial-pilot/expanded-audit/README.md)
documentent les métriques, limites, empreintes et sorties de chaque cas.

Le plan facultatif `compact_spatial_design.build_design(source_hashes, layout_count)`
prépare 2 cas par disposition, avec un nombre de dispositions multiple de 50,
jusqu’à 1 000. Son défaut de 200 dispositions donne 400 cas. Il sélectionne des
cas exactement identiques au plan initial pour permettre une réutilisation
ultérieure après vérification. L’identité `spatial-compact-v1` exige ce dataset
et une grille 12×16×8 ; elle ne remplace aucun modèle existant. Le plan est testé,
et exécuté par `generate_compact_spatial.py`. Le premier lot de 100 cas sur
50 dispositions, puis son extension à 200 cas sur 100 dispositions sont terminés ;
192 cas ont été simulés et 8 réutilisés du corpus initial. Les deux lots sont
conservés séparément. Les preuves de la reprise sont conservées dans
[spatial-recovery](../evidence/incidents/spatial-recovery/). Cette génération
n'active aucun modèle dans l'interface.

## Reprise bornée et modèle `spatial-recovery-v1`

`recover_spatial.py` conserve l'architecture et les cibles physiques, avec un
apprentissage neuf sur le compact complet et les seules partitions **train**
des deux jeux historiques. Les doublons exacts sont retirés et les signatures
géométriques ne peuvent traverser les partitions. Les familles structurelles
du compact restent séparées : six pour apprendre, deux pour choisir les poids,
deux pour le test final. L'audit historique de 60 cas est un diagnostic de
développement distinct ; il n'est jamais ajouté à l'entraînement.

Les cibles et canaux statiques de ce lot borné sont conservés en RAM hôte.
Les entrées complètes sont construites par minibatches de huit instants ; seize
instants par cas sont tirés à chaque époque. Chaque disposition reçoit le même
poids total. Les grilles historiques 8×10×4 et procédurales 12×16×8 sont traitées
séparément, sans interpolation de labels. Seul `spatial-recovery-v1` accepte la
liste explicite `supported_sample_shapes` enregistrée dans ses métadonnées ;
les contrats de grille des anciens modèles restent stricts.

Trois objectifs sont disponibles pour les diagnostics : historique, équilibré
par région, et `localized`. Ce dernier ajoute à la régression historique
0,25 fois une perte de support spatial Tversky/BCE. Les seuils restent ambiance
+5 °C et 10⁻⁷ kg/m³ ; ils servent au diagnostic et ne sont pas des seuils de
danger. La sigmoïde interne n'est pas une probabilité calibrée d'incendie.
La [recherche et les ablations](SPATIAL_RESEARCH.md) expliquent les choix.

La sélection utilise le composite encodé historique, plus
`0,5 × (1 − IoU_chaleur) + 0,5 × (1 − IoU_fumée)`, moyenné par cas puis
disposition. Une union vide a une IoU de 1 pour cette sélection. Le taux
d'apprentissage diminue après cinq évaluations sans amélioration, et l'arrêt
anticipé intervient après vingt époques sans nouveau meilleur score. Le test
est évalué seulement après sélection et rechargement des meilleurs poids.

L'heure d'arrivée de fumée est le premier franchissement **échantillonné** du
seuil, sur les points observés pendant tout l'horizon. Son erreur est calculée
seulement lorsque simulation et prédiction franchissent le seuil. Les arrivées
manquées, fausses arrivées et absences dans l'horizon sont comptées séparément :
l'absence de franchissement reste censurée et n'est pas remplacée par 30 s.

Le générateur compact utilise quatre solveurs FDS CPU mono-thread sous un même
verrou de calcul. `--reuse-compact` copie et vérifie les cas d'un lot complet
sans recalcul ni lien vers les fichiers sources. Le budget interrompt les
solveurs au terme prévu, puis termine l'archivage ; cet éventuel dépassement
est enregistré. Le trainer refuse un compact incomplet, exige CUDA et réserve
120 s de son budget à l'évaluation et à la sauvegarde. Il publie dans un nouveau
répertoire, refuse de remplacer une version existante et vérifie le résultat
après rechargement par le chargeur public. Aucune activation UI automatique.

### Résultat final du 14 novembre 2026

L'essai a consommé 44 min 58 s de phases de calcul, 50 min 55 s avec les
intervalles entre processus. L'entraînement final neuf sur RTX 4070 Ti a pris
452,40 s, évaluation et publication comprises : 52 époques, époque 32 retenue
sur validation. Les ablations équilibrée et `localized` ont été rejetées ;
l'objectif final est la perte historique. La sélection inclut les IoU comme
décrit ci-dessus, sans adaptation au test.

Apprentissage effectif : 170 cas / 66 dispositions (120 compact, 30 ancien
pilote et 20 ancien corpus après déduplication). Validation : 40 cas / 20
dispositions. Test réservé : 40 cas / 20 dispositions, familles `baffled` et
`double-island`. Le modèle figé a ensuite été relu sur les 60 diagnostics
historiques, sans nouvelle simulation, et reste hors interface.

| Test réservé | Rappel chaleur | Rappel fumée | Précision fumée |
| --- | ---: | ---: | ---: |
| Ensemble | 1,94 % | 87,09 % | 57,37 % |
| Terre | 0,042 % | 87,63 % | 61,11 % |
| Microgravité | 16,45 % | 71,99 % | 18,52 % |

Ces mesures portent sur les points × instants observés aux seuils exploratoires,
pas sur des incendies indépendants. La majorité des observations enfumées est
terrestre. La MAE globale de température, 0,178 °C, est moins bonne que la
référence ambiante (0,113 °C) ; celle des pics, 33,71 °C, ne s'améliore que
faiblement (référence 35,86 °C). Le réseau reste proche de l'ambiance sur certains
pics de plusieurs centaines de degrés. Il n'est pas validé pour une carte de
risque ou une géométrie arbitraire.

Le [bilan et les figures](../evidence/incidents/spatial-recovery/README.md)
détaillent arrivée de fumée, faux positifs, erreurs physiques, relecture
avant/après, limites et registre exact du calcul. Les sources entraînées et le
modèle restent figés ; ce test désormais consulté ne sert pas à ajuster les poids.
