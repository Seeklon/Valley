# Prédiction des conséquences et simulation par point

Le parcours actuel part d'un composant électrique annoté dans Blender. Il pose
la question : **si un incident commence ici, où se retrouveront chaleur et fumée ?**
Les composants sont comparés par conséquences. Aucun taux de panne ni probabilité
de départ de feu n'est déduit de leur seule présence.

## Deux pages, une configuration

- **Prédiction IA** calcule une estimation pour chaque point de la scène. Cliquer
  un point affiche ses champs de température et de suie dans la vue 3D. La couleur
  des points compare le pic de température, le pic de fumée ou les équipements
  exposés, avec une échelle fixe par critère.
- **Simulation** reprend exactement le point, la famille et les conditions choisis,
  puis lance FDS explicitement. Lecture temporelle, POV, orbite, dessus et export
  permettent d'inspecter le résultat. Changer les conditions invalide les résultats
  qui ne correspondent plus ; changer de point conserve la carte globale.
- **NASA** donne accès aux observations expérimentales sourcées et à leur
  interprétation par Codex. Les anciens outils restent disponibles sous **Outils**.

Les cinq départs sont la surchauffe, l'impulsion thermique équivalente à un arc,
le feu déclaré, le feu couvant et la batterie. Les deux derniers imposent chaleur
et émission de suie ; ils ne résolvent ni chimie du couvant ni électrochimie.
Voir [les profils physiques](INCIDENT_PHYSICS.md). Le feu déclaré impose un débit
nominal de combustible : FDS calcule séparément la puissance réellement brûlée.

## Ce qui vient de Blender

Les boîtes physiques, leurs matériaux, les revêtements combustibles et leur
épaisseur, les bouches, sondes et composants alimentent le calcul. Les shaders
visuels ne constituent pas des propriétés thermiques. Les objets voisins
combustibles peuvent pyrolyser dans le solveur.

L'import annoté existant est étendu avec :

| Annotation | Propriétés ajoutées |
|---|---|
| Équipement | `combustible_material_id` (PMMA ou cellulose), `thermal_thickness_m`, `ignis_critical` |
| Point électrique (Empty) | `ignis_role="component"`, `ignis_id`, `source_object_id`, `source_face=3`, `component_kind`, `ignis_provenance` |
| Sonde de passage | `ignis_passage=true` |

La première version place les points à l'intérieur de la face supérieure d'un
objet physique. Le compilateur place ensuite une source d'une cellule sur cette
face discrétisée et publie la position réellement appliquée. L'interface utilise
cette position pour les résultats ML et FDS. Deux points sur un même équipement
peuvent correspondre à des cellules différentes.

Les quatre scènes fournies comportent **17 points** (2 dans Soyouz, 5 dans chacune
des autres scènes). Leurs matériaux et équipements sont des hypothèses d'étude,
pas un relevé qualifié d'une capsule réelle. Les annotations sont séparées du
catalogue historique pour préserver les anciens modèles et archives.

L'export est décrit dans [SCENES.md](SCENES.md). Pour un modèle personnel, exporter
son paquet, ajouter son entrée au tableau `scenes` du catalogue de développement,
placer son GLB dans `scenes/generated/`, puis redémarrer le service. Il n'y a pas
d'import par glisser-déposer dans cette version. Une nouvelle géométrie peut être
simulée ; l'estimation ML est disponible uniquement dans son enveloppe déclarée,
avec la mention « géométrie inédite » quand elle n'a jamais été évaluée.

La copie Soyouz annotée est conservée sur Windows dans
`E:/IGNIS-Valley-dev/scenes/annotated/soyuz.blend`. Le véritable aller-retour Blender
4.5.9 a conservé ses deux sources, matériaux et épaisseurs ; les deux sources
exportées ont été compilées. Preuves : `evidence/incidents/blender-verification.json`.

## Modèle léger et données

`incident-field-v1` utilise Extra Trees sur des descripteurs physiques : disposition,
occupation du volume, matériaux et épaisseurs, position du départ, bouches,
conditions et temps. Les noms/IDs de scènes et équipements ne sont pas des entrées
prédictives. Le modèle prédit température et suie aux points gazeux ; vitesse et
oxygène spatiaux restent indisponibles côté ML.

Le pilote comporte 60 calculs FDS de 30 secondes sur 12 dispositions. Les partitions
contiennent des dispositions complètes : 30 calculs train, 15 validation et
15 test. Crossflow est entièrement réservé au test. Le réglage choisit entre deux
forêts sur validation ; les résultats de test restent séparés. L'apprentissage
est plafonné à 60 000 observations gazeuses, 64 arbres, profondeur 14 et 4 threads.
Ces observations ne sont pas des essais indépendants.

Domaine du pilote : 0,0001 ou 1 g, air 0,05–0,4 m/s, oxygène 18–24 %, puissance
500–3 000 W, source de 10 s (arc : 1 s), prévision jusqu'à 30 s. La simulation
physique accepte les bornes plus larges du formulaire. Des bornes admissibles
ne garantissent pas la précision de chaque combinaison.

Les métriques complètes et la référence « température ambiante, aucune fumée »
sont conservées avec les poids. Une erreur moyenne faible dans une cabine
majoritairement froide peut masquer une mauvaise estimation des zones chaudes :
les erreurs sur régions actives et sur les pics sont publiées séparément.

## Mesure du pilote Extra Trees

Le pilote a effectivement été généré sur Windows et le modèle entraîné en
109 secondes sur CPU. Sur les 15 calculs Crossflow réservés, l'erreur moyenne
locale de température est de **0,0247 °C**, contre **0,0171 °C** pour une cabine
supposée constamment à 20 °C. Cette moyenne dominée par le gaz froid ne démontre
pas une bonne prédiction. Dans les observations chaudes (≥25 °C), l'erreur est
**5,86 °C**, contre **6,05 °C** pour la référence. L'erreur de puissance chimique
est **233 W**, contre **91 W** pour une puissance toujours nulle.

Le modèle reste donc une référence exploratoire et l'interface l'indique.
Les nouvelles géométries procédurales et le réseau spatial 3D font l'objet d'un
corpus et de poids distincts. Les résultats du pilote ne servent pas à sélectionner
répétitivement un modèle sur son jeu de test. Métriques intégrales et baseline :
`evidence/incidents/evaluation.json`.

## Interprétation des résultats

Les seuils de comparaison sont **60 °C dans le gaz** ou **10 mg/m³ de suie**.
Ils servent à comparer des scénarios ; ce ne sont ni des températures d'allumage
ni des seuils physiologiques qualifiés. Les volumes sont approximatifs sur
320 points d'observation ; un équipement est évalué par une sonde gazeuse proche
de son sommet. Sans couverture suffisante, la valeur reste inconnue. Sans sonde
de passage annotée (cas Soyouz), le nombre de passages exposés reste inconnu.

La visualisation lisse ce champ clairsemé sans ajouter de résolution physique.
Le maillage FDS de 0,20 m n'a pas d'étude de convergence. Ces modèles apprennent
le simulateur : ils ne prouvent pas la généralisation à une vraie cabine.
Augmenter le nombre de scènes réduit certaines lacunes du jeu d'apprentissage,
mais ne corrige pas automatiquement les hypothèses du simulateur.

Les données NASA restent des références expérimentales traçables accessibles
à côté des scénarios. Elles ne sont pas présentées comme les labels de ce modèle.
Voir [NASA.md](NASA.md) pour les sources réellement archivées et utilisées.

## API et reproduction

- `GET /api/incidents/catalog` : familles, composants et disponibilité du modèle.
- `POST /api/incidents/predict` : carte, un résultat ou une erreur par composant.
- `POST /api/runs` : workflow existant, avec `incident_type` et `component_id`.
- `summary.consequences` : critères exposés ; `provenance.incident` : source,
  profil, énergie et limites du calcul.

Le worker et le calcul de carte partagent le verrou de calcul. Les erreurs de
modèle/domaine ne déclenchent jamais une fausse prédiction. Les configurations,
scènes et résultats exportés permettent de retracer les entrées.

```powershell
$env:PYTHONPATH='E:/IGNIS-Valley-dev/app/backend'
& E:/IGNIS-Valley/.venv/Scripts/python.exe E:/IGNIS-Valley-dev/app/tools/remote/generate_incidents.py
& E:/IGNIS-Valley/.venv/Scripts/python.exe E:/IGNIS-Valley-dev/app/tools/remote/train_incidents.py
```

Les scripts utilisent Windows et refusent l'écrasement d'un entraînement existant.
La grande campagne demandée ensuite est indépendante du pilote :
[SPATIAL_CORPUS.md](SPATIAL_CORPUS.md).
Le [U-Net 3D](SPATIAL_MODEL.md) a déjà effectué un entraînement CUDA sur le
pilote de 60 cas, avec poids et évaluation conservés séparément. Il n'est pas
encore utilisé par cette API ni par la page Prédiction.
