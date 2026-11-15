# Intégration du POC ISS — 15 novembre 2026

Le composant `IssPocView` consomme les sorties enregistrées du modèle chaleur et
fumée. Il n'exécute ni entraînement, ni simulation, ni nouvelle inférence dans le
navigateur. Le parcours de la future maquette peut ouvrir cette vue à l'entrée
d'un module, ou réutiliser son groupe THREE dans un rendu existant.

## Branchement React

```tsx
import IssPocView from "./components/IssPocView";

<IssPocView
  onBack={() => openStation()}
  onOpenSources={() => openNasaSources()}
/>;
```

Le coordinateur branche la vue sur `#iss`; `#poc` conserve le POC précédent. Le
composant charge `/poc/iss/index.json` et ses cas. `indexUrl` peut désigner un autre
index sur le même site, mais les fichiers de cas doivent rester dans `/poc/iss/`.
Un export absent produit un état d'attente explicite, sans démonstration factice.

La page garde la 3D au premier plan : intérieur navigable, vue d'ensemble,
sélection module/scénario, timeline, chaleur et fumée indépendantes. La bascule
« Référence FDS » et « Erreurs » distingue les prédictions de leurs cibles. La
vue initiale utilise le pic de température **FDS** lorsqu'un point chaud existe,
sinon le pic de suie FDS pour les cas fumée seule. Ce choix ne dépend pas des
scores ML. La caméra démarre dans une zone libre de l'allée, orientée vers la
source réelle ; aucune position de sonde ou prédiction n'est déplacée. Les
exemples de module viennent de l'index.

## Intérieur visuel

`web/src/iss-station.ts` est une dépendance du composant à inclure dans le kit.
Ce renderer Three.js produit panneaux jointés, racks, poignées, câbles, grilles,
étiquettes et éclairage intérieur à partir des boîtes et ventilations du cas
chargé. Il accepte les dimensions et dispositions exportées ; aucune géométrie
ISS fixe n'est substituée à une autre famille d'habitat.

Les détails des équipements restent dans leurs AABB physiques. La coque est
placée aux frontières, vers l'extérieur du domaine, avec les ouvertures des
évents réels ; la vue d'ensemble retire des faces pour montrer l'intérieur.
Peinture, écrans et câbles sont des illustrations sans nouveaux obstacles ni
coefficients thermiques. Les écrans portent une mention schématique et ne
prétendent pas afficher une télémétrie mesurée.

Le gris de la fumée et sa texture statique améliorent le contraste sur les parois
claires. Positions, rayon spatial, classes et masques restent ceux des glyphes
aux sondes ; aucun feu, mouvement ou champ de concentration n'est inventé.
Les textures, instances et cartes d'ombres sont libérées au changement de cas.
Les diagnostics de rendu exposent appels de dessin et triangles, pas une
garantie de fréquence d'images sur le poste de présentation.

## Contrat des exports

`web/src/iss-poc.ts` expose les types `IssIndex`, `IssCase`, `IssFrame` et les
validateurs. Schéma : `iss-poc-1`.

- L'index identifie poids et dataset par SHA256, contient les seuils physiques et
  les seuils de scores retenus, les partitions et métriques chaleur/fumée.
- Chaque entrée possède `id`, `layout_id`, `module_id`, `family`, `split`, `url`,
  `sha256` et ses métriques. `sha256` désigne les octets JSON décompressés reçus.
- Chaque cas contient **ses propres** boîtes physiques compilées pour FDS,
  matériaux, ventilations, conditions, source, positions et instants.
- Chaque instant sépare `temperature_c`, `soot_kg_m3`, `heat_score`,
  `smoke_score`, `heat_valid_mask`, `smoke_valid_mask`. Les décisions exactes
  `hotspot_truth`, `smoke_truth`, `predicted_hot_mask`, `predicted_smoke_mask`
  restent cohérentes avec les valeurs observées float32 conservées exactement.
  La comparaison au seuil physique exact utilise float64/Python et les nombres
  JavaScript, notamment pour `1e-6 kg/m³`, sans arrondir ce seuil en float32.
- Le client vérifie hash, identité et seuils avant affichage. Les mesures
  manquantes et masques invalides sont exclus par canal. Ils ne deviennent pas
  des points froids. `t = 0` reste visible ; les métriques agrégées indiquées
  proviennent de l'évaluation exportée `t > 0`.

Les dimensions sont en mètres, **XYZ avec Z vers le haut**. Conversion unique
vers THREE/glTF : `(x, y, z) → (x, z, −y)`. Aucun redimensionnement automatique
vers un modèle artistique n'est appliqué.

## Comparer la ventilation d'un même départ

Les entrées de l'index peuvent fournir ensemble `ventilation_group_id`,
`ventilation_state` (`still`, `slow`, `fast`, `reverse` ou `control`),
`ventilation_axis` (`x` ou `y`) et `reverse_ventilation` (booléen). Les témoins
ont un groupe `null` et l'état `control`. Les exports V2 sans ces champs
conservent leur comportement. Des métadonnées partielles ou incohérentes
produisent une erreur de lecture explicite.

Un quartet complet fait apparaître quatre boutons près du sélecteur de cas :
sans débit, lent (0,12 m/s), rapide (0,36 m/s), sens inversé (0,36 m/s).
Le débit affiché vient de l'index. Les quatre cas doivent partager groupe,
partition, module, disposition, famille, type de départ, gravité et axe de
ventilation. Un groupe incomplet ou ambigu ne crée pas de commande.

Les boutons et le sélecteur de scénario conservent le temps visé tant que le
changement reste dans ce quartet. Chaque cas affiche son relevé réel le plus
proche, avec préférence au relevé antérieur en cas d'égalité ; aucune valeur de
chaleur, fumée ou score n'est interpolée. Le temps visé et le temps effectivement
affiché sont tous deux indiqués. Le temps visé reste stable lors de plusieurs
bascules, jusqu'à une action sur la timeline ou la lecture.

Le point de vue est mémorisé dans le même quartet, en intérieur comme en vue
d'ensemble. Sa restauration exige les mêmes obstacles, matériaux, dimensions
et bouches physiques ; seuls les rôles entrée/sortie des bouches peuvent
différer. Les commandes caméra et le recentrage restent effectifs. Changer de
groupe, module, partition ou témoin rétablit le cadrage et l'instant initial
du cas. Aucun classement de sensibilité n'est calculé dans l'interface.

## Réutiliser les couches dans la maquette

```ts
import { decodeIssCase, issCaseUrl, parseIssIndex } from "./iss-poc";
import { createIssPocOverlay } from "./components/IssPocView";

const index = parseIssIndex(
  await fetch("/poc/iss/index.json").then((r) => r.json()),
);
const entry = index.cases.find((c) => c.id === selectedCaseId)!;
const response = await fetch(issCaseUrl(entry.url));
const data = await decodeIssCase(
  await response.arrayBuffer(),
  entry,
  index.model,
);

// physicalSceneDescriptor vient des annotations physiques de CE module.
// La fonction refuse une géométrie ou des matériaux différents.
const overlay = createIssPocOverlay(data, index.model, physicalSceneDescriptor);
threeScene.add(overlay.group);
overlay.setViewportHeight(renderer.domElement.height);
overlay.setFrame(data.frames[frameIndex], {
  display: "prediction",
  heat: true,
  smoke: true,
});

// À la sortie du module :
overlay.dispose();
```

`assertIssSceneBinding` compare les proxies, matériaux, épaisseurs thermiques et ventilations de la
scène, indépendamment de l'ordre de leurs objets. Un GLB simplement ressemblant
ne suffit pas. La décoration est exclue de la comparaison, mais ne doit pas
modifier des passages d'air sans adaptation des proxies et nouvelles données.
Un placement global de la station est possible via le transform du groupe
parent, **identique pour le module et les couches**, après vérification de cette
identité. Il ne remplace pas le contrôle des dimensions ou de la disposition.

Les halos sont des glyphes autour des sondes positives. Leur rayon dépend de
l'espacement des sondes et reste fixe. Ils n'ajoutent ni advection, ni trajectoire,
ni concentration simulée. Le score fumée représente la présence de suie au seuil
exporté ; son opacité n'est pas une densité physique. La couleur chaleur indique
une classe, pas une température prédite. Un clic montre séparément valeur FDS et
score ML.

Chaque scénario conditionne la propagation à **une** source électrique. Une
future carte réunissant plusieurs départs doit afficher cette agrégation comme
un ensemble d'hypothèses et ne pas prétendre à des feux simultanés ou à une
probabilité réelle de départ.

## Vérification

Tests ciblés :

```sh
cd web
npx vitest run src/iss-poc.test.ts
npm run build
```

Les tests couvrent coordonnées, identité physique, intégrité des fichiers,
masques indépendants, séparation référence/prédiction et visibilité des couches.
Ils vérifient aussi les métadonnées de ventilation, l'isolement des quartets et
la sélection d'un instant observé. Si l'export inclut les quartets, le contrôle
navigateur utilise un groupe TRAIN et vérifie conservation caméra/temps et
retour au comportement initial sur un témoin ; sinon il vérifie l'absence de
nouveaux boutons sur les exports antérieurs.
Les valeurs fabriquées sont confinées aux tests unitaires.

Contrôle navigateur **contre les exports réels**, après installation des fichiers
dans `web/public/poc/iss/` et démarrage de la prévisualisation :

```sh
cd web
IGNIS_BROWSER_URL=http://127.0.0.1:5177 \
IGNIS_BROWSER_PATH=/home/platform-admin/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome \
IGNIS_ISS_EVIDENCE=../evidence/incidents/iss-poc/browser \
node tools/iss-poc-check.mjs
```

Le script vérifie les hashes réels, les modules présents, le cadrage de la source,
les gestes de regard et déplacement, les couches, la timeline, le témoin froid,
le cas d'échec et la sélection du test. Il contrôle aussi l'absence d'erreurs JS
et d'écritures ou de nouveaux jobs. Il capture pour chaque module une vue
intérieure, une vue d'ensemble, la couche fumée seule et un cas de test.
Il produit un rapport JSON et des captures. Aucune interception réseau ou donnée
de démonstration inventée n'est employée.

`IGNIS_ISS_VENT_ONLY=1` limite ce contrôle à un quartet TRAIN et son témoin,
sans parcourir les partitions validation/test. Pour la vérification locale avant
promotion d'un modèle, utiliser un site temporaire séparé contenant les cinq
JSON réels, leurs empreintes inchangées et un index filtré explicitement marqué
comme sélection de contrôle UI. Les métriques de partition peuvent être omises
dans cet index temporaire ; aucun score ou champ physique n'est fabriqué.

Validation du lot ventilation le 15 novembre 2026 : 34 tests ciblés passent,
build TypeScript/Vite réussi. Le contrôle V2 compte 17 vérifications et 31
captures sans erreur JS ni écriture (`evidence/incidents/iss-poc-vent/browser-v2-compat/`).
Le contrôle des cinq TRAIN réels du candidat conserve la cible 28,7907 s malgré
des instants observés différents, vérifie les deux modes caméra et le retour au
témoin (`evidence/incidents/iss-poc-vent/browser-train-quartet/`). Les empreintes
du modèle et des cinq fichiers inchangés sont dans `fixture-provenance.json`.
Ces contrôles utilisent le rendu logiciel SwiftShader et ne mesurent pas les
performances graphiques du PC de présentation.

La géométrie est inspirée de l'ISS et non une réplique vérifiée. Les sorties
synthétiques ne valident pas expérimentalement un incendie réel. Le bouton Sources
NASA conserve le lien avec BASS/BASS-II, SAME et Saffire : ventilation, combustibles
et transport des fumées étudiés dans ces programmes donnent le contexte
scientifique du challenge, sans être confondus avec des labels FDS.
