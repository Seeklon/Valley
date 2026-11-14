# Reprise — IGNIS 3D / Valley

14 novembre 2026. Application Windows opérationnelle et vérifiée. Sources de
livraison sur la branche `codex/ignis-3d-lab`. Lors d’une reprise, relire Git
et `/api/health` pour connaître l’état actuel du code et du service.

## Dernier essai spatial borné — terminé, modèle non activé

Essai du 14 novembre terminé : **44 min 58 s de phases**, **50 min 55 s écoulées**,
génération et entraînement compris. Ne pas lancer de calcul supplémentaire au
nom de ce budget ni reprendre automatiquement les 20 000 cas. Le contrôle final
à 19:49 UTC confirme zéro processus de calcul, deux API saines, campagne initiale
**en pause à 64 cas**, anciens modèles préservés.

Le compact final `E:/IGNIS-Valley-dev/datasets/spatial-compact-200-v1` contient
200 cas / 100 dispositions : 192 nouveaux FDS et 8 réutilisés de l'ancien corpus.
Le premier compact de 100 cas est conservé séparément. L'identifiant interne des
deux datasets reste `spatial-compact-v1` ; consulter chemin et empreinte du plan.
Entraînement CUDA neuf `spatial-recovery-v1` : 170 cas / 66 dispositions après
réutilisation des seuls trains historiques, validation 40 cas / 20 dispositions,
test réservé 40 cas / 20 dispositions. 52 époques, époque 32 retenue ; 7 min 32 s.
Poids dans `E:/IGNIS-Valley-dev/runtime/models/spatial-recovery-v1`.

Résultat insuffisant : rappel chaleur global 1,94 %. La fumée globale atteint
87,09 % de rappel / 57,37 % de précision, mais la microgravité seule donne
71,99 % / 18,52 %. Les pics restent sous-estimés. Aucune activation UI ; le
parcours Prédiction conserve son modèle précédent exploratoire. Le test final
est maintenant connu ; tout ajustement futur exige un autre test réservé.

Lire le [bilan mesuré](evidence/incidents/spatial-recovery/README.md), le
[registre de calcul](evidence/incidents/spatial-recovery/compute-ledger.json)
et la [recherche ML](docs/SPATIAL_RESEARCH.md). Prochaine priorité proposée :
supervision près des foyers et rareté des observations chaudes, avant davantage
de génération uniforme. Les archives ont U/V/W ; les cibles actuelles n'utilisent
que température/suie. Aucun nouvel apprentissage ni calcul lancé après le test.

## Parcours incidents et corpus spatial — travail du 14 novembre 2026

La version de développement isolée est `E:/IGNIS-Valley-dev`, port 8766,
URL privée Tailscale `https://desktop-m4hkr86.tail609f26.ts.net:8444`.
La version précédente et ses données restent dans `E:/IGNIS-Valley` sur 8443.

L'accueil devient Prédiction, avec Simulation par point sensible et Sources NASA.
Chaque incident sélectionne un composant annoté ; ses objets voisins gardent
leurs matériaux combustibles. Cinq familles : surchauffe, arc thermique équivalent,
feu déclaré, couvant et batterie équivalente. Aucun risque probabiliste n'est déduit.
Les limites et inconnus sont visibles ; les anciens écrans restent sous Outils.

Pilote réellement exécuté : 60 calculs FDS, 12 dispositions, train30/validation15/test15.
ExtraTrees `incident-field-v1` entraîné CPU en109s. Les scores du test montrent
qu'il ne surpasse pas la référence ambiante sur température moyenne de champ et
HRR ; ne pas annoncer un modèle généraliste. Poids/données conservés sur Windows,
métadonnées, résultats et preuves légères dans `evidence/incidents/`.

Thomas a ensuite demandé beaucoup plus de diversité : nouveau corpus procédural
cible1000 environnements ×20 cas =20000 FDS, dix familles structurelles, 1536 points.
Il a aussi demandé à être prévenu au lancement effectif du trainingGPU. Le réseau
est spatial3D (U-Net), pas un LLM ; voir les documents SPATIAL_*.
Relire progress.json et les journaux avant d'affirmer l'avancement.
Ne pas confondre cette cible avec des simulations déjà produites ni avec le pilote.

**GPU réellement exécuté** le 14 novembre, premier pas à 16:10:29 UTC,
fin à 16:12:20 UTC : RTX 4070 Ti, PyTorch 2.7.0+cu128, U-Net 834486 paramètres,
20 époques, époque 19 retenue sur validation. Modèle `spatial-pilot-v1` dans
le runtime dev, preuves `evidence/incidents/spatial-pilot/`. Thomas a été prévenu
immédiatement après le premier backward/optimizer synchronisé.
Le score composite test bat l'ambiance, mais température moyenne, suie moyenne
et HRR restent moins bons ; surchauffe et arc régressent. Pas d'activation UI.
Le parcours Prédiction utilise toujours `incident-field-v1`, clairement signalé
comme exploratoire. Aucun des deux pilotes n'est un modèle généraliste validé.

Le nouveau lanceur `tools/remote/run_spatial_study.py` enchaîne corpus complet
puis entraînement CUDA `spatial-corpus-v1`. Il refuse un corpus incomplet et
respecte PAUSE/STOP avant le training ; chaque enfant possède son verrou de
calcul, aucun verrou de calcul imbriqué. Ne pas relancer un poids existant.

**Campagne initialement lancée, désormais en pause à 64 cas**. Journal détaché :
`E:/IGNIS-Valley-dev/runtime/training/study-735d5f67483b4030ad0140e05de7bb38/worker.log`.
État léger : `datasets/spatial-corpus-v1/progress.json`, également accessible par
`GET /api/incidents/campaign`. Le test navigateur a repris les deux premiers
cas puis vérifié pause après le cas courant et reprise à quatre cas achevés,
sans erreur JS. Ce compteur est historique ; relire l'état avant de le citer.
À la reprise, supprimer un éventuel STOP explicitement et utiliser la même
commande. Une fermeture du PC nécessite de relancer le job ; aucun démarrage
automatique Windows n'est installé. Ne pas lancer un second orchestrateur.

Validation de cette tranche : 299 tests Windows, puis 21 tests du trainer après
l'ajout des empreintes source ; Ruff et vérification du diff réussis. Frontend :
65 tests, build et formatage ; 12 contrôles navigateur incidents et 5 contrôles
de campagne réels. Revue indépendante et résultats dans `evidence/incidents/`.
Les deux premiers cas procéduraux ont été relus : 31 instants, 1536 points,
archives gzip/ZIP vérifiées par SHA, six champs conservés. Les poids du pilote
3D ont également été rechargés et exécutés en inférence CPU avec succès.

## Version précédente : vue mission immersive — 14 novembre 2026

L'accueil est maintenant **Mission** : POV équipage dans Soyouz, fumée douce
colorée par température, couches fumée/température/ventilation, caméras orbite
et dessus, lecture/pause/vitesse et panneau latéral repliable. Le mode avant
allumage affiche les températures des composants et partage la session avec
les paramètres de Prévention. La fumée n'est jamais déduite de ces prévisions.

- Relecture Soyouz réelle `52687f69460643ada9ff8d8a7573dbca`, 61 champs sur 60 s ;
  sélection dynamique depuis `/api/runs`, hors résultats purement scalaires.
- Échelles fixes sur le replay, interpolation aux temps réels, axes non uniformes
  et masque des cellules respectés. Le lissage n'ajoute pas de résolution physique.
- Coque artistique complétée visuellement en POV ; données, proxies, moteur et
  poids inchangés. Aucun entraînement ni nouveau calcul FDS pour cette refonte.
- **34 tests frontend**, build TypeScript/Vite et formatage réussis ; **12 contrôles
  navigateur réels**, aucune erreur JavaScript. Captures, revue et preuve du
  déploiement statique dans `evidence/mission/`.
- Lire `docs/MISSION_VIEW.md` pour navigation, unités et portée du rendu.
  Le backend n'a pas été redémarré ; les anciens assets restent disponibles
  pour les onglets déjà ouverts, et l'ancien index est sauvegardé dans le runtime.

## Prévention avant allumage livrée

L'onglet Prévention ouvre Soyouz sans foyer. Quatre composants hypothétiques par scène,
dont deux fils NiCr/LDPE, un faisceau non caractérisé et une batterie non couverte.
Le délai vient d'un modèle expérimental restreint ; température physique et
prévision ML sont distinctes. Comparaison, preuve par composant, Codex et ZIP
fonctionnent. Aucune probabilité calibrée ni intervalle n'est inventé.

- 13 sources NASA, 22 conclusions et 49 relevés historiques archivés ; une étude
  complémentaire Guo, explicitement hors NASA, fournit 26 points d'allumage.
- `ignition-delay-guo-v1` : test 9 points/5 courants, MAE 0,157 s, maximum 0,335 s.
  Protocole NiCr/LDPE sous courant maintenu en microgravité uniquement.
- `thermal-history-forest-v1` : 384 trajectoires Windows, 16 familles test,
  1 940 fenêtres couvertes ; MAE 10,05 °C, maximum 129,30 °C. Physique locale
  exploratoire, pas de chimie d'allumage ni de validation thermique expérimentale.
- 131 tests Windows, Ruff, 22 tests frontend, build/format passent. 9 contrôles
  réels des modèles/API, 12 contrôles navigateur prévention et 8 contrôles
  de non-régression du laboratoire réussis ; aucune erreur JavaScript.
- Explication réelle par Codex `gpt-6.1-sol`, avec faits figés par composant.
- Preuves et revue indépendante : `evidence/prevention/`. Modèles/datasets
  dans `E:/IGNIS-Valley/runtime/prevention/`, distincts du registre FDS.
- Archive vérifiée de 99 fichiers, 39 142 723 octets :
  `G:/IGNIS-Valley-archives/ignis-prevention-v1-20261114T125618Z.zip`.
  SHA et vérification de chaque entrée dans `evidence/prevention/archive-verification.json`.

Lire `docs/PREVENTION_MODELS.md`, `PREIGNITION_PHYSICS.md`,
`PREIGNITION_SOURCES.md` et `PREVENTION_API.md`. L'air local est prescrit ; la
position 3D ne couple pas encore le fil au champ FDS. Les fréquences de panne,
cas sans allumage et données indépendantes nécessaires à un risque réel manquent.
Les datasets/modèles archivés ne doivent pas être écrasés ni leurs tests utilisés
pour choisir une amélioration. Les scripts refusent leur réécriture.

## Accès et exploitation

- Dépôt `/home/platform-admin/projects/Valley`, branche `codex/ignis-3d-lab`.
- URL privée Tailscale : `https://desktop-m4hkr86.tail609f26.ts.net:8443`.
- Sur le PC Windows : `http://127.0.0.1:8765`.
- Lanceurs : `tools/windows/start-ignis.ps1` et `stop-ignis.ps1`.
  Ils survivent à la fermeture SSH et contrôlent l’identité du service.
- Dernier démarrage vérifié : PID 24436, wrapper 6472. Ces numéros sont
  historiques ; utiliser le fichier d’identité pour arrêter le service.
- État du service : `E:/IGNIS-Valley/runtime/service/api-process.json`.
- Pas de tâche au démarrage Windows : relancer avec `docs/WINDOWS.md`.
- L’interprétation utilise **Codex**, détecté dans l’installation Windows déjà
  authentifiée. Aucun appel Ollama dans IGNIS. L’autre service Ollama sur HTTPS
  443 a été préservé.

## Socle FDS et preuves antérieures

- Quatre scènes Blender/GLB détaillées : habitat, cargo, crossflow et Soyouz.
  Soyouz est une interprétation originale avec proxy physique simplifié.
  `evidence/blender-verification.json` contrôle assets et import/export annoté.
- FDS 6.11.1 : froid, transport, combustion couplée et chauffage I²R réellement
  exécutés. Compilateur `ignis-fds-2`, matériaux `ignis-fds-materials-2`.
  Convergence de maillage non établie.
- 96 simulations pilotes, 5 800 instants ; deux modèles entraînés et préchargés :
  `field-mlp-v2`, `metrics-forest-v2`. Séparation 48/12/36 par calculs/familles.
- Audit Windows : CSV originaux, 96 fichiers FDS et échantillonnages identiques,
  partitions, domaines, latences et poids vérifiés. Identité physique version 2
  normalisant uniquement les flottants entiers ; hashes FDS exacts inchangés.
- Tables NASA BASS-II/BASS/Saffire-I archivées avec DOI/version/hash.
  Calibration ventilateur : 211 paires, 171 pour ajustement et 40 pour test.
  Calibration instrumentale uniquement ; aucune validation de combustion.
- Parcours réel complet : **15 contrôles réussis**, couvrant les huit prédictions
  scène/modèle, FDS Soyouz, export, domaine, annulation, campagne Parquet et Codex.
  Preuve : `evidence/application-verification.json`.
- **58 tests Windows réussis** et Ruff sans erreur. XML dans
  `evidence/windows-final-tests.xml`. Les 7 tests lifecycle sont aussi conservés
  dans `evidence/windows-lifecycle-tests.xml`.
- Contrelecture indépendante : `evidence/final-review.md` ; constats de
  concurrence des lanceurs, fermeture des processus et validation des citations
  corrigés et vérifiés.
- Navigateur sur l’URL Windows : 8 contrôles généraux et 7 contrôles de prédiction
  réussis, aucune erreur JavaScript, vues desktop/mobile inspectées. Rapports
  et captures dans `evidence/ui/`. Les aperçus temporaires du VPS ont été arrêtés.

## Localisateurs Windows

- Connexion SSH privée ignorée `.remote-pc.json`, contrôleur `tools/remote/pc.py`.
  Ne jamais afficher de clés ou recopier des secrets dans Git.
- Dossier isolé `E:/IGNIS-Valley` : `app/`, `.venv/`, `tools/`, `runtime/`,
  `datasets/pilot-v2/`. Ryzen 7 3700X, 16 Go RAM, RTX 4070 Ti 12 Go.
- Blender 4.5.9 LTS, Python 3.11.2, Torch 2.7.0+cu128, FDS 6.11.1.
- Poids : `E:/IGNIS-Valley/runtime/models/`. Copies de métadonnées et métriques
  dans `evidence/models/` et `docs/MODELS.md`.
- Archive vérifiée :
  `G:/IGNIS-Valley-archives/ignis-pilot-v2-models-20261114T112409Z.zip`.
  1 351 fichiers, 157 279 419 octets compressés, empreintes relues ;
  `evidence/archive-verification.json` et manifeste adjacent sur G:.
  Les métadonnées finales des modèles correspondent à cette archive.
- Les gros calculs et rendus restent sur Windows. Le VPS coordonne et conserve
  code, sources et petites preuves. Son port 8765 appartient à un autre projet.

## Limites et suite scientifique

Lire `docs/PHYSICS.md`, `NASA.md`, `MODELS.md` et `SCENES.md` avant d’élargir le
domaine. Les modèles imitent des simulations FDS exploratoires à 0,20 m ; ils
ne prédisent pas la vérité expérimentale NASA. Le réseau ne contraint pas la
cohérence moyenne/maximum/champ et sous-estime certains pics Soyouz. Les erreurs
par scène et gravité sont visibles dans l’interface. Aucun ajustement sur le test.

Une nouvelle géométrie doit être annotée, compilée, simulée et faire l’objet
d’un nouvel entraînement. La visualisation seule ne lui donne pas un domaine
prédictif. Réserver de nouvelles familles de test avant toute amélioration ML.
Thomas a précisé la priorité : prévoir le départ de feu avant l'allumage et
localiser le risque dans la 3D. Le cadrage est dans `docs/PREIGNITION.md` :
premier cas de surchauffe électrique, conclusions NASA comparables, trajectoires
avant feu et témoins, modèle temporel, validation indépendante et incertitude.
La première tranche est livrée selon le périmètre décrit en tête de ce document.
Les 96 calculs de source prescrite restent distincts du dataset d'allumage.
La prochaine étape scientifique exige cas témoins, validation indépendante et
couplage fil/cabine ; les températures simulées seules ne comblent pas ces données.

## Méthode conservée

Le plan est dans `PLAN.md`. Agentic fournit méthode et revue, sans conventions
produit Seeklon. L’utilisateur demande réalisation autonome et visuels réguliers
en français. Les lots physique, frontend et revue sont terminés ; conserver leurs
preuves. Avant une nouvelle session, vérifier Git, l’état du service, la file de
calcul et les capacités réelles, sans rejouer les 96 simulations par défaut.
