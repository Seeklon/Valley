# Reprise — IGNIS 3D / Valley

14 novembre 2026. Application Windows opérationnelle et vérifiée. Sources de
livraison sur la branche `codex/ignis-3d-lab`. Lors d’une reprise, relire Git
et `/api/health` pour connaître l’état actuel du code et du service.

## Prévention avant allumage livrée

L'accueil ouvre Soyouz sans foyer. Quatre composants hypothétiques par scène,
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
