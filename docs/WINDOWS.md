# Utilisation et exploitation sur Windows

Poste de calcul : Windows, Ryzen 7 3700X, 16 Go de RAM, RTX 4070 Ti de 12 Go. Le projet est
isolé dans `E:/IGNIS-Valley`. Le VPS conserve le code et les petites preuves ;
les rendus, simulations et entraînements sont exécutés sur le PC.

## Ouvrir et gérer l’application

- Sur le PC : `http://127.0.0.1:8765`.
- Depuis un appareil du même réseau Tailscale :
  `https://desktop-m4hkr86.tail609f26.ts.net:8443`.
- Le PC doit être allumé et Tailscale connecté. Le service est privé au tailnet.
  Ollama conserve son adresse HTTPS443 existante.

PowerShell, démarrage indépendant de la session SSH :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:/IGNIS-Valley/app/tools/windows/start-ignis.ps1
```

Arrêt du service identifié, avec annulation propre du calcul en cours :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:/IGNIS-Valley/app/tools/windows/stop-ignis.ps1
```

Le démarrage est idempotent. Les journaux et identités des processus restent dans
`E:/IGNIS-Valley/runtime/service/`. L’application continue après fermeture du
terminal ; après un redémarrage du PC, utiliser de nouveau la commande de départ.
Il n’y a pas de tâche automatique à l’ouverture de session.

## Parcours

1. Choisir Habitat, Cargo, Ventilation transversale ou Soyouz.
2. En **Simulation physique**, régler gravité, atmosphère, ventilation et source.
   Le mode prescrit étudie le transport d’une puissance nominale. Le mode couplé
   calcule le dégagement chimique depuis l’échauffement et la pyrolyse du coupon.
3. Pour un départ électrique, choisir chauffage résistif et fournir I/R.
   `I²R` représente la chaleur déposée dans le solide ; la HRR chimique reste
   calculée séparément. Ce mode ne couvre ni arc ni batterie.
4. En **Prédiction**, sélectionner un des deux modèles préchargés. Le réseau
   spatial produit les observations 3D et les métriques ; ExtraTrees produit les
   courbes seules. Les demandes hors domaine sont refusées avant calcul.
5. Lire la chronologie, inspecter les champs et courbes, conserver une référence
   de comparaison ou télécharger le résultat. Les points dans les obstacles
   restent sans mesure ; les 320 points affichés sont un échantillonnage des cellules du solveur.
6. Générer une campagne avec graine et plages de paramètres. Le calcul est
   séquentiel. L’export contient les métriques Parquet, configurations et
   provenances ; les champs sont dans les exports de chaque run.
7. Consulter les observations NASA et l’interprétation. Le classement explicite
   mesure la pertinence documentaire. Codex interprète les faits archivés avec
   citations ; une synthèse extraite des faits reste disponible s’il ne répond pas.

Le lanceur détecte l’installation Windows de Codex et utilise son authentification
existante. Aucun appel Ollama n’est effectué par IGNIS. L’exécutable peut aussi
être précisé avec `-CodexExecutable 'C:/chemin/codex.exe'`. Le bouton NASA envoie
à Codex la question, les paramètres du scénario et les faits publics archivés ;
les poids, fichiers Blender et volumes simulés ne sont pas transmis. L’accès
au service Codex nécessite Internet et une session Codex connectée.

Chaque interprétation utilise une session éphémère, un répertoire temporaire,
une sortie JSON structurée et aucun outil shell, application ou recherche web.
Une seule interprétation s’exécute à la fois, avec un délai maximal de 110 secondes.
L’interface indique si la réponse provient de Codex ou de la synthèse documentaire
de secours. Chaque paragraphe doit citer une source autorisée ; les mesures
chiffrées restent dans les faits archivés affichés séparément. Les références
inconnues et les nouveaux chiffres sont refusés. Ce contrôle ne prouve pas à lui
seul que chaque phrase générée est scientifiquement exacte ; l’interface conserve
cette limite à côté du texte.

Les annotations Blender et l’import d’un environnement sont expliqués dans
[SCENES.md](SCENES.md). Les scènes importées doivent être inscrites au catalogue,
compilées et simulées avant de former un nouveau modèle ; les poids livrés
refusent une scène physique modifiée, même si son identifiant reste identique.

## Données, ressources et reprise

| Dossier | Contenu |
|---|---|
| `app/` | Code et assets de l’interface. |
| `app/scenes/generated/` | Fichiers Blender, GLB et images. |
| `runtime/jobs.sqlite3` | File persistante, runs et campagnes. |
| `runtime/runs/<id>/` | Entrées, fichier FDS, mesures et résultats. |
| `runtime/models/` | Poids préchargés, métriques et historique d’entraînement. |
| `datasets/pilot-v2/` | 96 simulations brutes, manifestes, Parquet et NPZ. |
| `runtime/service/` | Identité du service, demandes d’arrêt et journaux. |
| `G:/IGNIS-Valley-archives/` | Archives de livraison avec empreintes. |

La sauvegarde initiale vérifiée est
`G:/IGNIS-Valley-archives/ignis-pilot-v2-models-20261114T112409Z.zip` :
1 351 fichiers, 485 591 338 octets avant compression, 157 279 419 octets archivés.
Elle contient `datasets/pilot-v2/`, `runtime/models/` et leur manifeste ; chaque
entrée a été relue et comparée à son SHA-256. L’empreinte de l’archive figure dans
[la preuve de sauvegarde](../evidence/archive-verification.json). Les scènes et
le code sont versionnés dans Git.

Pour créer une nouvelle archive cohérente, terminer les calculs puis exécuter :

```powershell
& E:/IGNIS-Valley/.venv/Scripts/python.exe E:/IGNIS-Valley/app/tools/remote/archive_delivery.py
```

Le script prend les verrous dataset/calcul et crée un nouveau fichier horodaté.
Pour restaurer, arrêter IGNIS, vérifier le SHA-256 avec `Get-FileHash`, extraire
d’abord dans un dossier distinct, puis remettre les deux dossiers à leur place
après avoir préservé les éventuelles données plus récentes.

Une seule instance possède la file. Le verrou de calcul sérialise FDS et les
opérations ML coopératives. Les processus FDS sont contenus dans des Jobs Windows.
Les calculs interrompus passent en échec au redémarrage ; ils ne sont jamais
rejoués silencieusement. Les travaux encore en attente sont conservés.

Quotas initiaux : 8 calculs interactifs en attente, 100 cas par campagne,
2 000 runs par runtime, 8 Go libres réservés, une heure maximum par calcul FDS.
Les dimensions de maillage et sorties sont aussi plafonnées par le compilateur.
Archiver les résultats avant une nouvelle campagne importante. Ne pas supprimer
un runtime pendant qu’un service, un entraînement ou une campagne le possède.

## Reconstruire l’environnement

Python 3.11 et Node 22 pour le build. Les versions Python sont épinglées dans
`pyproject.toml`, les dépendances web dans `web/package-lock.json`.

```powershell
py -3.11 -m venv E:/IGNIS-Valley/.venv
& E:/IGNIS-Valley/.venv/Scripts/python.exe -m pip install -e 'E:/IGNIS-Valley/app[test]'
& E:/IGNIS-Valley/.venv/Scripts/python.exe -m pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cu128
Set-Location E:/IGNIS-Valley/app
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/remote/install_tools.py
Set-Location web
npm ci
npm run build
```

Blender 4.5.9 LTS et FDS 6.11.1 sont téléchargés depuis leurs éditeurs et vérifiés
par SHA-256. L’archive autoextractible FDS est extraite localement ; elle ne modifie
pas le PATH système ni les services Windows.

Pour les modèles, restaurer l’archive vérifiée dans `runtime/models`, ou
reproduire le pilote et l’entraînement sur le PC :

```powershell
Set-Location E:/IGNIS-Valley/app
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/remote/generate_pilot.py
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/remote/train_models.py
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/remote/audit_models.py
```

Le pilote existant conserve les scènes exactes de sa génération. Si seule une
scène supplémentaire doit être ajoutée, `--scene soyuz` cible cet ajout.
Une empreinte d’entrée différente est refusée ; conserver les labels existants
et utiliser un nouveau dataset pour changer la physique. Les légendes/aperçus
ajoutés après le pilote peuvent aussi changer son empreinte intégrale : ne pas
modifier les preuves sauvegardées pour forcer une reprise.

## Vérification

```powershell
& E:/IGNIS-Valley/.venv/Scripts/python.exe -m pytest -q
& E:/IGNIS-Valley/.venv/Scripts/python.exe -m ruff check backend tools tests
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/blender/validate_assets.py --require-all-artifacts
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/remote/verify_application.py
```

La dernière commande suppose le service démarré et crée de vrais petits calculs,
une annulation et une campagne exportée. Le navigateur est vérifié par
`web/tools/browser-check.mjs` et le script de parcours Windows associé.
La CI vérifie contrats/API/assets/frontend ; elle ne simule pas la présence de
CUDA, FDS ou des poids Windows. Les preuves de calcul sont séparées dans `evidence/`.

La portée scientifique est détaillée dans [PHYSICS.md](PHYSICS.md),
[NASA.md](NASA.md) et [MODELS.md](MODELS.md).
