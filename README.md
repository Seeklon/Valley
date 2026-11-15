# Flame in Freefall

Site de l'équipe **Seeklon Valley** pour le NASA Space Apps Challenge 2026 (Paris), défi
*Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data*.

Un simulateur en 3D : depuis la Lune, la caméra recule jusqu'à la station en orbite ; on choisit un
environnement (ISS, base lunaire, Terre), on entre dans une pièce par thème de prédiction (prévention,
détection, suppression, physique des flammes, console SI), on règle les conditions d'essai et on consulte
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

**Les scores, les résumés « SI summary » et les prédictions des pièces sont des valeurs d'illustration**,
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
  des types (`@ts-nocheck`). Seuls les modules de données sont typés. Le découpage en modules typés reste à faire.
- Pas de tests automatisés.
- Les scènes sont procédurales ; les modèles Blender prévus ne sont pas intégrés.
- Le modèle Gateway est celui de NASA 3D Resources ; les textures lunaires viennent de Moon Trek (LRO),
  le relief de LOLA, l'imagerie terrestre de l'USGS National Map. La NASA ne cautionne pas ce projet.
