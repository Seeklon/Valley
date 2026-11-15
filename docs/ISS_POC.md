# POC spatial chaleur et fumée — livraison du 15 novembre

Le POC expose des prédictions enregistrées dans six familles d'intérieurs
simplifiés : laboratoire, nœud, service, cargo, cabine et racks centraux.
L'utilisateur entre dans un module,
parcourt le temps, sépare chaleur et fumée, puis compare le modèle à la
simulation FDS et à ses erreurs.

- Vue : <https://desktop-m4hkr86.tail609f26.ts.net:8444/#iss> (accès Tailscale).
- Sur le PC Windows, secours local : <http://127.0.0.1:8766/#iss>.
- Le POC du 14 novembre reste disponible sur `#poc`.
- L'intégration dans la maquette externe attend son lien ou son code.

## Ce que démontre le modèle

Le réseau apprend à localiser la chaleur et la présence de suie à partir de
volumes, matériaux, ventilation, conditions ambiantes, source électrique et
instant. Il ne reçoit pas les champs FDS comme entrées. L'architecture est un
U-Net 3D de **379 046 paramètres au total**, dont **376 834 entraînables** et
2 212 gelés dans une tête auxiliaire inutilisée. Il possède 54 canaux d'entrée
et deux sorties, sur une grille de 12 × 16 × 8 sondes. Le décompte exécuté sur
Windows est conservé dans `evidence/incidents/iss-poc-v2/model/parameter-count.json`.

Le foyer est une hypothèse imposée. La démonstration porte sur ses conséquences
spatiales, pas sur la probabilité de déclenchement d'un défaut électrique.

## Résultat du réentraînement sur six familles

Le même réseau est réentraîné depuis les poids v1 : **384 nouveaux scénarios**,
48 dispositions, **240 train / 48 validation / 96 test**. Les 48 géométries sont
distinctes entre partitions et différentes de toutes les géométries v1. Les six
familles restent communes aux partitions : ce test mesure des dispositions
inédites de familles connues.

Comparaison sur les **mêmes 84 scénarios de test en microgravité**, après gel
des poids et des seuils sur validation :

| Champ | F1 v1 figé | F1 v1 recalibré | F1 réentraîné | Précision réentraînée | Rappel réentraîné |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chaleur | 15,1 % | 24,6 % | 48,5 % | 45,1 % | 52,4 % |
| Fumée | 29,8 % | 27,6 % | 54,3 % | 47,9 % | 62,7 % |

Le modèle progresse au-delà d'un simple changement de seuils. Les erreurs restent
nombreuses ; il s'agit d'une preuve de concept synthétique. Ces scores ne doivent
pas être comparés directement aux scores v1 ci-dessous, calculés sur un autre
jeu plus étroit. Les 12 autres cas du nouveau test sont terrestres.

Calcul : **23 min 53 s** de génération, puis **8 min 32 s** pour le fit, validation
et export compris, soit environ **32 min 25 s** de phases de calcul. Le fit inclut
300 s d'optimisation et 14 387 mises à jour ; l'étape 1 000 est retenue sur
validation. GPU médian **98 %**, maximum **99 %**, sans promesse de saturation
constante. Les contrôles 0 W de validation et de test n'ont aucune fausse alerte.

Une trajectoire de 31 instants et 1 536 sondes s'infère en **84,7 ms CPU** ou
**52,7 ms GPU**, médianes de trois appels sur `habitat-cargo-v2-05-flame` après
chargement. Aucun désaccord binaire CPU/GPU sur ce cas mesuré.

Les 384 exports ont été contrôlés indépendamment contre les données FDS,
géométries, masques, seuils, poids et métriques. Les deux comparaisons v1 sont
recalculées à partir de leurs scores archivés et des observations originales.
Ce contrôle ne réexécute pas toutes les inférences du réseau.

Voir [les nouvelles données](ISS_POC_DATA_V2.md), [le protocole et les résultats
détaillés](ISS_POC_V2_MODEL.md), et
`evidence/incidents/iss-poc-v2/export-verification.json`.

## Résultat historique de la première tranche

108 scénarios, 18 dispositions, trois familles ; 72 cas d'apprentissage,
18 de validation et 18 de test. Les dispositions sont séparées entre
partitions, mais les familles sont communes. Les résultats suivants portent
sur les **15 cas de test en microgravité**, avec comptages agrégés aux sondes
observées après l'instant initial.

| Champ | Précision | Rappel | F1 modèle | F1 proximité du foyer |
| --- | ---: | ---: | ---: | ---: |
| Chaleur | 63,6 % | 71,4 % | 67,3 % | 36,8 % |
| Fumée | 58,5 % | 79,6 % | 67,4 % | 33,5 % |

F1 équilibre précision et rappel ; ce n'est pas un taux de réussite de 67 %
pour une station réelle. La chaleur signifie `T ≥ température ambiante + 5 °C` ;
la fumée signifie `suie ≥ 1e-6 kg/m³`. Le réseau ne prédit ni la température
ni la concentration quantitative.

Les seuils et le checkpoint ont été sélectionnés sur validation avant
l'évaluation du test. L'étape 1 000 a été retenue parmi 20 000 : prolonger
l'apprentissage ne suffisait pas à améliorer la validation. Tous gravités
confondues, le test contient une fausse alerte chaleur parmi neuf cas sans
dépassement thermique observé ; aucune fausse alerte fumée parmi cinq cas
sans suie au seuil. Ces populations diffèrent de la seule microgravité ci-dessus.

Calcul effectif : 7 min 18 s de génération FDS sur CPU, puis 4 min 55 s pour
l'exécution complète d'apprentissage, validation et export, dont 3 min 55 s
dans la boucle d'optimisation. Un premier essai de préparation CPU a échoué
après 11,5 s, avant toute mise à jour, puis a été corrigé et testé. Les phases
de calcul totalisent environ 12 min 25 s, hors développement et vérification.
L'utilisation GPU mesurée sur le fit réussi atteint 99 %, avec une médiane
de 96 % ; il ne s'agit pas d'une utilisation constante à 100 %.

Sur le cas de mesure `iss-laboratory-v04-flame`, une trajectoire de 31 instants
et 1 536 sondes s'infère en 81,8 ms sur CPU, médiane de trois appels après
chargement. La simulation FDS de ce cas prend 8,984 s. Ces tâches ont des
sorties différentes : classification approchée contre simulation physique.

## Parcours de présentation

1. Ouvrir `#iss`. Le cas initial de validation montre une surchauffe électrique
   dans une soute ; la caméra vise le foyer depuis une position libre.
2. Lire la chronologie, puis masquer alternativement chaleur et fumée.
3. Passer à « Référence FDS » puis « Erreurs » pour rendre les écarts visibles.
4. Changer de module et choisir « Test · géométries réservées » pour distinguer
   les scènes d'évaluation de celles utilisées pour régler le modèle.
5. Montrer le témoin `habitat-capsule-v2-05-control` et le cas difficile
   `iss-service-v2-05-arc`, sans les présenter comme une sélection exhaustive.
6. Revenir aux Sources NASA pour le contexte expérimental sur la combustion
   et le transport des fumées en microgravité.

La vue intérieure se contrôle par glisser pour regarder et flèches/ZQSD pour
avancer. La vue d'ensemble permet de tourner autour du module. Les halos
représentent les classes aux sondes, pas une densité physique ni une flamme
simulée entre les sondes. Les comparaisons doivent conserver ce même repère.

## Preuves et limites

- [Données et diversité](ISS_POC_DATA.md), [modèle et protocole](ISS_POC_MODEL.md),
  [contrat d'intégration](ISS_POC_INTEGRATION.md).
- `evidence/incidents/iss-poc/export-verification.json` : vérification des
  108 replays contre les observations FDS, masques, géométries, instants,
  partitions, métriques, poids et sélection figée. Ce contrôle ne réexécute
  pas indépendamment le réseau.
- `evidence/incidents/iss-poc/browser/` : contrôles et captures du rendu réel,
  trois modules, témoin, échec, partition test, déplacement et chronologie.
- `evidence/incidents/iss-poc/dev-delivery.json` : livraison et sauvegarde
  Windows, hashes de tous les fichiers livrés.

Les géométries ne reproduisent pas fidèlement l'ISS ; les coefficients des
matériaux sont des hypothèses du simulateur. Les arcs brefs sont peu résolus
par la grille et l'échantillonnage temporel. Ces données synthétiques ne sont
pas une validation expérimentale NASA ni une certification de sécurité.
Les ressources BASS/BASS-II, SAME et Saffire restent identifiées séparément
dans les Sources : voir [l'audit NASA](RECADRAGE_SOURCES_NASA.md).

Le renderer ajoute panneaux, équipements et textures aux dimensions des volumes
physiques, sans modifier les passages d'air. Les détails visuels ne constituent
pas des propriétés supplémentaires apprises par le modèle. Le kit autonome
regroupe la vue, les poids, l'inférence CPU et les exports ; voir le contrat
d'intégration pour relier ces champs à la géométrie physique de la maquette.
