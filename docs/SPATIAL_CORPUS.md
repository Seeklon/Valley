# Corpus spatial procédural — spatial-corpus-v1

Le générateur [generate_spatial_corpus.py](../tools/remote/generate_spatial_corpus.py)
prépare **1 000 compartiments distincts × 20 scénarios = 20 000 calculs FDS**.
Les observations doivent provenir de FDS 6.11.1 exécuté sur le poste Windows.
Le nombre planifié n'est pas un nombre de calculs déjà terminés : consulter
`progress.json` et l'index des cas pour connaître l'avancement réel.

Ce corpus sert à apprendre la température et la concentration de suie dans un
environnement 3D **sous l'hypothèse d'un incident donné**. Il n'apporte pas de
fréquence de défaut électrique, de probabilité d'allumage d'un équipement réel,
ni de garantie de généralisation à un véhicule. Les scénarios ne sont pas des
mesures NASA. Le manifest porte `nasa_experimental_labels: false`.

## Plan physique et séparation des données

La graine de conception est `2026111401`. Chaque pièce contient :

- des dimensions variables, de 2,4–6 m en X, 3,2–6 m en Y et 2,6–4,8 m en Z ;
- 6–18 obstacles sans recouvrement, avec positions, tailles et hauteurs variables ;
- 3–6 composants annotés sur les faces supérieures des obstacles, tous utilisés
  dans les 20 scénarios de cette pièce ;
- des substrats explicites aluminium, acier ou isolant ; une couche PMMA ou
  cellulose peut couvrir la face supérieure, séparément du substrat ;
- une épaisseur thermique de 0,8–8 mm, distincte de la hauteur géométrique ;
- deux évents opposés, d'axe X ou Y, de taille et position variables ;
- un maillage adapté au volume, ciblant environ 24 000 cellules.
  Le préflight refuse tout maillage hors de 12 000–60 000 cellules.

`config.mesh_cell_m` conserve la taille nominale demandée ; les largeurs
effectives selon X/Y/Z sont `manifest.mesh.cell_size_m`. La forme et le nombre
réels de cellules sont conservés dans `manifest.mesh` et dans le rapport de
préflight. Une taille nominale scalaire ne remplace pas ces trois largeurs.

| Partition | Familles structurelles | Pièces | Calculs |
| --- | --- | ---: | ---: |
| train | perimeter, central-island, parallel-aisles, staggered, corner-banks, radial-clusters | 600 | 12 000 |
| validation | cross-aisle, split-bays | 200 | 4 000 |
| test | baffled, double-island | 200 | 4 000 |

Une **famille structurelle entière** appartient à une seule partition. Les
20 scénarios et tous les instants d'une pièce y restent ensemble. Les
empreintes des géométries compilées empêchent de placer la même physique sous
deux identifiants différents. Ces familles sont des motifs procéduraux de
boîtes ; elles ne représentent pas dix familles de véhicules réels.

Les familles sont intercalées par groupes de pièces. Les calculs 1–20
appartiennent à train, 21–40 à validation, 41–60 à test. Un lancement limité à
60 nouveaux cas couvre donc immédiatement trois pièces et les trois
partitions, mais ne suffit pas à évaluer la généralisation aux 1 000 pièces.

Chaque pièce combine cinq incidents (`overheating`, `arc`, `flaming`,
`smoldering`, `battery`), deux gravités (1 g et 0,0001 g), et deux conditions.
Un plan Latin hypercube à deux strates fait varier la puissance entre
500–3 000 W, la vitesse d'air entre 0,05–0,4 m/s et l'oxygène entre 18–24 %.
Les conditions, le composant et la graine turbulente sont identiques dans
chaque paire de gravité. Le départ dure 1 s pour l'arc, 10 s pour les autres
incidents ; le calcul dure 30 s. Le modèle de source et ses limites sont
décrits dans [INCIDENT_PHYSICS.md](INCIDENT_PHYSICS.md).

Le préflight compile une fois par pièce, puis vérifie chaque annotation de
source sur ses solides discrétisés. Il valide aussi toutes les configurations.
Il ne compile pas les 20 000 decks d'avance. Les petits résultats de préflight
sont protégés par empreintes d'entrée et de sortie, puis réutilisés à la
reprise. L'admissibilité du compilateur ne prouve ni le succès du solveur ni la
validité physique du modèle.

## Lancer et reprendre sur Windows

Préconditions : environnement Python du dépôt installé, exécutable FDS présent,
code et modèle de matériaux stabilisés, au moins **20 GiB libres** avant le
prochain calcul. Aucun accès Ollama ni service LLM n'est utilisé. Un seul FDS
tourne à la fois, avec **quatre threads OpenMP**. Le verrou du poste est partagé
avec les calculs interactifs via `runtime/compute.lock`.

Depuis le dépôt `E:/IGNIS-Valley-dev/app`, dans le Python configuré pour IGNIS :

```powershell
python tools/remote/generate_spatial_corpus.py --home E:/IGNIS-Valley-dev --limit 60
```

Le chemin FDS par défaut est
`E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe`.
L'option `--fds` permet de fournir un autre exécutable, dont l'empreinte fera
partie du plan. Le point d'entrée refuse les calculs réels sur une autre
plateforme ; le compilateur et les tests sans solveur restent portables.

Pour enchaîner automatiquement l'entraînement CUDA après les 20 000 succès,
utiliser `tools/remote/run_spatial_study.py --home E:/IGNIS-Valley-dev`.
Ce lanceur respecte STOP et PAUSE avant l'entraînement. Il ne remplace aucun
modèle déjà publié ; voir [WINDOWS.md](WINDOWS.md) et [SPATIAL_MODEL.md](SPATIAL_MODEL.md).

Après vérification des cas et mesure du coût réel :

```powershell
python tools/remote/generate_spatial_corpus.py --home E:/IGNIS-Valley-dev
```

`--limit` compte les **nouveaux succès de cette invocation**, sans réduire le
plan immuable. `--limit 0` effectue le préflight et les vérifications de reprise
sans nouveau calcul. `--max-runs` reste un alias.

Les commandes de contrôle suivantes utilisent PowerShell :

```powershell
New-Item -ItemType File E:/IGNIS-Valley-dev/datasets/spatial-corpus-v1/PAUSE
Remove-Item E:/IGNIS-Valley-dev/datasets/spatial-corpus-v1/PAUSE
```

`PAUSE` laisse le calcul en cours se terminer, puis attend sa suppression en
libérant le verrou de calcul. Le lanceur vérifie toutes les deux secondes.
`STOP` laisse également terminer le cas puis ferme le lanceur :

```powershell
New-Item -ItemType File E:/IGNIS-Valley-dev/datasets/spatial-corpus-v1/STOP
```

Pour reprendre, supprimer `STOP` et relancer la même commande. Les fichiers
`PAUSE` et `STOP` ne sont jamais supprimés automatiquement.

Un échec ferme le lanceur avec `state=failed` et conserve ses sorties.
Au redémarrage explicite, chaque cas terminé est vérifié avant tout nouveau
calcul. Les tentatives incomplètes ou échouées sont déplacées sous
`attempts/<run-id>/<numéro>/`, avec leur ancien checkpoint, puis recalculées.
Un fichier final altéré, une modification du plan, du compilateur, du modèle
de matériaux ou du binaire FDS bloque la reprise. Conserver ces artefacts et
créer une nouvelle version de corpus si les hypothèses doivent changer.

## Stockage et intégrité

Dossier : `E:/IGNIS-Valley-dev/datasets/spatial-corpus-v1`.

```text
plan.json                 conception, empreintes et préflight immuables
preflight/<layout>.json   petits résultats compilateur mis en cache
manifest.json             agrégat périodique des checkpoints
records/<run>.json        checkpoint atomique de chaque cas
progress.json             état courant léger pour l'interface
index.json                index immuable une fois les 20 000 cas terminés
runs/<run>/
  scene.json
  config.json
  manifest.json
  ignis.fds
  result.json.gz
  fields.npz
  raw-fds.zip
attempts/<run>/<numéro>/   tentatives précédentes conservées
```

Les quatre fichiers d'entrée restent lisibles. `result.json.gz` conserve
**octet pour octet le JSON original**, ses six canaux spatiaux (température,
suie, oxygène, U/V/W), ses capteurs, ses statistiques globales et sa provenance.
`raw-fds.zip` conserve les fichiers bruts du solveur, notamment CSV et logs.
`fields.npz` contient seulement les cibles spatiales température/suie et les
statistiques globales nécessaires au modèle actuellement développé.

La compression vérifie la décompression du JSON par SHA-256, chaque membre
ZIP par CRC et SHA-256, et la lecture de chaque tableau NPZ. Les originaux
JSON/CSV/log ne sont supprimés qu'après ces vérifications ; les archives et
leurs empreintes restent dans le checkpoint. Une compression interrompue
forme une tentative conservée, pas un succès réutilisable.

Les checkpoints de cas sont publiés atomiquement après le passage à
`running`, `completed` ou `failed`. L'agrégat est écrit tous les 100 nouveaux
succès et aux transitions pause/arrêt/échec/fin. Lire seulement
`manifest.runs` pendant la génération peut donc sous-estimer les succès :
utiliser `read_spatial_index`, qui fusionne `records/*.json`, ou
`progress.json`. Le plan, les caches et l'index final sont publiés après
écriture complète et fsync, sans remplacer un fichier existant. Les
temporaires cachés laissés par une interruption sont conservés ; ils ne
bloquent pas la reprise du préflight.

Le lanceur maintient les compteurs par partition, incident et famille
structurelle, ainsi que les pièces entièrement terminées. L'ETA repose sur la
moyenne des temps FDS réellement terminés. Elle exclut les pauses futures,
échecs et vérifications. Le coût disque et le temps total doivent être
**mesurés sur les premiers cas du nouveau maillage** : les chiffres du pilote
grossier de 60 cas ne sont pas extrapolables. La réserve disque peut arrêter
la campagne avant 20 000 cas ; elle ne garantit pas que le volume complet
tient sur le disque disponible.

Le 14 novembre 2026, les deux premiers cas ont réellement été exécutés puis
relus : 31 instants et 1 536 points chacun, 8,672 s et 28,485 s de solveur,
3 892 951 et 4 300 745 octets conservés. Les empreintes gzip et de chaque membre
ZIP ont été revérifiées. Ces deux cas de surchauffe ne représentent pas encore
le coût de toutes les familles. Preuve :
[spatial-verification.json](../evidence/incidents/spatial-verification.json).
La campagne continue a ensuite repris les cas conservés ; Pause/Reprendre ont
été testés dans le navigateur avec le vrai solveur. Le compteur de l'interface
et `progress.json` donnent l'avancement ultérieur, sans l'assimiler au plan.

## Contrat NPZ et chargement progressif

Implémentation : [spatial_dataset.py](../backend/ignis/ml/spatial_dataset.py).
`F` désigne le nombre d'instants réellement exportés par FDS et
`P = 12 × 16 × 8 = 1 536`.

| Clé | Forme | Type et sens |
| --- | --- | --- |
| time_s | F | float64, temps FDS exacts, strictement croissants |
| temperature_c, smoke_kg_m3 | F × P | float32, °C et kg/m³ ; NaN si indisponible |
| valid_mask | F × P | bool, points de gaz selon géométrie compilée |
| field_mask | F × P × 2 | bool, gaz ET valeur finie pour chaque canal |
| positions_m | P × 3 | float64, coordonnées compilées faisant autorité |
| bounds_m | 3 | float64, dimensions du domaine en mètres |
| shape | 3 | int32, forme d'échantillonnage |
| globals | F × 4 | float32, statistiques FDS indépendantes |
| global_mask | F × 4 | bool, disponibilité de chaque statistique |
| global_keys | 4 | Unicode, noms des statistiques |
| metadata_json | scalaire | Unicode JSON, schéma et provenance |

Ordre des cibles : `temperature_c`, `smoke_kg_m3`.
Ordre des statistiques : `temperature_max_c`, `temperature_mean_c`,
`smoke_mean_kg_m3`, `heat_release_w`. Ce sont les mesures du domaine complet
FDS, pas des agrégats reconstruits depuis les 1 536 points.

L'ordre P reste celui du manifest. `position_grid_indices(positions_m, shape)`
retourne les indices entiers correspondants sans supposer l'ordre des points.
Le compilateur courant utilise X/Y/Z, Z le plus rapide, et des coordonnées
alignées sur les cellules qui peuvent être non uniformes. Aucun reshape
supposant des centres uniformes, rééchantillonnage temporel ou remplissage
artificiel de vitesse/oxygène n'est effectué.

```python
from pathlib import Path
from ignis.ml.spatial_dataset import iter_spatial_cases

dataset = Path("E:/IGNIS-Valley-dev/datasets/spatial-corpus-v1")
for case in iter_spatial_cases(dataset, split="train"):
    temperature = case["temperature_c"]
    available = case["field_mask"][:, :, 0]
    # Traiter ce cas, puis libérer ses tableaux avant le suivant.
```

Le lecteur ne charge qu'un cas à la fois, avec un instantané des métadonnées.
Par défaut, un corpus incomplet est refusé. `allow_incomplete=True` est une
option explicite pour un entraînement de prototype pendant la génération ;
seuls les cas terminés sont alors chargés. Le lecteur supporte également le
pilote historique à 8 × 10 × 4 via ses `result.json` et leurs empreintes.

À chaque chargement, il vérifie les empreintes disponibles, les entrées
compilées, le deck, l'origine `simulation`, les versions du compilateur et des
matériaux, les coordonnées, masques, types numériques et instants initial/final.
Les valeurs nulles restent indisponibles. Les cellules solides ne portent
aucune cible gazeuse. Une prédiction ML n'est jamais acceptée comme observation
FDS pour l'entraînement.

## Vérifications et limites

`tests/test_spatial_corpus.py` couvre le plan complet, le préflight des
1 000 pièces, la séparation des familles, l'intégrité et la compression,
ainsi que pause, arrêt, reprise, réserve disque et index final. Les tests
de cycle utilisent un faux solveur dans des répertoires temporaires ; ils ne
constituent pas des simulations FDS et ne sont jamais ajoutés au corpus.

```bash
.venv/bin/pytest -q tests/test_spatial_corpus.py
.venv/bin/ruff check tools/remote/generate_spatial_corpus.py backend/ignis/ml/spatial_dataset.py tests/test_spatial_corpus.py
```

La résolution et la chimie de démonstration ne valident pas l'extinction en
microgravité. Les évents échangent avec un réservoir ambiant, sans boucle HVAC
fermée. Les incidents arc/batterie/couvant sont des équivalents de chaleur et
d'émissions, sans circuit, plasma ou électrochimie résolus. Le revêtement
réactif couvre la face supérieure ; le substrat n'est pas un modèle multicouche
complet de câble. Voir [INCIDENT_PHYSICS.md](INCIDENT_PHYSICS.md).

La diversité de ce corpus permet une évaluation spatiale plus exigeante ;
elle ne garantit pas qu'un réseau surpasse une référence simple. Les modèles
doivent être comparés à des baselines sur validation/test, y compris dans les
régions chaudes et enfumées, avant d'interpréter leur visualisation comme une
prédiction utile.
