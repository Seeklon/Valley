# Flame in Freefall

Site de l'équipe **Seeklon Valley** pour le NASA Space Apps Challenge 2026 (Paris), défi
*Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data*.

Une exploration en 3D : depuis la Lune, la caméra recule jusqu'à la station en orbite ; on choisit un
environnement (ISS, base lunaire, Terre), puis un compartiment, une pièce et un scénario électrique.
Les intérieurs affichent les prédictions enregistrées de chaleur et de fumée du modèle ML.

C'est un **site statique** : Vite + TypeScript, aucune partie serveur.

## Commandes

```bash
npm install        # dépendances
npm run dev        # serveur de développement
npm run build      # vérification des types puis site statique dans dist/
npm run preview    # sert dist/ en local
npm run data:psi   # rafraîchit l'archive PSI, hors interface publique
```

Le build utilise des chemins relatifs (`base: './'`) : le contenu de `dist/` se dépose tel quel dans
n'importe quel dossier d'un serveur web. La version publique est hébergée sur
`https://space.in-momentum.fr` ; voir `deploy/space/README.md`. Le poids dépend de l'export ML installé.

## Organisation

| Chemin | Rôle |
|---|---|
| `index.html` | structure de la page |
| `src/main.ts` | point d'entrée |
| `src/app.ts` | toute l'expérience : scènes 3D, transitions, pièces, panneaux |
| `src/styles.css` | styles |
| `src/data/psi-snapshot.json` | instantané des investigations PSI (généré) |
| `src/data/investigations.ts` | ancienne curation PSI conservée en source, non importée par le site |
| `scripts/fetch-psi.mjs` | génère l'instantané |
| `scripts/render-server.py` | sert `dist/` et enregistre les images exportées (voir plus bas) |
| `public/` | modèle Gateway, textures, images pré-rendues |

## Données

Le site charge les scènes et sorties ML du lot vérifié `public/poc/iss/`, construit sur des simulations
FDS synthétiques. Chaque cas est vérifié par SHA256 avant affichage.

L'instantané du dépôt **NASA Physical Sciences Informatics** (PSI), recherche « combustion », reste
conservé dans les sources pour sa provenance. Les investigations, comparaisons, scores de pertinence
et résumés d'illustration ont été retirés de l'interface ; le site n'importe plus ces enregistrements.

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

L’introduction, les voyages entre environnements et la navigation restent ceux du site.
Les intérieurs et leur panneau de conditions utilisent les
scènes IGNIS et les **inférences enregistrées** du réseau chaleur/fumée. Aucun entraînement, aucune
simulation FDS ni nouvelle inférence n’est lancé dans le navigateur.

Les marqueurs et la navigation portent les noms des compartiments : cargo, nœud de jonction,
service, laboratoire et équipements centraux. Le sélecteur permet aussi de visiter la capsule.
Les anciens identifiants `prev`, `det`, `sup`, `fun`, `si` restent internes pour conserver les ancres
du modèle extérieur et les URL. Le modèle classe la présence de chaleur et de fumée pour une source
électrique donnée ; il ne prédit pas une probabilité de départ, un temps d’alarme ou une extinction.

Les boutons **précédent / suivant** de la barre inférieure changent directement le scénario dans la
pièce affichée, même avec les réglages fermés. Ils bouclent sur les variantes de cette pièce. Cliquer
sur le nom ouvre le seul menu « Scenario ». « Change room », replié par défaut, contient les choix
du compartiment et de la disposition. L'export ventilation actuel offre 24 pièces, quatre par
compartiment, et 216 scénarios. Les numéros de pièce sont stables dans
chaque compartiment ; dimensions, nombre d'équipements et bouches d'air proviennent du cas chargé.
Le menu scénario contient seulement les variantes de la pièce choisie et distingue les débits,
le flux inversé et le témoin sans feu. Les identifiants techniques et partitions train/validation/test
restent dans « Model & conditions ». La navigation suit la famille effectivement affichée.

Le rendu conserve les dimensions, matériaux et passages d’air de chaque scénario. La conversion
physique XYZ (Z vertical) vers Three.js est `(x, z, -y)`, commune à la pièce et aux sondes. Les nouvelles
couches ne sont jamais appliquées aux anciens intérieurs de la maquette. Les panneaux ont des
jointures, fixations, grain et relief de surface ; les racks des repères et faisceaux supplémentaires.
Ces détails restent dans les volumes existants. Les lumières sont rééquilibrées et les textures
procédurales sont réutilisées entre scènes ; la disposition et les annotations physiques restent intactes.

Glisser à droite pour regarder à droite, vers le haut pour regarder vers le haut ; flèches / WASD /
ZQSD pour se déplacer. « Exterior view », toujours accessible en bas de la scène, montre la pièce
entière en coupe ; « Enter POV » permet d’y revenir. Le retour station est en haut à gauche.
Les investigations sont retirées. Les réglages sont fermés à l’entrée. « Prediction controls » ouvre le panneau de
réglages à droite, refermable par sa croix, son bouton ou Échap, sans perdre le scénario ni l’instant.
Un changement de pièce dans le sélecteur conserve le mode de vue, POV ou extérieur.
La timeline et les boutons chaleur/fumée lisent les instants exportés, sans interpolation inventée.
La fumée utilise une texture nuageuse déterministe et les points chauds un halo texturé. Leur
position et leur rayon restent liés aux sondes ; la texture n’ajoute aucune propagation simulée.
La couche « FDS reference » montre la cible, « Misses and false alarms » distingue les erreurs.
Le premier instant affiché est le pic observé par FDS, pas un résultat choisi selon la qualité ML.
Chaque scénario reconstruit la géométrie et les équipements de son export et charge ses propres
sondes. Les variantes de ventilation partagent volontairement une disposition pour la comparaison.
Changer de pièce ou de type d'incident peut aussi changer la source et les matériaux.

ISS charge uniquement les cas en microgravité ; Terre charge les cas à 1 g lorsqu’ils existent.
Pour toute gravité absente de l’export, le parcours montre seulement un aperçu de géométrie, avec les
prédictions explicitement désactivées. L’adaptation ventilation du 15 novembre contient 216 cas,
tous en microgravité : les parcours Terre et Lune restent donc en aperçu de géométrie. Leurs boutons
et transitions sont actifs ; « ML not ready - Coming soon » concerne seulement les prédictions ML.
Le mode `?nogl` conserve les images pour l’extérieur ; les
nouveaux intérieurs nécessitent WebGL et affichent un état d’erreur s’il est indisponible. Les anciens
exports `?export=rooms` sont les images de la maquette, pas des sorties ML.

### Préchargement dès l'accueil

Le build génère `scene-assets.json` à partir des scènes, textures, vignettes et transitions présentes
dans `public/` (hors lot ML). Dès l'ouverture, le site charge les six cas d'entrée en priorité,
puis tous ces assets et le reste des 216 scénarios, avec trois téléchargements de fond simultanés.
Une progression s'affiche sur l'accueil et la vue extérieure ; le parcours reste utilisable pendant
le chargement. Aucun tableau de prédictions n'est analysé par le préchargement.

Les fichiers de prédiction sont vérifiés par SHA256, puis conservés via CacheStorage, avec trois
fichiers récents en mémoire. La clé contient le hash : un nouvel export ne réutilise pas les anciens
résultats. Les demandes concurrentes d'un même fichier sont partagées, et quitter une pièce ne
coupe pas le préchargement partagé. Les assets visuels utilisent le cache HTTP du navigateur.
Si le stockage est indisponible, plein ou si un téléchargement échoue, le site indique le chargement
à la demande ; il ne prétend pas que tout est prêt. Le lot actuel représente environ 281 Mo de
JSON compressés sur le réseau, 1,06 Go décompressés en cache, plus les assets visuels.
Le premier téléchargement et la préparation WebGL dépendent toujours du réseau et du navigateur.

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
le retour station, les cas Terre/Lune et le mobile. Il vérifie l'absence des investigations et des
anciens thèmes, les réglages fermés au départ, leur ouverture/fermeture, le sens des glissements
de caméra et l’accès direct à la vue extérieure. Il change aussi les quatre pièces cargo, vérifie
leurs géométries distinctes, leurs scénarios filtrés et la synchronisation de la navigation.
Il vérifie aussi le changement rapide sans panneau, le préchargement complet et l'ouverture d'un
scénario en cache lorsque ses requêtes réseau sont bloquées. Les tests unitaires couvrent le
changement de hash, un cache corrompu, les limites de stockage et l'annulation d'un seul lecteur.
Il vérifie les comptes de sondes directement contre
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
