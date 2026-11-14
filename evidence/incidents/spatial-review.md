**Contrelecture indépendante du corpus spatial et du réseau 3D — 14 novembre 2026**

Après correction des points ci-dessous, aucun défaut bloquant non résolu n'a été identifié dans le périmètre relu. Le plan comporte bien 1 000 géométries distinctes et 20 cas par géométrie. Les preuves disponibles établissent un entraînement CUDA du pilote de 60 cas et deux nouveaux calculs FDS du corpus. Elles n'établissent pas l'achèvement des 20 000 calculs ni l'entraînement du modèle du grand corpus. La qualité du pilote reste insuffisante pour une activation dans l'interface.

Revue effectuée en lecture seule par `asset_verify` : aucun changement du code, aucune opération Windows ou Git, aucun solveur ni entraînement lancé. Le seul fichier écrit par le contrelecteur est ce rapport. Périmètre : `spatial_dataset.py`, `spatial_network.py`, `generate_spatial_corpus.py`, `train_spatial.py`, puis `run_spatial_study.py` ajouté au périmètre par le coordinateur ; tests spatiaux, documents `SPATIAL_MODEL.md` et `SPATIAL_CORPUS.md`, preuves indiquées ci-dessous.

**Constats initialement ouverts, désormais résolus**

| Point | Défaut constaté | Correction relue et vérification |
| --- | --- | --- |
| P2 — canal entièrement absent | Un cas avec température observée et suie entièrement indisponible satisfaisait le contrat de présence par instant, puis `run_metrics` produisait une moyenne NaN et échouait sur un maximum vide. | Les moyennes et pics du canal absent valent maintenant `None`. Reproduction indépendante en mémoire avant correction : `ValueError: zero-size array to reduction operation maximum which has no identity`. Après correction, les deux canaux ont été vérifiés séparément : score fini et sérialisation JSON stricte valides. Tests de régression présents. |
| P2 — identité pilote/corpus | `--model-id spatial-corpus-v1` sans dataset conservait le dataset pilote par défaut ; aucune association stricte entre modèle, dataset et grille n'était exigée. | `MODEL_DATASETS` et `validate_dataset_identity` imposent les associations, avant création du réseau ; la CLI choisit le dataset correspondant. Contrôle indépendant en mémoire des deux associations admises, de quatre incompatibilités et des deux valeurs par défaut. |
| P2 — interruption des JSON immuables | Le plan et les caches étaient écrits directement dans leur destination finale. Une interruption pendant l'écriture pouvait laisser un JSON partiel empêchant la reprise. | Écriture temporaire complète, flush/fsync, puis publication sans remplacement : rename sous Windows, lien exclusif sous POSIX. Les temporaires de plan sont conservés et ne bloquent plus la reprise. Relecture du code et des tests d'interruption ; aucune injection sur le système de fichiers effectuée par le contrelecteur. |
| P2 — pause à la transition vers CUDA | Une campagne déjà complète, ou un PAUSE créé pendant son dernier calcul, pouvait déclencher l'entraînement malgré ce drapeau. | `wait_for_training` attend la suppression de PAUSE et respecte STOP avant le GPU. Vérification indépendante avec chemins simulés en mémoire : reprise après pause et refus avec STOP. |
| P3 — second appel de compression | Après compression réussie, l'appel suivant relisait `result.json` supprimé avant de détecter les archives existantes ; exception incorrecte et test de cycle en échec. | Le refus des destinations existantes précède maintenant la relecture de l'original. Correction relue ; test du second appel présent. Aucune perte d'original n'avait été identifiée. |

Le dernier ajustement du générateur récupère le temps écoulé depuis `progress.json` uniquement lorsque son empreinte de plan correspond à celle du manifeste et que le temps est fini. Il utilise le maximum avec l'agrégat existant. Cette correction et sa régression ciblée ont été relues ; elle évite de perdre le temps déjà enregistré entre deux agrégations périodiques.

**Invariants contrôlés**

- Exécution indépendante de `build_design({})`, uniquement en mémoire : 1 000 pièces, 20 000 cas, exactement 20 par pièce, partitions de 12 000 / 4 000 / 4 000 cas. Chacune des dix familles structurelles appartient à une seule partition. Un hash indépendant limité aux dimensions du domaine, positions/dimensions des solides et évents, excluant noms, identifiants et matériaux, donne 1 000 géométries distinctes. Chaque pièce possède au moins trois composants.
- Le préflight rejette les doublons physiques compilés et les familles traversant les partitions. Le lecteur et `CaseStore` revérifient les partitions ; le trainer reconstruit les entrées compilées et vérifie aussi les signatures physiques indépendamment des noms.
- Les cibles sont température/suie et quatre statistiques FDS indépendantes. L'origine `simulation`, les versions, les empreintes scène/configuration/deck, les coordonnées, masques, types et temps sont contrôlés. Les valeurs absentes restent masquées ; aucune prédiction, vitesse ou concentration d'oxygène n'est fabriquée comme cible.
- Le JSON complet est conservé dans gzip ; les fichiers bruts le sont dans ZIP. La décompression du JSON et chaque membre brut sont comparés par SHA-256, le ZIP est contrôlé par CRC et tous les tableaux NPZ sont relus avant suppression des originaux. Une interruption de compression conduit à conserver la tentative avant recalcul. Les cas terminés sont vérifiés avant tout archivage ou nouveau calcul.
- Les tableaux du corpus ne sont jamais concaténés en mémoire. Le chargement reste par cas, avec cache LRU de deux cas, minibatches de 2 à 8 instants et plan d'indices borné. La grille du modèle est limitée à 4 096 points ; celle du corpus en contient 1 536. L'allocateur CUDA est plafonné à 5 Gio ou 80 % de la mémoire GPU si cette valeur est inférieure ; le contexte et les bibliothèques restent en supplément.
- CUDA est obligatoire. Le journal `cuda_training_started` est émis après `backward`, vérification/clipping des gradients, `optimizer.step` et synchronisation CUDA. Les meilleurs poids sont copiés et clonés sur CPU. La sélection utilise seulement la validation, puis les poids sélectionnés sont restaurés avant l'évaluation du test.
- L'orchestrateur exige 20 000 succès, 1 000 pièces complètes, zéro échec et l'état `completed` avant de lancer le trainer. STOP et PAUSE sont contrôlés à cette transition. L'index et les entrées sont de nouveau vérifiés par le trainer. Les modèles existants ne sont pas remplacés.

**Preuves d'exécution et limites de leur portée**

Le contrelecteur a lu `evidence/incidents/spatial-pilot/{metadata,evaluation,dataset-snapshot,exited}.json` et `training.jsonl`. L'empreinte canonique du snapshot correspond aux métadonnées ; l'évaluation correspond exactement à leur copie dans les métadonnées. Le snapshot contient 60 cas, séparés en 30 / 15 / 15, avec 12 signatures physiques disjointes entre partitions (6 / 3 / 3). La scène crossflow appartient exclusivement au test.

Le journal rapporte la NVIDIA GeForce RTX 4070 Ti, PyTorch `2.7.0+cu128`, CUDA 12.8, 834 486 paramètres et un premier pas d'entraînement synchronisé à **2026-11-14 16:10:29.752910 UTC**. Il rapporte 20 époques ; l'époque 19 est sélectionnée à 16:12:17.771498 UTC avec zéro évaluation de test préalable, puis la fin est enregistrée à 16:12:20.951442 UTC. Les métadonnées indiquent 118,22 s d'entraînement, 34 106 368 octets au pic alloué et 41 943 040 au pic réservé par PyTorch. Ces nombres ne mesurent pas la mémoire totale du processus.

`evidence/incidents/spatial-verification.json`, produit par la vérification distante du coordinateur, rapporte deux nouveaux cas FDS : la paire microgravité/Terre du scénario overheating de procedural-0000. Chaque cas possède 31 instants et une grille 12×16×8, avec respectivement 3 892 951 et 4 300 745 octets conservés. Le rapport distant atteste les hashes gzip et de tous les membres ZIP ainsi que la conservation des six canaux spatiaux. Le contrelecteur a vérifié la cohérence des sommes de fichiers et l'identité du hash des poids testés en inférence CPU avec les métadonnées du pilote ; il n'a pas téléchargé ni rouvert lui-même les archives Windows. Le rapport d'inférence CPU indique des sorties finies, de formes `[3,320,2]` et `[3,4]`.

Résultats de tests communiqués par les producteurs et le coordinateur, distincts des contrôles indépendants en mémoire ci-dessus :

| Vérification | Résultat communiqué |
| --- | --- |
| Corpus / stockage / cycle | 49 tests réussis en 143,36 s ; Ruff et CLI vérifiés |
| Préflight complet | 1 000 pièces, 4 516 sources ; 24 300 à 34 560 cellules par pièce |
| Réseau et trainer, après corrections | 20 tests réussis |
| Orchestrateur | 9 tests réussis, dont PAUSE après le dernier calcul |
| Suite VPS du coordinateur | 259 réussis, 8 ignorés en 154,30 s ; module Torch et 7 tests Windows ignorés |
| Réseau + orchestrateur sous Windows | 29 tests réussis en 8,35 s |

La suite Windows complète était encore en cours lors du gel de cette revue ; son résultat sera une preuve séparée. Le contrelecteur n'a pas relancé pytest ni installé Torch dans le venv local. Ses reproductions NumPy ont exécuté les fonctions relues extraites de leur AST sans écrire de fichiers ni lancer d'apprentissage.

**Qualité mesurée : ne pas confondre gain composite et qualité générale**

| Test du pilote, moyenne équilibrée par disposition/cas | Réseau | Ambiance constante |
| --- | ---: | ---: |
| Critère composite encodé | 0,378522 | 0,450097 |
| MAE température, °C | 0,118384 | 0,017094 |
| MAE température en région chaude, °C | 5,934874 | 6,049637 |
| MAE suie, kg/m³ | 8,52276 × 10⁻⁸ | 3,47681 × 10⁻⁸ |
| MAE suie en région enfumée, kg/m³ | 2,38145 × 10⁻⁶ | 2,75078 × 10⁻⁶ |
| Erreur du pic de température, °C | 1,129647 | 1,348842 |
| MAE dégagement de chaleur global, W | 161,245 | 91,207 |

Le composite s'améliore d'environ 15,9 %, mais la MAE moyenne de température est multipliée par 6,93 et celle de suie par 2,45. Le gain en région chaude est seulement d'environ 1,9 %. Le composite régresse aussi sur overheating (0,075972 contre 0,007400) et arc (0,081031 contre 0,000617), tandis qu'il progresse pour flaming, smoldering et battery. La documentation présente correctement cette qualité insuffisante et le maintien du modèle spatial hors interface. Aucune probabilité de panne, validation NASA ou certification physique ne découle de ces résultats.

**Empreintes du code relu avant gel**

```text
882c00bada16e86ba6ddba69c22239f06bc199ac66151f7ed9dad8fe9c6629f6  backend/ignis/ml/spatial_dataset.py
cc6be82276fb99ff75e00292d9ffb7cba71116c70b3ae65b6c0c9bcf2c2e1fc1  backend/ignis/ml/spatial_network.py
3db6f726e2d857467037d56d4cfeaa7a0c0b12e4ca42afe9e7a67995ad5c4e22  tools/remote/generate_spatial_corpus.py
175255f842d5974df3d8f8c540aef21761318055976536c2dbd65418539bead4  tools/remote/train_spatial.py
f3fa3c3f05dcbf3ecd42c971b4ad3a39c72630c06335c6b4859a2dd4bbe3aee5  tools/remote/run_spatial_study.py
1279698041cfb6688a2c1e706edd44b36b4a56713374af673ca8b8cd5dc7b482  tests/test_spatial_corpus.py
3d3f015868c0634d2276681eac1411598c86e821728eef0745193641070be52e  tests/test_spatial_network.py
73c8e8e56707e561e3d4034f6f30067618a494a4b971ebb865a656bf55af5d39  tests/test_spatial_study.py
0ef14fb935e6d0f52fae171d041a6bbec294cc3a1111d04cefbca34565b5dabf  docs/SPATIAL_MODEL.md
7969769b6a608bd44818484adbc074619d8ebbb58486161206506ce8bc554a13  docs/SPATIAL_CORPUS.md
2806f05d9fff0e1f59b8b4e270f67a77c08e601c34e56a941727df33836a7cb3  evidence/incidents/spatial-verification.json
```

Le coordinateur a annoncé un ajout documentaire ultérieur : empreintes des six fichiers source effectifs dans les métadonnées des futurs entraînements. Cet ajout reste sous son contrôle de revue et n'est pas couvert par l'empreinte de `train_spatial.py` ci-dessus. Les métadonnées et poids du pilote demeurent leurs artefacts originaux, sans ajout rétroactif de ces hashes.
