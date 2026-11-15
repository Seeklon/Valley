# POC visuel — détection de points chauds par ML

Demande confirmée le 14 novembre 2026, vers 22:11 Europe/Paris. Rendu le
15 novembre à 18 h. Objectif : présenter un apprentissage réel et ses sorties
3D, à partir du socle existant. Le modèle généraliste et la refonte d'import
Blender ne sont pas des prérequis de cette démonstration.

**Périmètre d'exécution.** Entraînement PyTorch/CUDA sur le PC Windows,
RTX 4070 Ti, réutilisation du corpus compact de 200 cas. Classifier les sondes
gazeuses dépassant la température ambiante de 5 °C ; les valeurs non observées
restent exclues. Budget GPU cumulé de 20 minutes maximum pour cette tranche,
avec un premier entraînement borné puis au plus une correction motivée sur
validation. Aucune génération FDS nouvelle ni reprise du corpus initial.

**Présentation.** Une vue de la scène avec points chauds FDS, une vue avec les
détections ML, caméra et chronologie synchronisées. Le score de détection
appartient à une classe définie, pas à une probabilité d'incendie. La température
de référence conserve ses unités ; aucun score n'est affiché comme des degrés.
Les proxies, obstacles, matériaux, source et conditions proviennent des données.
Pas d'interpolation donnant l'apparence de mesures supplémentaires.

Le navigateur charge un index léger puis le cas choisi. Les fichiers présentés
sont des inférences enregistrées du checkpoint livré, identifiées comme telles.
Changer de cas ou de temps relit ces prédictions ; cela ne lance pas un nouveau
FDS et ne prétend pas accepter un environnement arbitraire en temps réel.

**Évaluation.** Entraînement 120 cas, validation 40 ; aucune séparation aléatoire
des instants d'une même scène. Poids et seuil choisis sur validation. Les 40 cas
de test historique sont absents du fit mais ont déjà été examinés lors des
anciens essais : cette limite doit accompagner leur résultat. Afficher
précision, rappel, intersection/union, erreurs et contrôles froids, en distinguant
microgravité/Terre et les partitions. Les métriques excluent l'instant initial.

Le cas de départ proposé est représentatif des validations microgravité avec
échauffement (proche de la médiane d'IoU), pas présenté comme une performance
universelle. La liste complète et des cas d'échec/contrôle restent consultables.
La règle de sélection et les résultats réels sont archivés avec les poids.

**Challenge NASA.** Les sources BASS-II, Saffire et SAME restent disponibles
dans le parcours existant. Elles expliquent pourquoi gravité, écoulement et
matériaux comptent. Les étiquettes du classifieur proviennent de FDS ; elles ne
deviennent pas des mesures NASA. L'angle de présentation est la possibilité
d'accélérer l'exploration visuelle de scénarios, avec cette distinction explicite.

**Livraison attendue.** Poids et protocole conservés sur Windows ; sources,
preuves légères et guide dans le dépôt ; vue POC sur la version de développement.
Contrôles de données, tests du modèle et du frontend, comparaison dans un vrai
navigateur et captures. Les services et modèles antérieurs restent disponibles.
Aucune promesse de livraison ou de qualité n'est substituée aux vérifications.

## Résultats obtenus ce soir

Deux essais terminés, sans nouvelle simulation. Calcul cumulé : **561,625 s
(9 min 22 s)**, entraînement, validation, benchmark et export compris. Le
premier essai est retenu, exclusivement sur la validation : F1 moyen microg/Terre
0,325 contre 0,318 pour le second. Entraînement du modèle retenu : **191,766 s**,
16 000 mises à jour, checkpoint 4 000 conservé.

L'optimisation de la deuxième boucle atteint **98 % d'utilisation GPU sur
11 relevés consécutifs pendant l'apprentissage**, avec lots de 128 ; ce n'est
pas la moyenne de toute l'exécution. Le benchmark donne environ 6 400 exemples/s.
Cette boucle est conservée dans les sources ; ses poids n'ont pas remplacé ceux
du premier essai, meilleur selon le critère fixé.

| Mesure | Microg validation | Microg test historique | Terre test historique |
|---|---:|---:|---:|
| Précision ML | 39,6 % | 52,3 % | 52,4 % |
| Rappel ML | 39,6 % | 47,1 % | 8,8 % |
| IoU ML | 24,7 % | 33,0 % | 8,1 % |
| F1 ML | 0,396 | 0,496 | 0,150 |
| F1 proximité source | 0,377 | 0,403 | 0,007 |

Le test historique est exclu du fit, mais déjà consulté dans les expériences
précédentes. Il ne constitue pas un test vierge. Le gain sur la proximité
s'accompagne encore de nombreux points chauds manqués. **7/18 cas sans
dépassement observé en validation et 8/22 dans le test historique ont une
fausse alerte ML.** Un faible taux de faux positifs par point ne signifie donc
pas un faible taux de fausses alarmes par scène.

La preuve obtenue est limitée : un réseau spatial peut apprendre une
localisation partielle de points chauds synthétiques, à partir de la scène et
d'une source imposée. Ce POC ne démontre ni la probabilité d'allumage, ni la
fumée ML, ni une généralisation fiable à une nouvelle capsule.

## Démonstration en deux minutes

Lien de développement : **https://desktop-m4hkr86.tail609f26.ts.net:8444/#poc**
(accès Tailscale au PC Windows). Déployé et contrôlé dans Chromium le 14 novembre
au soir. Ancienne interface conservée en sauvegarde, services 8443 et 8444 sains.

1. Ouvrir le parcours **POC ML** de la version de développement. Le cas affiché
   est proche de la médiane d'IoU des validations microg avec échauffement,
   sélectionné sans chercher le meilleur exemple.
2. Montrer FDS à gauche et le réseau à droite. Tourner les deux scènes, puis
   revenir au premier instant, choisir **×5** et cliquer **Lire** pour parcourir
   les instants. **Pic FDS** revient au maximum
   mesuré. Les prédictions sont enregistrées ; la lecture ne relance pas FDS.
3. Activer **Erreurs ML** : orange détecté, bleu manqué, rose fausse alerte.
   Cliquer une sonde pour voir température FDS et score ML séparément.
4. Montrer le tableau ML/proximité et la fréquence des cas avec fausse alerte,
   puis les raccourcis **Échec observé** et **Témoin froid**. Les 200 cas restent
   accessibles dans leurs partitions.
5. Ouvrir **Sources NASA** pour relier gravité, ventilation et matériaux aux
   connaissances expérimentales disponibles. Préciser que l'apprentissage
   utilise FDS, sans validation expérimentale NASA de ce réseau.

Formulation du pitch : « Nous avons entraîné un petit réseau 3D sur des
simulations pour localiser rapidement des points chauds dans un scénario
d'incident. La comparaison montre ce qu'il détecte et ce qu'il manque.
L'étape suivante sera de mieux couvrir les géométries et de confronter les
hypothèses aux expériences de microgravité. »

## Artefacts conservés

- Modèle retenu et export complet :
  `E:/IGNIS-Valley-dev/runtime/hotspot-poc/20261114-evening/fit1`.
- SHA-256 du fichier de poids :
  `fe4f781dd50f66d27400f87beef91a2ce7c666c3319b143d5cb42c5f577ead60`.
- Sélection, mesures GPU, rapports et contrôle indépendant des 200 replays :
  `evidence/incidents/hotspot-poc/`.
- Archives complètes `fit1-complete.zip` et `fit2-complete.zip` conservées
  séparément ; elles ne sont pas destinées à Git. Les JSON lourds servis au
  navigateur sont également exclus de Git.

Le vérificateur recalcule les métriques depuis les valeurs réellement affichées,
contrôle les masques, les partitions, les groupes gravité/chaud/froid et les
empreintes de chaque cas. Aucun recalcul ML ou FDS n'est nécessaire pour le lancer.

**Vérifications réalisées :** build TypeScript/Vite, 82 tests frontend, 17 tests
modèle sur Windows, 8 tests du vérificateur et contrôle indépendant des 200 cas.
Dans le navigateur du site livré : comparaison FDS/ML, chronologie, caméra liée,
couche d'erreurs, scénarios d'échec et sans dépassement, étiquette du test
historique et vue portable. Aucun appel d'écriture ni erreur JavaScript pendant
ce parcours. Captures dans `evidence/incidents/hotspot-poc/browser/`.
