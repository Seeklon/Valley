# Flame in Freefall

Site de l'équipe **Seeklon Valley** pour le NASA Space Apps Challenge 2026 (Paris), défi
*Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data*.

Un simulateur en 3D : depuis la Lune, la caméra recule jusqu'à la station en orbite ; on choisit un
environnement (ISS, base lunaire, Terre), on entre dans une pièce par thème de prédiction (prévention,
détection, suppression, physique des flammes, console SI), on choisit un scénario de prédiction et on consulte
les investigations NASA classées pour cet environnement.

C'est un **site statique** : Vite + TypeScript, aucune partie serveur.

## Commandes

```bash
npm install        # dépendances
npm run dev        # serveur de développement
npm run build      # vérification des types puis site statique dans dist/
npm run preview    # sert dist/ en local
npm run data:psi   # rafraîchit l'instantané des investigations PSI
```

Le build utilise des chemins relatifs (`base: './'`) : le contenu de `dist/` se dépose tel quel dans
n'importe quel dossier d'un serveur web (le VPS n'est pas encore fixé). Il pèse environ 100 Mo, presque
entièrement des images.

## Organisation

| Chemin | Rôle |
|---|---|
| `index.html` | structure de la page |
| `src/main.ts` | point d'entrée |
| `src/app.ts` | toute l'expérience : scènes 3D, transitions, pièces, panneaux |
| `src/styles.css` | styles |
| `src/data/psi-snapshot.json` | instantané des investigations PSI (généré) |
| `src/data/investigations.ts` | passage des enregistrements PSI au modèle de l'interface, avec notre classement par thème |
| `scripts/fetch-psi.mjs` | génère l'instantané |
| `scripts/render-server.py` | sert `dist/` et enregistre les images exportées (voir plus bas) |
| `public/` | modèle Gateway, textures, images pré-rendues |

## Données

Les investigations viennent du dépôt **NASA Physical Sciences Informatics** (PSI),
recherche « combustion ». L'API PSI n'accepte les appels de navigateur que depuis `psi.nasa.gov` : un site
statique ne peut donc pas l'interroger en direct. `npm run data:psi` enregistre un instantané, intégré au
build. L'instantané du 15/11/2026 contient 26 enregistrements ; les 24 du domaine « Combustion Science »
sont affichés.

Ce qui vient de PSI : numéro d'accession, titre, plateforme, matériel, objectifs.
Ce qui est de nous : le thème (prévention, détection, suppression, physique des flammes), le libellé court
du combustible et des variables, et les indicateurs de pertinence. Ils sont dans
`src/data/investigations.ts`, table `CURATED`.

**Les scores et les résumés « SI summary » sont des valeurs d'illustration**,
pas des résultats NASA. L'API de recherche ne fournit pas de DOI : la citation affichée donne le titre et
l'accession PSI.

## Deux modes d'affichage

- **3D direct** (WebGL, three.js r128) quand le navigateur le permet.
- **Images pré-rendues** sinon : séquences dans `public/frames/` et vues fixes dans `public/rooms/`. Le
  site bascule seul sur ce mode si WebGL est absent, rendu par logiciel, trop lent (moins d'environ
  18 images par seconde) ou si l'écran d'accueil reste noir.

Paramètres d'URL utiles pour tester : `?nogl` force les images pré-rendues, `?gl` force la 3D,
`?hub` saute l'intro, `?env=moon|earth` choisit l'environnement, `?open=prev|det|sup|fun|si` ouvre une pièce.

### Re-rendre les images pré-rendues

À refaire après toute modification visuelle d'une scène, sinon les deux modes ne montrent plus la même chose.

```bash
npm run build
python3 scripts/render-server.py            # sert dist/ sur le port 8765
firefox --headless --window-size=1280,720 --screenshot /tmp/x.png "http://127.0.0.1:8765/?export=env"
```

Les images arrivent dans `render-out/`. Types d'export : `intro` (défaut), `hub`, `env`
(`&only=moon|earth|x`), `rooms` (`&env=earth` pour les pièces terrestres). Les séquences sont ensuite
assemblées en planches de 9 images (3 × 3, 3840 × 2160) : `r` intro, `s` station, `ma` Lune, `ea` Terre,
`xa` Lune ↔ Terre. L'assemblage n'est pas encore scripté dans le dépôt.

## Limites connues

- `src/app.ts` est le portage en un seul module de la maquette validée ; il est exclu de la vérification
  des types (`@ts-nocheck`). Les modules de données et les nouveaux modules `src/prediction/` sont typés. Le découpage en modules typés reste à faire.
- Les contrats des prédictions ont des tests unitaires et le parcours des pièces a un contrôle navigateur sur les exports réels (voir ci-dessous).
- Les scènes extérieures restent celles de la maquette. Les pièces utilisent les géométries physiques des cas exportés et une décoration procédurale ; ce ne sont pas des répliques vérifiées de Gateway ou de l’ISS.
- Le modèle Gateway est celui de NASA 3D Resources ; les textures lunaires viennent de Moon Trek (LRO),
  le relief de LOLA, l'imagerie terrestre de l'USGS National Map. La NASA ne cautionne pas ce projet.


## Pièces POV et prédictions ML

L’introduction, les voyages entre environnements, les marqueurs, les panneaux NASA et la navigation
restent ceux du site. Seuls les intérieurs et leur panneau de conditions utilisent maintenant les
scènes IGNIS et les **inférences enregistrées** du réseau chaleur/fumée. Aucun entraînement, aucune
simulation FDS ni nouvelle inférence n’est lancé dans le navigateur.

Les thèmes de la maquette ouvrent les compartiments suivants : prévention → cargo, détection → nœud,
suppression → service, physique → laboratoire, console SI → équipements centraux. Le sélecteur permet
aussi de visiter la capsule. Ces thèmes ne créent pas de nouvelles sorties ML : le modèle classe la
présence de chaleur et de fumée pour une source électrique donnée. Il ne prédit pas une probabilité de
départ, un temps d’alarme ou une extinction.

Le rendu conserve les dimensions, matériaux et passages d’air de chaque scénario. La conversion
physique XYZ (Z vertical) vers Three.js est `(x, z, -y)`, commune à la pièce et aux sondes. Les nouvelles
couches ne sont jamais appliquées aux anciens intérieurs de la maquette.

Glisser pour regarder, flèches / WASD / ZQSD pour se déplacer. « Overview » montre la pièce en coupe.
La timeline et les boutons chaleur/fumée lisent les instants exportés, sans interpolation inventée.
La couche « FDS reference » montre la cible, « Misses and false alarms » distingue les erreurs.
Le premier instant affiché est le pic observé par FDS, pas un résultat choisi selon la qualité ML.
Changer de scénario peut changer plusieurs conditions simultanément : ce n’est pas une expérience
isolant causalement le débit d’air.

ISS charge uniquement les cas en microgravité ; Terre charge les cas à 1 g lorsqu’ils existent.
Pour toute gravité absente de l’export, le parcours montre seulement un aperçu de géométrie, avec les
prédictions explicitement désactivées. L’adaptation ventilation du 15 novembre contient 216 cas,
tous en microgravité : les parcours Terre et Lune restent donc en aperçu de géométrie.
Le mode `?nogl` conserve les images pour l’extérieur ; les
nouveaux intérieurs nécessitent WebGL et affichent un état d’erreur s’il est indisponible. Les anciens
exports `?export=rooms` sont les images de la maquette, pas des sorties ML.

### Installer les sorties d’un entraînement validé

Les gros fichiers ne sont pas versionnés dans Git. Le dossier source doit être un export complet
`iss-poc-1` **déjà validé**, contenant `index.json` et `cases/` :

```bash
npm ci
npm run data:predictions -- /chemin/vers/export-valide
npm test
npm run build
npm run preview -- --host 127.0.0.1 --port 5182
```

Le script vérifie les empreintes de tous les cas, leurs identités et les seuils du modèle avant de
remplacer le lot local. L’ancien lot est conservé sous `artifacts/prediction-backups/`. Les tests
unitaires n’ont pas besoin de ces données. Les fichiers `public/poc/iss/` sont inclus dans `dist/`
par le build. Servir le site en HTTPS ou sur localhost pour la vérification SHA256 du navigateur.
Les chemins relatifs de la maquette restent supportés, y compris sous un sous-dossier.

Pour brancher le réentraînement en cours, réexécuter cette commande sur son export après validation,
puis reconstruire le site. Aucun changement de code ni de maquette n’est nécessaire. Ne pas copier
un checkpoint `.pt` seul : le site lit les sorties de ce checkpoint. Les empreintes des poids et du
dataset sont conservées dans l’index et dans `installation.json`; l’empreinte des poids est visible
sous « Model & conditions ». Un cas dont les octets ne correspondent pas à l’index est refusé.

### Validation navigateur

```bash
npx playwright install chromium
POV_URL=http://127.0.0.1:5182 npm run test:prediction
```

Ou fournir `BROWSER_PATH` pour un Chromium existant. Captures et rapport sont dans `artifacts/browser/`.
Le contrôle suit les cinq pièces, la capsule, les couches et la timeline, un témoin à puissance nulle,
le retour station, les cas Terre/Lune et le mobile. Il vérifie les comptes de sondes directement contre
les masques des fichiers réels et l’absence d’écritures réseau. Les modules de données, le renderer
et les glyphes proviennent du POC IGNIS du même dépôt ; les adaptations r128 concernent uniquement
l’API Three.js, les couleurs sRGB et le contrôle de caméra.

Les vignettes des cinq pièces sont aussi des captures des nouvelles scènes. Pour les actualiser après
un nouvel export, avec la prévisualisation déjà lancée : `npm run data:previews`, puis `npm run build`.
Le script conserve la provenance de chaque vignette dans `artifacts/preview-provenance.json`.
Un contrôle complémentaire (`npm run test:prediction:edges`) couvre les chemins
sous `/mission/`, une indisponibilité réseau injectée et la navigation pendant un chargement. Il attend
une seconde prévisualisation sur le port 5183 avec `--base /mission/`; `POV_NESTED_URL` peut la remplacer.

Pour contrôler aussi l’extérieur WebGL forcé, utiliser `POV_LIVE_WEBGL=1` avec un navigateur disposant d’un GPU. Cette passe forcée n’a pas été validée sur le SwiftShader du serveur ; le parcours avec extérieur pré-rendu et intérieurs 3D, lui, a été vérifié.
