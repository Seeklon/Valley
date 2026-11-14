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
