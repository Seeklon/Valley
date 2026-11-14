# Vue mission — cabine, fumée et prévention

La page d'accueil ouvre une vue à hauteur d'occupant de la capsule inspirée de
Soyouz. Elle charge une **relecture existante** ; ouvrir le site ne lance ni
entraînement ni nouvelle simulation. Le laboratoire et les analyses détaillées
restent accessibles dans la navigation.

## Parcours

- **Fumée & chaleur** : choisir une scène et une simulation enregistrée, puis
  utiliser lecture/pause, retour au début, vitesse et barre temporelle. La
  première image correspond à un instant enregistré avec beaucoup de fumée,
  affiché explicitement dans la timeline ; la lecture démarre sur action.
- **POV** : glisser pour regarder, flèches ou ZQSD/WASD pour déplacer la caméra,
  molette pour avancer/reculer. Le clavier agit lorsque le canvas a le focus.
  La navigation respecte l'enveloppe générale, sans collision fine avec tous
  les équipements. **Orbite** permet de tourner autour ; **Dessus** de déplacer
  le plan. Recentrage et plein écran sont disponibles.
- **Couches** : fumée thermique, fumée grise, température, ventilation ou cabine
  seule. L'intensité règle uniquement l'opacité visuelle. Le panneau se replie
  pour agrandir la scène ; sur mobile il passe sous la vue.
- **Avant allumage** : choisir un composant, régler courant et air local, calculer
  puis lire l'historique et la prévision. Les paramètres avancés et les résultats
  sont partagés avec l'onglet Prévention. Une configuration modifiée invalide la
  carte précédente jusqu'au nouveau calcul.
- **Modifier le scénario** transmet au laboratoire la configuration du replay
  affiché. Un calcul déjà actif reste prioritaire ; il n'est pas remplacé.

## Signification des champs

La fumée thermique emploie la densité de suie pour l'opacité et la température
du gaz pour la couleur. Les unités de légende sont °C, mg/m³ ou m/s. Les maxima
globaux affichés dans le panneau ne sont pas les maxima des sondes spatiales :
ces deux sorties peuvent différer.

Les échelles sont calculées sur l'enregistrement entier, avant décimation
graphique. L'interpolation utilise les timestamps réels, les positions de
sondes `sample_positions_m` et le masque valide aux deux instants. Les grilles
incompatibles ou champs absents ne produisent pas de rendu inventé. Les valeurs
nulles/solides sont exclues, y compris dans le masque spatial des volumes.

Le rendu utilise des volumes gaussiens doux aux positions échantillonnées. Il
ne résout ni nouvelle turbulence, ni advection, ni extinction optique : il ne
permet pas de mesurer la visibilité réelle d'un équipage. Le lissage graphique
n'ajoute pas de résolution physique. Aucune remontée artificielle de fumée
n'est appliquée en microgravité.

La demi-coque artistique de Soyouz est complétée par symétrie en vue intérieure
pour fermer visuellement la cabine. Les proxies physiques, matériaux, poids et
champs existants restent inchangés. Cette maquette ne décrit pas un véhicule
réel qualifié.

## Avant allumage

Les couleurs s'appliquent aux **repères de composants**, pas au gaz de la cabine.
Échelle fixe de température d'isolant, saturée aux bornes 20 et 300 °C. L'historique
simulé précède l'instant de prévision ; les valeurs suivantes viennent du modèle
thermique appris. La lecture reste dans les intervalles couverts : aucun point
ne prolonge une prévision après sa fin de validité. Sans estimation, le repère
reste gris. Aucune fumée n'est créée à partir de ces températures.

Le délai d'allumage conserve son domaine expérimental NiCr/LDPE. La source Guo
est liée séparément des conclusions NASA, dont la pertinence et les inconnues
restent visibles. Les analyses utilisent leurs preuves figées et peuvent être
interprétées par Codex ou exportées. Probabilité réelle et incertitude du délai
restent non quantifiées ; voir [les modèles](PREVENTION_MODELS.md).

## Données et contrôles

`GET /api/runs?limit=100` fournit les replays récents. La sélection privilégie
un calcul FDS de la scène choisie ; les résultats ne contenant que des métriques
sans champs sont écartés après lecture. Les prédictions spatiales sont étiquetées
ML. La puissance résistive affichée est I²R et la combustion couplée est
distinguée d'une source prescrite.

Le script `web/tools/mission-check.mjs` vérifie les vrais replays et modèles du
service, les caméras, le rendu à plusieurs instants, les couches, la lecture,
les changements de scène, les transferts de paramètres et le mobile. Aucun
nouveau calcul FDS n'est nécessaire. Rapports et captures de livraison :
`evidence/mission/`. Les tests unitaires couvrent masques, axes irréguliers,
interpolation, limites de prévision et sélection des replays.
