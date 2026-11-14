# IGNIS 3D — plan de réalisation figé

Version 2 — 14 novembre 2026. Ajout Soyouz demandé par Thomas. Dépôt : Seeklon/Valley.

## Résultat attendu

Une application web accessible depuis le PC Windows de Thomas et par Tailscale,
avec une scène Blender détaillée, plusieurs variantes physiques et des modèles
réellement entraînés, chargés au démarrage. L'utilisateur choisit une scène,
modifie ventilation, atmosphère, matériau, gravité et allumage, lance une
simulation physique ou une prédiction, observe son évolution en 3D et compare
les mesures. Il peut générer une campagne reproductible et exporter ses données.

Le challenge NASA exige également de résumer, classer et interpréter les résultats
expérimentaux : chaque matériau, cas de référence et résultat scientifique reste
relié aux sources pertinentes. Les mesures NASA, simulations et prédictions ont
des provenances distinctes.

## Architecture retenue

- PC Windows : Blender, calcul physique FDS sur CPU, apprentissage PyTorch sur
  CUDA, stockage des campagnes, API et service web. Le VPS sert au code, au plan,
  à la coordination et à la conservation de petites preuves. Pas de calcul ML,
  de campagne CFD ou de rendu lourd sur le VPS.
- Frontend : React, TypeScript strict, Three.js ; visualisation GLB, sélection
  d'objets, paramètres, transport visible, chronologie, courbes et comparaison.
- Backend : Python, FastAPI, validation des entrées, registre des scènes et
  modèles, file de jobs persistante. FDS épinglé comme premier backend physique.
- Blender : génération Python reproductible du compartiment et des variantes,
  fichier .blend modifiable, export GLB, images de présentation et proxy physique.
- Données : JSON versionné pour les contrats ; Parquet pour séries/paramètres ;
  stockage spatial compressé par blocs pour les essais sélectionnés. Quotas
  mémoire/disque et manifestes avec empreintes.
- ML : référence tabulaire, puis modèle spatial compact ; validation sur familles
  de scènes réservées. Modèles livrés avec poids, métriques, variables d'entrée,
  plages de validité, version du simulateur et identifiants des datasets.
- Interprétation documentaire : Codex via son installation Windows et sa session
  authentifiée, à partir des faits NASA archivés. Aucun appel Ollama par IGNIS,
  conformément à la correction explicite de Thomas.

## Contrat de scène

Une scène associe géométrie visuelle et proxy de calcul, unités SI, matériaux
thermiques, atmosphère, vecteur de gravité, ventilation (inlet/outlet, débit ou
vitesse, ouverture, commande temporelle), source d'allumage, capteurs, événements,
maillage, durée, fréquence d'enregistrement, graine et provenance. Les matériaux
graphiques ne sont pas interprétés comme propriétés de combustion.

Le premier environnement est un compartiment spatial original et détaillé,
inspiré d'équipements de cabine : racks, panneaux, câbles, conduits, grilles,
trappes, éclairage, équipements et repères. Il n'est pas présenté comme une
reconstruction certifiée d'un module réel. Quatre scènes partagent le contrat :
habitat, ventilation transversale, zone cargo et capsule inspirée du Soyouz.
Cette capsule est une interprétation originale du module de descente, avec trois
sièges, instrumentation et hublots ; aucune géométrie officielle n'est revendiquée.

## Physique et validité

1. Géométrie fermée, contrôle des unités, intersections, ouvertures, détails
   non résolus et cohérence des conditions aux limites.
2. Écoulement à froid 3D, stabilisation, transport de chaleur et d'espèces.
3. Mode `prescribed_source` : puissance et émissions imposées ; prédiction de
   leur transport. Ces résultats ne constituent pas une prédiction de l'allumage.
4. Mode `coupled_combustion` : échauffement/décomposition/consommation des matériaux
   et propagation dans les limites des modèles et paramètres disponibles.
5. Allumage thermique et résistif électrique avec coupure. Arcs, plasma et
   emballement des batteries ne sont pas implicitement couverts par I²R.
6. Comparaison normale/microgravité ; gravité partielle exploratoire, sans
   revendication de validation NASA à partir de données absentes de PSI.
7. Contrôles de conservation, stabilité, convergence ciblée et cas expérimentaux.
   Réserver des essais à la validation ; séparer calibration et test.

Le moteur 2D antérieur (/home/platform-admin/projects/ignis-lab) est exploratoire
et non calibré. Ses données ne sont ni des mesures NASA ni une vérité de validation.
Un obstacle technique ne justifie pas de remplacer silencieusement le moteur 3D
par une animation ou une interpolation de résultats préfabriqués.

## Jalons et preuves

| ID | Livrable | Preuve d'acceptation |
|---|---|---|
| A | Poste Windows et exécution distante | Identité SSH, inventaire CPU/RAM/GPU/disque, CUDA exercé, dossier Valley séparé, quotas et absence d'interférence avec les autres travaux. |
| B | Scènes et Blender | Script reproductible, .blend, GLB, quatre scènes dont Soyouz, matériaux et ventilation associés, rendus inspectés et paquets importables. |
| C | Simulation 3D | Cas ventilation/chaleur puis combustion couplée réellement exécutés, champs et métriques exportés, diagnostics et tests pertinents. |
| D | Sources NASA | Données importées avec DOI/version/hash, cas comparables, documentation des écarts et données manquantes, calibration et test distincts. |
| E | Campagnes | Environ 100 simulations pilotes valides, génération contrainte, reprise et export testés, débit et volume mesurés avant augmentation. |
| F | Modèles entraînés | Poids issus d'une exécution d'entraînement conservée ; référence et modèle spatial évalués ; aucun chevauchement des familles train/test ; limites publiées. |
| G | Application | Modèles chargés au démarrage, quatre scènes, variables modifiables, lancement réel, chronologie 3D et courbes, comparaison et téléchargement. |
| H | Livraison vérifiée | URL accessible, test navigateur réel sur le parcours complet, guide Windows, versions verrouillées, revue indépendante, sources et preuves commitées. |

## Gestion des ressources et campagnes

- Hypothèse de départ : 12 Go de VRAM, 16 Go RAM ; inventaire réel prioritaire.
- Calcul GPU exclusif et coopératif : respecter Ollama et les autres jobs,
  ne pas tuer de processus tiers. Échantillonnage mémoire et annulation propre.
- Simulation, génération et entraînement découplés. Une tâche lourde à la fois
  initialement ; concurrence déterminée par mesures.
- Les runs ont des identifiants uniques, seed, hashes du code/scène/données et
  statuts persistants. Reprendre un job vivant, ne pas relancer après simple timeout.
- Séparer géométrie, famille de scénarios, run et frame. Partitionner par famille
  avant d'augmenter les données ; les frames voisines ne sont pas indépendantes.
- Estimer stockage avant lancement. Une sortie 128³ × 8 champs float32 × 300
  instants représente environ 20 Go bruts. Conserver des séries partout et des
  volumes sélectifs/compressés. Ne pas promettre un débit avant benchmark.

## Communication et organisation

- Thomas demande des mises à jour détaillées et des visuels réguliers : premiers
  rendus Blender, évolution de l'interface, champs simulés puis comparaison ML.
- Plan et reprise persistants sur le VPS, sous ce dépôt. Mettre REPRISE.md à jour
  à chaque passage de relais ; les preuves réelles priment sur ce document.
- Appliquer Agentic comme point d'entrée méthodologique, sans importer les
  conventions du produit Seeklon. Lots indépendants et revue via sous-agents
  conformément à sa policy de collaboration.
- Aucun secret, clé, accès personnel, environnement local ou dataset massif dans Git.
- Ne déclarer le goal terminé que lorsque tous les jalons requis ont leurs preuves.

## Sources de départ vérifiées

- Challenge : https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/?tab=details
- PSI combustion : https://psi.nasa.gov/physci/repo/search?q=combustion
- BASS-II : https://psi.nasa.gov/physci/repo/data/investigations/PSI-25 — DOI 10.60555/4qc4-de67.
- BASS : https://psi.nasa.gov/physci/repo/data/investigations/PSI-26 — DOI 10.60555/58h4-dy80.
- Saffire-I : https://psi.nasa.gov/physci/repo/data/investigations/PSI-98 — DOI 10.60555/0t15-1z43.
- Rapport BASS-II : https://ntrs.nasa.gov/citations/20210011385
- Modélisation Saffire V : https://ntrs.nasa.gov/citations/20240008602 — transport avec sources mesurées, pas modélisation directe de la flamme.
- FDS : https://pages.nist.gov/fds-smv/

Les trois tableaux PSI ont été contrôlés et archivés avec leur provenance dans
`data/sources/`. Les métriques, écarts et limites sont dans `docs/NASA.md`.
Le tableau BASS-II a 129 identifiants ; ce nombre ne garantit pas 129 labels
d'apprentissage complets. Le détail du challenge signale l'absence actuelle de
données de combustion en gravité partielle dans PSI.
