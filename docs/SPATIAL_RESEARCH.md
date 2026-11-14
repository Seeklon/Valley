# Choix du modèle spatial et protocole de généralisation

Recherche effectuée le **14 novembre 2026**, pour un essai borné à une heure de
calcul sur Ryzen 3700X, 16 Go de RAM et RTX 4070 Ti de 12 Go. Ce document sépare
les résultats existants, les publications consultées et les recommandations.
Le [bilan final mesuré](../evidence/incidents/spatial-recovery/README.md) accompagne
cette recherche : essai terminé en 50 min 55 s écoulées, modèle non activé.

## Décision

La décision initiale de l'essai était de conserver le **petit U-Net 3D conditionné
par la scène et le temps**, vérifier son apprentissage, puis augmenter la diversité
des scènes. Un réseau plus grand n'est pas aujourd'hui la priorité démontrée.
Le modèle existant est déjà du deep learning spatial : il traite des volumes
avec convolutions 3D et reçoit géométrie, matériaux, source et conditions.

Le résultat visé est un **substitut de FDS pour les conséquences d'un incident
supposé**, dans un domaine explicite de scènes et de conditions. Il ne prédit
pas la probabilité qu'un équipement réel tombe en panne. Pour choisir un point
sensible avant un incident, on peut comparer les conséquences prévues de
départs hypothétiques à plusieurs composants. Un classement de conséquences
n'est pas une fréquence d'incendie.

## Ce que les preuves du dépôt montrent

L'[audit de 60 cas nouveaux](../evidence/incidents/spatial-pilot/expanded-audit/README.md)
ne détecte aucun point chaud au seuil exploratoire ambiance + 5 °C ; la précision
des alertes de fumée est proche de 20 %. Le modèle reste presque à température
ambiante, y compris sur les configurations similaires. Le problème n'est donc
pas seulement l'extrapolation vers des géométries nouvelles.

Le code examiné avant le nouvel essai utilise 834 486 paramètres, 54 canaux et
une prédiction directe à chaque temps. La grille du pilote est 8 × 10 × 4 ;
le corpus procédural prévu utilise 12 × 16 × 8. Ce sont les points de mesure
de FDS, pas tous ses volumes de calcul. Aucun réseau ne peut récupérer des
foyers absents des cibles échantillonnées sans une autre source de supervision.

Dans `train_spatial.py`, les observations actives sont déjà pondérées par cinq.
Dans `spatial_network.masked_loss`, leur somme reste divisée par la somme des
poids de toutes les observations. À titre illustratif, si 0,1 % des points sont
actifs, ils représentent environ 0,5 % de la masse de pondération :
`5p / (1 + 4p)`. Cela ne détermine pas leur contribution finale, qui dépend aussi
de l'amplitude de leurs erreurs, mais motive un essai d'équilibrage explicite.

Le score de sélection sur validation tient **déjà** compte de l'erreur dans les
régions chaudes et enfumées, en plus de l'erreur globale. Il serait inexact
d'attribuer l'échec à une sélection fondée exclusivement sur la MAE de tout le
volume. La perte d'entraînement et le score de sélection ne sont cependant pas
identiques. La rareté des foyers, le nombre de cas, le sous-échantillonnage et
l'optimisation restent des hypothèses à départager.

Sources locales : [réseau](../backend/ignis/ml/spatial_network.py),
[entraîneur](../tools/remote/train_spatial.py),
[contrat spatial](SPATIAL_MODEL.md),
[limites des sources et matériaux](INCIDENT_PHYSICS.md).

## Comparaison des familles de modèles

| Méthode | Ce que la source primaire établit | Choix pour IGNIS |
| --- | --- | --- |
| **U-Net 3D** | Çiçek et al. introduisent les convolutions et connexions U-Net en volume pour la segmentation ; ce travail ne valide pas la combustion. | Garder comme premier modèle : implémentation et mesures CUDA existent, contexte spatial multirésolution, peu de modifications nécessaires. Le succès doit être mesuré sur nos champs physiques. [Article, 21 juin 2016](https://arxiv.org/abs/1606.06650). |
| **FNO** | Li et al. apprennent des opérateurs en espace de Fourier et évaluent Burgers, Darcy et Navier–Stokes. | Candidat de comparaison ultérieur sur grille régulière ; les interactions globales sont intéressantes, mais l'article ne prouve pas une généralisation à nos obstacles, matériaux et sources. Ne résout pas une cible absente ou une perte dominée par le fond. [Article, version du 17 mai 2021](https://arxiv.org/abs/2010.08895). |
| **GINO** | Combine nuage de points, distance signée, opérations de graphe et FNO ; évalué sur des pressions de surface en aérodynamique automobile. | Option future pertinente si l'on veut interroger des maillages Blender variés. Représentation, recherche de voisinages et supervision doivent être adaptées. Sa convergence en discrétisation ne garantit pas une extrapolation vers une physique ou des matériaux nouveaux. [Article, 1er septembre 2023](https://arxiv.org/html/2309.00583v1). |
| **MeshGraphNets** | Apprentissage de dynamiques par messages sur un graphe de maillage ; expériences en aérodynamique, mécanique et tissu. | Intéressant pour un maillage non structuré et des interactions locales. Le modèle actuel supervise T/suie sur une grille cartésienne ; les composantes U/V/W sont conservées dans les archives FDS mais pas dans ses cibles NPZ. Changer le réseau demanderait aussi une nouvelle préparation des données. [Article ICLR 2021, version du 18 juin 2021](https://arxiv.org/abs/2010.03409). |
| **Modèle par point : MLP ou arbres** | Référence d'ingénierie simple, à comparer sur les mêmes partitions ; pas une preuve issue d'un article particulier. | Utile comme témoin économique à partir de distance source, temps, conditions et descripteurs locaux. Une entrée purement locale ne distingue pas deux pièces identiques près du point mais dont un obstacle éloigné détourne le flux. Il faut un contexte géométrique pour couvrir cet effet. |
| **Encodeur global + décodeur par coordonnées / DeepONet** | DeepONet sépare l'encodage d'une fonction d'entrée et celui des coordonnées de sortie. Les auteurs distinguent expressément approximation théorique, optimisation et généralisation. | Alternative si une grille fixe limite la résolution : encoder toute la scène puis interroger `(x,y,z,t)`. Ce n'est pas équivalent à un MLP n'utilisant que des informations locales. [Article, version du 15 avril 2020](https://arxiv.org/abs/1910.03193). |

Ces recommandations sont des décisions d'ingénierie pour notre budget et nos
données, pas le classement universel des architectures. Le benchmark
**PDEBench** compare notamment U-Net, FNO et PINN sur plusieurs équations et
propose une évaluation qui dépasse une seule erreur moyenne. Il fournit une
méthode de comparaison ; son jeu de données n'est pas un corpus de combustion
en microgravité. [Takamoto et al., NeurIPS 2022 ; version du 26 août 2024](https://arxiv.org/abs/2210.07182).

Une publication directement liée à FDS renforce l'intérêt de commencer avec un
U-Net : Panayis et al. rapportent un apprentissage sur 200 simulations et une
validation sur 50, pour les températures à un instant sur cinq niveaux d'un
**même bâtiment**. Leur entraînement est effectué sur A100. C'est une preuve de
faisabilité d'un substitut dans un domaine borné ; ni leur durée ni leur erreur
normalisée ne se transposent à notre GPU ou à des cabines inédites. Leur recherche
guidée de positions défavorables motive aussi une génération ciblée après le
premier lot, plutôt que la répétition uniforme de milliers de cas.
[Panayis et al., 30 septembre 2025, sections 3, 5 et 6](https://arxiv.org/html/2509.26139v1).

Un autre dépôt d'auteurs, **TunnelFire180**, documente des sorties de température
et de vitesse pour une coupe de tunnel avec une seule cellule transversale.
Ce jeu ne fournit pas des champs de suie 3D de cabines en microgravité. Il peut
servir à reproduire une étude de méthode ultérieure, mais ne doit pas être
ajouté aux étiquettes IGNIS comme s'il couvrait la même tâche. Le dépôt indique
que son code d'entraînement sera publié ultérieurement.
[Dépôt des auteurs, consulté le 14 novembre 2026](https://github.com/dtgaop/tunnelfiresurrogatemodelling).

## Expérience minimale pour réparer l'apprentissage

1. **Vérifier l'apprentissage sur un petit lot existant.** Choisir des trajectoires
   d'entraînement avec chaleur et fumée observées, plusieurs instants et les deux
   gravités. Faire volontairement sur-apprendre 4 à 8 cas. Vérifier les pics,
   leur position, les courbes temporelles et les régions actives. Un succès
   démontre une capacité d'ajustement, pas une généralisation.
2. **Comparer une seule correction de perte.** Pour chaque variable, calculer
   séparément la moyenne d'erreur sur points actifs et sur fond observé ;
   combiner leurs moyennes avec des coefficients explicites. Masquer solides et
   valeurs absentes, conserver la transformation physique et traiter les groupes
   vides sans division par zéro. Maintenir la pénalisation des faux positifs dans
   le fond. Ne pas supprimer tous les instants calmes.
3. **N'ajouter une tête de présence que si nécessaire.** Une classification
   auxiliaire chaud/fumée peut utiliser une perte pondérée ou focal loss, avec
   une régression des valeurs. C'est une ablation distincte, pas un changement
   gratuit à cumuler avec tout le reste. Une porte multiplicative dure peut
   masquer un foyer si le classifieur échoue ; mesurer les faux négatifs.
4. **Évaluer les champs physiques décodés.** Une baisse de perte transformée
   ne suffit pas ; mesurer les erreurs en °C et kg/m³, les pics et la localisation.

La **focal loss** originale répond au déséquilibre entre fond facile et objets
dans une classification dense. Son usage éventuel ici concerne une tête de
présence ; elle ne remplace pas directement une régression de température et
suie. L'analogie justifie une expérience, pas une garantie de correction.
[Lin et al., ICCV 2017 ; version du 7 février 2018](https://arxiv.org/abs/1708.02002).

Le mécanisme est de l'apprentissage supervisé : FDS fournit la cible et les
gradients corrigent l'écart. Le renforcement learning serait un autre problème,
par exemple apprendre une politique qui choisit une commande de ventilation
et reçoit une récompense selon les conséquences. Nous n'avons pas besoin d'un
tel mécanisme pour corriger la régression actuelle.

## Générer pour tester une généralisation définie

La taille brute d'un corpus ne suffit pas. Des milliers d'instants d'un même
incendie restent corrélés. L'unité d'indépendance utile est d'abord la scène et
son dispositif source/ventilation ; les deux gravités d'une paire restent dans
la même partition.

Le [plan compact](../tools/remote/compact_spatial_design.py) fournit une base :
familles structurelles séparées entre train/validation/test, cinq incidents
équilibrés et gravités appariées. Il faut enregistrer effectivement les nombres
par famille, source, matériau et régime de ventilation, pas seulement le nombre
de simulations terminées. Son défaut de 400 cas n'est pas une promesse de durée.

| Axe | Variation utile | Limite à conserver |
| --- | --- | --- |
| Géométrie | Taille/aspect de la pièce, passages, densité d'équipements, obstacle entre source et sortie. | Plusieurs scènes et familles entièrement réservées ; transformer une scène ne crée pas automatiquement une nouvelle famille indépendante. |
| Source | Position sur les composants, profil, puissance, durée et délai. | Le compilateur actuel limite la source à une face supérieure ; « tous les départs électriques » n'est pas couvert. |
| Matériaux | Distribution et épaisseur des matériaux du catalogue documenté. | PMMA/cellulose de démonstration et substrats inertes ne représentent pas tous les câbles et batteries réels. |
| Air | Orientation et position des évents, débit, cas faiblement ventilés. | Les vitesses d'évents en entrée ne sont pas le champ de vitesse interne. |
| Conditions | Paire Terre/microgravité, oxygène et autres plages réellement générées. | Une pression, ambiance ou durée maintenue constante définit une restriction du domaine, pas une capacité d'extrapolation. |
| Observation | Champs et instants proches de la source, croissance puis transport. | Une grille plus fine de rendu ne constitue pas davantage de supervision ; le maillage FDS et la grille de mesure doivent être documentés séparément. |

Le premier complément doit favoriser de nouvelles dispositions et des départs
placés différemment, avec des blocs équilibrés terminés. Un budget qui s'arrête
après les seules premières familles d'une liste peut produire un corpus biaisé.
Prévoir quelques cas calmes ou sans source pour mesurer les fausses alertes ;
ils ne doivent pas étouffer les cas actifs dans la fonction de perte.

La réutilisation évite du calcul uniquement si scènes, configurations, versions
du compilateur, coordonnées de mesure et empreintes correspondent. Les deux
grilles historiques ne sont pas interchangeables par simple changement de
forme. Toute interpolation éventuelle doit être explicitement validée, jamais
présentée comme une nouvelle mesure FDS.

Après le premier modèle, sélectionner les cas supplémentaires sur les erreurs
du **train/validation** et la couverture des paramètres : zones où il manque les
foyers, confond le fond et la fumée, ou réagit mal à un obstacle. Garder une part
de scènes tirées indépendamment pour ne pas apprendre seulement ses propres
cas difficiles. Le test final ne sert pas à sélectionner le prochain cas.

## Budget et décision à partir des mesures

Le précédent audit a terminé 60 simulations en 477,27 s avec quatre processus
CPU FDS indépendants. C'est un point de mesure pour sa grille et ses scènes,
pas une estimation garantie du coût d'un corpus plus fin. L'inférence CUDA du
réseau n'est pas la génération FDS. Les 118 s du précédent entraînement pilote
ne prédisent pas non plus le temps d'un lot plus grand.

Pour l'essai autorisé, imposer une échéance commune d'une heure au calcul,
mesurer un premier bloc représentatif, réserver explicitement du temps GPU et
du temps d'évaluation, puis adapter le nombre de scénarios. La limite se porte
sur le travail effectivement démarré ; elle ne déclenche pas une nuit de calcul
pour finir un nombre annoncé. Conserver les cas terminés et signaler les
interruptions. Un lot réduit mais équilibré et audité est exploitable.

Le checkpoint est choisi sur validation avec la même définition de score
annoncée avant l'essai. Le jeu final doit comporter à la fois nouvelles scènes
dans les familles couvertes et familles inédites, avec conditions comparables
pour isoler autant que possible l'effet de la géométrie. Les 60 cas de l'audit
qui ont orienté la correction sont désormais diagnostiques : ils ne peuvent
pas suffire à une affirmation finale indépendante.

Rapporter au minimum : précision/rappel/IoU chaleur et fumée, erreur des régions
actives et du fond, erreurs et positions des pics, délai d'arrivée de la fumée
aux points effectivement observés, résultats par incident/gravité/famille,
comparaison ambiance et modèle initial. Agréger par cas puis scène ; si des
intervalles d'incertitude sont calculés, rééchantillonner des scènes entières,
pas des millions de points corrélés. Les seuils de diagnostic ne sont pas des
seuils de danger certifiés.

Si le petit lot ne s'apprend pas, diagnostiquer encodage, masques, cibles,
normalisation et optimisation avant d'agrandir le réseau. S'il s'apprend mais
que le test échoue, analyser couverture et représentations ; GINO ou un
décodeur par coordonnées deviennent des expériences justifiées lorsque la
grille fixe est identifiée comme limite. Une amélioration sur une seule famille
ne justifie pas l'étiquette « généraliste ».

## Lien scientifique avec le challenge NASA

Les expériences **Saffire IV/V** publient des observations de propagation,
températures, dégagement de chaleur et transport de produits de combustion.
Elles soulignent notamment l'effet des dimensions de l'échantillon et du conduit
sur la croissance et la propagation. Ce sont des axes concrets pour comparer
des simulations à l'expérience et contextualiser les résultats dans le tableau
de bord. Leurs observables sont spécifiques ; ce n'est pas un fichier universel
de labels 3D pour toute cabine importée.
[Urban et al., ICES-2021-266, NASA NTRS, juillet 2021](https://ntrs.nasa.gov/citations/20210011521).

L'inventaire de ressources [NASA PSI-98 — Saffire](https://psi.nasa.gov/physci/repo/data/investigations/PSI-98)
a été retrouvé ; son interface n'a pas fourni de texte lisible par l'outil web
durant cette recherche. Aucun nouveau fichier expérimental n'a été téléchargé
ni intégré à l'entraînement dans cette tâche. La ressource réellement exploitée
antérieurement est la calibration de ventilateur BASS-II, documentée dans
[NASA.md](NASA.md). Elle ne calibre ni la combustion ni le modèle spatial.

Les [manuels officiels NIST](https://pages.nist.gov/fds-smv/manuals.html), consultés
le 14 novembre 2026, indiquent FDS 6.11.1 et distinguent théorie, vérification
numérique et validation expérimentale. Le lien de téléchargement du guide
technique n'a pas été accessible à l'outil web ; aucune nouvelle affirmation
technique détaillée n'est attribuée à ce PDF non lu. Les hypothèses actuelles
restent celles du compilateur documenté dans le dépôt.

Apprendre fidèlement FDS est une première validation de l'émulateur. Comparer
FDS à une expérience compatible est une validation différente. Une réduction
de l'erreur ML n'élimine pas le biais d'une source thermique équivalente, d'un
rendement de suie supposé, d'un matériau de substitution ou d'une géométrie
simplifiée. La présentation NASA doit permettre de remonter de chaque conclusion
à sa simulation, ses hypothèses et, lorsqu'elle existe, sa preuve expérimentale.

## Addendum — diagnostic de perte et contrôle du support spatial

Le [diagnostic de reprise](../evidence/incidents/spatial-recovery/diagnostic-report.json)
compare maintenant les objectifs historique et équilibré, chacun pendant
80 époques et 1 920 pas, avec même initialisation, même ordre de données et même
optimiseur. Les deux essais et leur évaluation ont pris **77,01 s sur RTX 4070
Ti**. Ils portent sur six **cas d'entraînement** : cinq incidents actifs d'une
même disposition procédurale en microgravité et un contrôle calme d'une
disposition cargo. Ils ne mesurent aucune généralisation et ne couvrent pas les
deux gravités dans les incidents actifs.

| Mesure sur ces six cas | Perte historique | Régions équilibrées |
| --- | ---: | ---: |
| Rappel chaleur | 68,40 % | 100,00 % |
| Précision chaleur | 58,72 % | 6,53 % |
| IoU chaleur | 46,19 % | 6,53 % |
| Rappel fumée | 83,15 % | 98,85 % |
| Précision fumée | 46,29 % | 4,72 % |
| IoU fumée | 42,32 % | 4,72 % |
| Faux positifs chaleur | 213 | 6 340 |
| Faux positifs fumée | 1 340 | 27 686 |
| MAE des pics de température, moyenne par disposition | 63,08 °C | 114,75 °C |
| MAE des pics de suie, moyenne par disposition | 3,461 × 10⁻⁴ kg/m³ | 2,375 × 10⁻³ kg/m³ |

Les comptes restent des couples point/instant corrélés. Le modèle historique
apprend une partie des régions actives : il existe donc bien un signal
d'apprentissage. L'équilibrage seul étend trop largement chaleur et fumée et
aggrave les pics. Il **ne doit pas être adopté sur la seule hausse du rappel**.
La baisse de son erreur encodée de sélection, de 0,660 à 0,455, alors que les
IoU chutent, montre aussi pourquoi le score doit contrôler le support spatial.
Cette expérience invalide la recommandation initiale d'adopter un équilibrage
seul sans comparaison ; elle ne prouve pas qu'aucun autre équilibrage ne marche.

La littérature sur segmentation fournit une piste précise. Sudre et al.
étudient les pertes de recouvrement Dice pour des structures rares, en montrant
l'importance du déséquilibre et des réglages d'optimisation.
[Generalised Dice, version du 14 juillet 2017](https://arxiv.org/abs/1707.03237).
Salehi et al. proposent Tversky pour régler explicitement le compromis entre
faux positifs et faux négatifs en segmentation 3D. Leurs résultats concernent
des lésions médicales, pas des champs de combustion : l'application à IGNIS
est une hypothèse d'ingénierie à tester.
[Tversky loss, 18 juin 2017](https://arxiv.org/abs/1706.05721).

**Une seule ablation proposée, sans nouvelle architecture : historique +
contrôle différentiable du support.** Conserver la régression historique, qui
donne ici les meilleurs pics et la meilleure précision, et ses poids globaux.
À partir des deux sorties continues encodées existantes, calculer un indicateur
doux de dépassement des seuils déjà fixés. La proposition exacte pour le prochain
diagnostic est :

```text
a_T = asinh(5 / 20)
a_S = asinh(1e-7 / 1e-6)
tau_c = a_c / 8
logit_i = (prediction_encodee_i - a_c) / tau_c
q_i = sigmoid(logit_i)
y_i = 1 si la cible physique observée dépasse le seuil, sinon 0

TP = somme(q * y)
FP = somme(q * (1 - y))
FN = somme((1 - q) * y)
L_Tversky = 1 - (TP + epsilon) / (TP + 0.7 * FP + 0.3 * FN + epsilon)
L_support = L_Tversky + 0.1 * BCEWithLogits(logit, y)
L_total = L_historique_champs + 0.25 * L_global + 0.25 * L_support
```

Les sommes de recouvrement et la moyenne BCE portent uniquement sur les points
observés du gaz, par variable et par instant. Une variable non observée est
exclue. Lorsqu'il n'y a aucun actif observé, omettre Tversky et conserver la BCE
sur le fond : un recouvrement avec un ensemble vide ne doit pas devenir une
récompense trompeuse ou une division par zéro. Prendre un epsilon numérique
fixe et l'enregistrer. Les termes sont ensuite moyennés sur les variables
observées et les instants avec les poids de scènes existants.

Cette adaptation apporte un coût aux régions prédites hors du support cible.
Le poids 0,7 désigne explicitement **FP**, 0,3 **FN** ; l'objectif de cette
ablation est de réduire la diffusion excessive observée. La petite BCE fournit
aussi un gradient lorsqu'un logit erroné sature la sigmoïde. Coefficients,
températures de sigmoïde et seuils sont fixés avant l'essai ; ils ne sont ni des
valeurs optimales établies par un article, ni une calibration probabiliste.
Le diviseur huit est un choix d'ingénierie fixé avant l'ablation : le support
doux vaut environ `sigmoid(-8) = 0,000335` à la sortie encodée zéro, contre
`sigmoid(-4) = 0,018` avec un diviseur quatre. Sur 1 500 points froids, ces
sommes représentent respectivement environ 0,5 et 27 pseudo-points actifs.
Cela réduit l'incitation à produire un fond négatif, avec pour contrepartie
un gradient de support plus faible près de zéro ; la régression continue
fournit toujours son signal. Contrôler les températures sous l'ambiante et
le comportement du contrôle calme.

Calculer le terme d'entraînement sur les **sorties encodées brutes**. Le décodage
tronque la suie négative à zéro ; reconstruire ensuite un logit depuis cette
valeur tronquée impose un plancher artificiel `sigmoid(-8)`. Cela ne doit pas
servir à sélectionner le checkpoint. Les métriques de pertinence restent
calculées sur les champs physiques décodés avec les seuils inchangés. Le score
de sélection fixé est l'erreur encodée composite existante, augmentée de
`0.5 * (1 - IoU_chaleur) + 0.5 * (1 - IoU_fumee)`, puis agrégée par cas et
disposition. Une union vide donne IoU = 1 seulement si aucun point positif
n'est présent ni prédit. Les deux IoU restent publiées séparément.

Comparer cette ablation sur les mêmes six cas, 80 époques, seed `20261115`,
AdamW et taux `1e-3`, sans autre modification. Préserver les résultats historiques
et équilibrés. Si le support s'améliore sans aggravation des foyers manqués et
des pics, fixer l'objectif retenu à partir de ce diagnostic d'entraînement,
puis l'évaluer sur les 20 cas de validation prévus. Une baisse de perte ou un
rappel élevé seuls ne suffisent pas ; présenter précision, rappel, IoU, pics
et contrôle calme ensemble. Ces 20 cas servent au développement et à la
sélection, pas à une déclaration finale de généralisation.

Une perte de distance à la frontière serait une autre piste si les régions
restaient mal localisées. Kervadec et al. la combinent à une perte régionale sur
des segmentations très déséquilibrées. Elle exige ici une définition correcte
des distances physiques et des masques sur les grilles ; elle est donc reportée
pour éviter de cumuler plusieurs changements dans le même essai.
[Boundary loss, PMLR 102, 2019](https://proceedings.mlr.press/v102/kervadec19a.html).

Cette section conserve le protocole proposé avant exécution. Les résultats
obtenus ensuite sont consignés dans l'addendum suivant.

## Addendum — résultat de l'ablation avec support

Le [rapport d'ablation localisée](../evidence/incidents/spatial-recovery/localization-diagnostic-report.json)
est maintenant disponible. Il compare `historical` et `localized` sur les six
cas d'entraînement, avec 80 époques et 1 920 pas par objectif ; l'exécution
rapporte 74,95 s au total sur RTX 4070 Ti. Les chiffres ci-dessous proviennent
exclusivement de cette exécution.

| Mesure | Historique de cette exécution | Historique + support |
| --- | ---: | ---: |
| Rappel chaleur | 88,49 % | 36,34 % |
| Précision chaleur | 26,81 % | 96,99 % |
| IoU chaleur | 25,91 % | 35,94 % |
| Rappel fumée | 96,98 % | 27,36 % |
| Précision fumée | 14,89 % | 88,99 % |
| IoU fumée | 14,82 % | 26,46 % |
| Faux positifs chaleur / fumée | 1 070 / 7 698 | 5 / 47 |
| Faux négatifs chaleur / fumée | 51 / 42 | 282 / 1 009 |
| MAE du champ de température, moyenne par disposition | 0,217 °C | 0,777 °C |
| MAE des régions chaudes | 43,32 °C | 63,38 °C |
| MAE des pics de température, moyenne par disposition | 69,97 °C | 95,09 °C |
| MAE des pics de suie, moyenne par disposition | 3,406 × 10⁻⁴ kg/m³ | 3,799 × 10⁻⁴ kg/m³ |
| MAE des régions enfumées | 8,006 × 10⁻⁵ kg/m³ | 8,905 × 10⁻⁵ kg/m³ |
| Score de sélection avec support, plus bas = meilleur | 0,971 | 1,356 |

Le terme de support réduit fortement les faux positifs, mais manque maintenant
la majorité des observations chaudes et enfumées. Le gain de précision et
d'IoU agrégée ne constitue donc pas un succès : les erreurs physiques et le
score de sélection se dégradent. Les cas arc et batterie n'ont aucun vrai
positif chaleur ou fumée avec cette ablation. Elle n'est pas une correction
suffisante pour un outil destiné à repérer les conséquences d'un départ.

**Le témoin historique de cette exécution diffère du témoin du premier
diagnostic.** Les deux rapports ont des empreintes de scripts différentes ;
la cause de la différence numérique du témoin doit être établie séparément.
La présence du même seed dans les recettes n'autorise pas à présenter les deux
exécutions comme une répétition numériquement identique. Ne pas comparer le
`localized` de ce rapport au `historical` du rapport précédent pour attribuer
un gain causal. À ce stade, conserver le témoin mesuré dans la même exécution
et la réserve de provenance ; aucune affirmation de généralisation n'en découle.

L'objectif **historique** est retenu pour l'entraînement final : l'ablation de
support n'a pas satisfait le critère prévu de préservation du rappel et des pics.
Le checkpoint reste sélectionné sur validation avec le composite incluant les
IoU. La comparaison porte donc sur davantage de scènes, un entraînement prolongé
et cette sélection ; elle n'isole pas l'effet causal de chaque changement.
Le test réservé sert uniquement à mesurer le modèle ainsi fixé ; ses résultats
ne doivent pas déclencher un ajustement du même modèle tout en conservant
l'étiquette de test indépendant.

Les listes des six cas des deux diagnostics ont été comparées et sont identiques.
Les empreintes des dépendances historiques sont également identiques, hors
scripts de reprise/perte modifiés pour l'ablation. Les opérations CUDA
déterministes ne sont pas imposées ; le même seed ne garantit donc pas une
répétition numérique exacte. Cela ne suffit pas à attribuer toute la variation
observée à une cause précise. Les drapeaux de déterminisme sont enregistrés
dans les métadonnées de l'entraînement final ; aucun résultat multi-seed ou
intervalle de confiance d'architecture n'est revendiqué.

Le script local [`analyze_spatial_recovery.py`](../tools/remote/analyze_spatial_recovery.py)
prépare la lecture des résultats finaux : `training-report.json` (ou `report.json`
du trainer), `replay-report.json` et `test-plots.json.gz` dans le dossier de
preuves. Il reprend les moyennes par disposition après contrôle des lignes
individuelles, détaille gravités et incidents, vérifie les erreurs de pics des
exports et conserve les résumés d'arrivée fournis par l'évaluateur de trajectoires.
Sans `per_case_arrival`, cette mesure reste indisponible : les maxima temporels
et les coupes aux pics ne permettent pas de reconstruire les observations
communes de chaque point. Une absence d'arrivée n'est jamais remplacée par
l'instant final. Le script ne modifie ni modèle ni sélection.

```text
.venv/bin/python tools/remote/analyze_spatial_recovery.py --directory evidence/incidents/spatial-recovery
```

La sortie JSON est écrite sur stdout ; `--output chemin.json` crée explicitement
un nouveau fichier sans écraser un rapport existant. Les agrégations ont été
vérifiées sur les deux diagnostics réels et les 60 cas de l'audit antérieur.
L'analyse intégrale a depuis été exécutée sur les trois fichiers finaux ;
[analysis.json](../evidence/incidents/spatial-recovery/analysis.json) et les figures
proviennent des sorties mesurées, sans résultat fictif.

## Suite proposée après l'essai final

La température reste mal prédite : 1,94 % de rappel global sur les observations
chaudes du test. La fumée ne suffit pas non plus en microgravité, avec 71,99 %
de rappel et 18,52 % de précision. Ces résultats motivent les pistes ci-dessous ;
aucune nouvelle simulation ni optimisation n'a suivi la consultation du test.

Les pistes suivantes sont des expériences à départager sur entraînement et
validation, pas des corrections acquises. Le
[`final-training-survey.json`](../evidence/incidents/spatial-recovery/final-training-survey.json)
décrit 170 cas et 66 dispositions d'entraînement. Après l'instant initial, il
compte **20 440 observations chaudes sur 6 475 156 observations valides**
(0,316 %, présentes dans 91 cas), contre **252 973 observations enfumées**
(3,907 %, présentes dans 133 cas). Les seuils sont ambiance + 5 °C et
0,1 mg/m³. Il s'agit de points × instants corrélés, pas de millions de scènes
indépendantes. Les cinq types d'incident comptent chacun 34 cas, mais seulement
2 cas d'arc contiennent des observations chaudes : équilibrer les étiquettes
d'incident ne suffit pas à équilibrer le signal thermique.

1. **Vérifier la résolution de la supervision.** Comparer, sur quelques cas
   d'entraînement/validation, sondes plus denses près de la source et instants
   supplémentaires pendant la montée thermique. La convergence du maillage FDS
   et la densité des sondes exportées sont deux questions distinctes. Interpoler
   les cibles ou agrandir la grille de rendu n'ajoute aucune mesure. Un éventuel
   rééchantillonnage doit préserver coordonnées, masques, unités et provenance.
2. **Traiter la rareté avant de conclure à un manque de capacité.** Tester
   séparément un échantillonnage d'instants chauds en conservant des instants
   calmes et des contrôles. Mesurer ensemble rappel, précision, faux positifs et
   erreurs physiques. Les deux ablations précédentes montrent qu'une simple
   pondération ou un terme de support peut déplacer le problème ; elles ne
   justifient pas une nouvelle combinaison non mesurée. Le test conserve sa
   distribution et ne sert jamais à choisir le dosage.
3. **Diagnostiquer la capacité sur l'ajustement d'entraînement.** Les six cas
   montrent un apprentissage partiel, pas un sur-apprentissage exact. Examiner
   leurs courbes et erreurs avant un essai borné de largeur supérieure. Un
   échec en validation seul ne démontre ni sous-capacité ni besoin d'un réseau
   de grande taille ; comparer à budget et protocole explicites.
4. **Examiner ce que la représentation perd.** Les fractions de volume et
   propriétés moyennées encodent la géométrie ; elles ne constituent pas une loi
   physique de mélange. Des détails locaux ou une distance aux surfaces peuvent
   aider à distinguer de fins passages, à vérifier par ablation. Le réseau
   actuel reçoit les débits/vitesses aux évents et ne prédit pas la vitesse
   interne. Cela ne signifie pas que les données en sont dépourvues : le
   compilateur mesure T, O2, suie et U/V/W ; le parseur et `result.json.gz`
   conservent ces six champs, alors que `fields.npz` et les têtes actuelles
   utilisent seulement T/suie. Une supervision auxiliaire des vitesses est donc
   une piste de préparation des archives, avec contrôle des valeurs manquantes
   et des faces de grille décalées utilisées par FDS. Son bénéfice reste à
   mesurer ; elle ne garantit pas une conservation physique du réseau.
5. **N'augmenter les scènes que par transformations cohérentes.** Des réflexions
   horizontales ou un demi-tour autour de la verticale peuvent préserver la
   gravité descendante et les sources sur face supérieure, à condition de
   transformer ensemble obstacles, matériaux, source, évents, coordonnées,
   vecteurs, masques et cibles. Recalculer les canaux de position/distance et les
   signes de vitesse concernés. Un simple `flip()` n'est pas automatiquement
   valide : l'arrondi des sondes vers des centres de cellules FDS peut rendre
   leurs coordonnées asymétriques. Vérifier la correspondance des coordonnées
   et l'équivalence avec le compilateur avant de réutiliser des labels. Un
   quart de tour échange aussi les dimensions et transforme 12 × 16 × 8 en
   16 × 12 × 8 ; ce n'est pas un ajout transparent au chargement actuel. Exclure
   retournements verticaux, rotations arbitraires et changements d'échelle non
   simulés. Toutes les variantes restent dans le groupe de leur disposition
   d'entraînement, sans devenir de nouveaux cas de test indépendants.

Ces propositions n'altèrent pas le modèle final gelé ; aucune métrique d'époque
intermédiaire n'est présentée ici comme sa performance finale. Si un prochain développement
est motivé par l'analyse du test, il faudra un nouveau test réservé pour en
mesurer la généralisation.
