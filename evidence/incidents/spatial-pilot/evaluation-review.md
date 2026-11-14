**Contrelecture indépendante — audit de pertinence spatiale, 14 novembre 2026**

Aucun blocage non résolu identifié pour le chemin d'exécution actuel après les corrections ci-dessous. Cette revue couvre le code de l'audit frais, la preuve de rechargement du pilote et les résultats finaux des 60 nouveaux cas exportés localement. Le coordinateur a exécuté et contrôlé séparément les audits individuels sur Windows ; le contrelecteur a vérifié les agrégats, le plan et les tableaux des figures reçus.

Lecture de `evaluate_spatial_generalization.py`, `verify_spatial.py`, `compact_spatial_design.py`, de ses tests et des deux associations d'identité du modèle compact. Lecture ciblée de `locking.py` et `FDSRunner.run` pour contrôler le pool. Aucune opération distante, modification de code, écriture dans les données ou exécution de solveur/apprentissage par le contrelecteur. Seul ce rapport a été écrit.

**Constats corrigés**

- Le préflight écrivait initialement le deck dans le futur dossier de calcul, incompatible avec le refus d'écrasement du solveur. L'échec initial, signalé par le coordinateur avant tout FDS, est corrigé par des dossiers `preflight/<id>` séparés des dossiers `runs/<id>`. La tentative précédente reste conservée.
- Un cas était ajouté aux listes de succès avant ses graphiques et son audit durable. Une erreur ultérieure le comptait simultanément réussi et échoué. Défaut reproduit indépendamment par exécution du bloc réel extrait de son AST : `rows=1`, `failures=1` après une erreur de graphique. Le code actuel prépare les valeurs localement, écrit l'audit, puis ajoute toutes les listes. Les injections d'échec graphique et d'échec d'écriture donnent désormais zéro succès et un échec ; le chemin normal ajoute exactement un élément partout. L'état final exige aussi zéro échec, et un audit incomplet sort avec une erreur.

**Contrôles et portée**

- Le plan prévoit 30 cas sur trois géométries connues du train (`soyuz`, `habitat`, `cargo`, layout 0) et 30 sur trois géométries procédurales nouvelles, indices 1100–1102. Chaque pièce couvre cinq incidents et deux gravités appariées. Les signatures physiques compilées doivent appartenir au snapshot pour le groupe similaire et en être absentes pour le groupe nouveau.
- Les conditions similaires sont effectivement nouvelles : les valeurs d'air 0,08/0,17/0,29/0,36/0,12 m/s et d'oxygène 19,5/22,5/23,5 % diffèrent des valeurs du pilote vérifiées dans son snapshot. Le contrôle de doublon par fingerprint inclut la graine, mais la nouveauté de ce plan ne repose donc pas uniquement sur un changement de graine.
- Le pool nominal contient au plus quatre futurs ; chaque FDS reçoit un seul thread OpenMP et son dossier/verrou propre. Le pool détient le verrou commun `runtime/compute.lock`. Le drapeau PAUSE du grand corpus est exigé. Le budget nominal de 3 000 s coupe les solveurs par leur callback d'annulation et empêche de nouvelles soumissions après échéance ; parsing, compression et finalisation peuvent ajouter du temps. Les anciens cas et le modèle ne sont jamais réécrits.
- Aucun optimiseur ni apprentissage n'est appelé. L'inférence utilise le checkpoint chargé, `eval` et `inference_mode`. Le hash des poids sur disque et celui de l'état en mémoire doivent rester identiques. Le rechargement historique vérifie en plus tous les artefacts du modèle avant/après et les tenseurs CUDA via un hook.
- Les erreurs physiques sont recalculées indépendamment avec les masques par canal et les masques globaux. Vérification en mémoire des observations partielles, statistiques globales absentes, exclusion de t=0 et égalité exacte au seuil. Les moyennes du score sont calculées par cas, puis par disposition, puis entre dispositions ; les détections utilisent explicitement des comptages micro de points/instants observés à t>0.

**Preuve historique relue**

Le fichier `reload-audit/audit.json` décrit une répétition sur les 15 cas de test historiques, pas un nouveau test indépendant. Le contrelecteur a recalculé les moyennes par disposition et les sommes de confusion : elles correspondent au rapport et aux métriques historiques. Les hashes des copies locales du snapshot, des métadonnées et de l'évaluation correspondent aux artefacts inchangés déclarés.

L'inférence synchronisée cumulée vaut 0,4042165 s sur RTX 4070 Ti. Température chaude : TP=0, FN=3, FP=0 ; seulement trois points/instants positifs, corrélés. Suie : TP=2 438, FN=44, FP=17 352, soit rappel 98,23 % et précision 12,32 %. Ces chiffres ne démontrent ni une détection fiable d'incendie ni une probabilité de risque.

**Plan compact vérifié en mémoire**

Le choix de 200 pièces produit exactement 400 cas, répartis en 240 train / 80 validation / 80 test. Chacun des 400 records et chacune des 200 scènes sont strictement identiques à leur entrée du plan original. Les familles restent disjointes, avec huit cas par couple famille structurelle/incident et deux gravités par pièce. Les identifiants modèle/dataset compacts sont distincts, sur la grille 12×16×8 existante. Ce module dessine un sous-ensemble ; il ne lance ni calcul ni copie d'artefacts.

**Résultats finaux des 60 nouveaux cas — vérification indépendante locale**

Les fichiers `expanded-audit/report.json`, `integrity.json`, `plan.json.gz`, `plot-data.json.gz` et `README.md` ont été relus après leur transfert. Le rapport déclare 60/60 cas terminés, aucun échec, en 477,2714344 s ; la somme recalculée des temps d'inférence vaut 4,4074393 s. Les cinq collections locales — plan, métriques modèle/ambiance, diagnostics, temps et figures — portent les mêmes 60 identifiants uniques. Chaque groupe comporte 30 cas et trois dispositions de dix cas ; chacun des cinq incidents possède les deux gravités dans chaque disposition. L'empreinte du plan décomprimé correspond au rapport.

Les onze métriques macro du modèle et de l'ambiance ont été recalculées à partir des lignes par cas, par disposition puis par groupe : elles concordent toutes. Toutes les sommes de confusion et leurs rapports concordent également. Pour le groupe similaire, la température compte TP=0, FN=212, FP=0, TN=213 928 ; la fumée TP=8 076, FN=260, FP=32 007, TN=173 797. Pour les nouvelles géométries, la température compte TP=0, FN=2 713, FP=0, TN=279 275 ; la fumée TP=10 960, FN=8 664, FP=40 332, TN=222 032. Les rappels fumée de 96,9 % / 55,8 % et précisions de 20,1 % / 21,4 % du README sont correctement arrondis. Les MAE température modèle/ambiance 0,1475/0,0708 °C et 0,2914/0,2530 °C, ainsi que les MAE chaudes 6,58/21,84 °C, sont confirmées.

Les séries de maxima exportées ne dépassent le seuil chaud dans aucun des 60 cas : maximum modèle de 21,0330288 °C, seuil de 25 °C. Cela confirme indépendamment l'absence totale de prédictions chaudes dans les points de gaz échantillonnés, soit zéro détection parmi 2 925 couples point/instant positifs. Les erreurs de pic des deux canaux correspondent aux séries exportées. Chaque instant des trames spatiales correspond au maximum FDS du canal, et les maxima de leurs tableaux correspondent aux séries. L'exemple extrême du README est exact : `novel_geometry-perimeter-overheating-microg`, 498,8963013 °C pour FDS contre un maximum modèle de 20,4950257 °C. Le rendu emploie les mêmes positions, instant et échelle par paire ; aucune interpolation n'est appliquée.

Aucun désaccord scientifique relevé avec le README : l'insuffisance du pilote pour représenter les foyers est étayée, tandis qu'une cause unique et une attribution à la seule géométrie ne sont pas établies. Ces contrôles locaux portent sur les agrégats et les tableaux exportés ; les champs complets FDS ne sont pas présents ici et leurs moyennes physiques n'ont pas été recalculées à nouveau depuis les sorties brutes. `integrity.json` consigne le contrôle distant du coordinateur : 60 audits durables égaux aux agrégats. L'empreinte déclarée de l'évaluateur effectivement exécuté, `a60994adc1ede8e1069f2e0eda9e01cb7cafaebd721480953a7ede442ef4bf65`, est identique dans le plan et le contrôle d'intégrité. Cet essai utilise la version antérieure au renforcement de l'atomicité ; l'absence d'échec et les audits durables contrôlés écartent le défaut de double comptage pour cet essai.

**Limites pour décider des calculs suivants**

Chaque groupe frais ne comporte que trois géométries. Les couples incident/vitesse d'air diffèrent entre les groupes à cause du décalage du numéro de pièce : une différence de score ne peut pas être attribuée à la seule géométrie. Les erreurs incluent l'état initial imposé, tandis que les détections l'excluent ; le rapport l'annonce. Les futures conclusions doivent présenter les erreurs par groupe avec leur référence ambiante et le nombre de cas réussis, sans traiter les milliers de points corrélés comme autant d'expériences indépendantes. Si cet audit sert à choisir une nouvelle fonction de perte ou un nouveau modèle, il devient un diagnostic de développement ; une évaluation finale supplémentaire doit rester séparée de ces choix.

Empreintes du code et de la preuve relus :

```text
c66970b81add061c05e70e371a42f639697b577eeb6407e9f08a30d9b583ad7c  tools/remote/evaluate_spatial_generalization.py
9f10c4d14927efc2c85cab13c83f3fc38fd6cca0d9013cfe798dd5c260ed0198  tools/remote/verify_spatial.py
e2a34e2c124e77c4222d2ee2b8ba8f85c85f772a739c0e011d426286fd0e08f3  tools/remote/compact_spatial_design.py
4ac308b941bf63a5a3e96681ce802ae8f469ec8fc37b1679da61a45dbdef22a8  tests/test_compact_spatial_design.py
1e05e3ea657982543866c4343b8546c4a2537d651f7225eac0560d6f47217b0c  evidence/incidents/spatial-pilot/reload-audit/audit.json
78d552d76ce9527e570a333ee57c19d03eacc45b53fb527c7c8fc7098ef29933  evidence/incidents/spatial-pilot/expanded-audit/report.json
200e71cb35d6ab2c489beb2ef2a45777eae7bfde7cd2eaccffa25e94eeb3363e  evidence/incidents/spatial-pilot/expanded-audit/integrity.json
cf41e65395a95fb070b68ba195e540049da48d7c3f7ce1529dff884cc339322f  evidence/incidents/spatial-pilot/expanded-audit/plan.json.gz
c11794ae44671dac8d886de7ad762ddffc244f6dc6d1e06eadd5a0eaad59778f  evidence/incidents/spatial-pilot/expanded-audit/plot-data.json.gz
205988e56c371d5e67773892b0f60ec31b9631b12e8db91abfc593cce26ff173  evidence/incidents/spatial-pilot/expanded-audit/README.md
```

Les reproductions de cette revue sont restées en mémoire, sans réexécuter les suites pytest ni installer Torch. Le rapport d'exécution frais et ses empreintes distinguent la version réellement utilisée par la tentative Windows ; une correction locale pendant un processus déjà lancé ne modifie pas son code chargé.
