# Scènes Blender et import d'environnements

Le module **Aster** est une géométrie originale d'habitat expérimental. Ce n'est
pas une reconstruction d'un module ISS ni un modèle géométrique validé par la
NASA. Ses dimensions intérieures sont **5,6 × 8 × 3,2 m**. Le modèle contient de
la vraie géométrie : racks et modules démontables, panneaux, vis, filtres,
conteneurs, vannes, faisceaux, conduits, clavier, paillasse, porte avec coaming,
grilles et banc de combustion. Aucune image, texture ou géométrie NASA externe
n'est nécessaire.

## Fichiers et contrat

- `scenes/catalog.json` : bibliothèque et quatre scènes, schema_version 1.
- `tools/blender/scene_catalog.py` : source déterministe du catalogue ; Python
  standard uniquement. Vérifie identifiants, limites, recouvrements et bouches.
- `tools/blender/build_scene.py` : générateur de géométrie, export GLB et rendus.
- `tools/blender/soyuz_geometry.py` : coque courbe et équipements de la capsule
  inspirée de Soyouz, demandée explicitement par Thomas.
- `tools/blender/export_scene.py` : export d'un modèle importé et annoté.
- `tools/blender/validate_assets.py` : contrôle léger des GLB, IDs sémantiques,
  ressources embarquées, empreintes et dimensions des images.
- `scenes/generated/<id>.blend` : scène modifiable, courbes et textes conservés.
- `scenes/generated/<id>.glb` : géométrie visuelle triangulée pour le navigateur.
- `scenes/generated/<id>-overview.png`, `-detail.png`, éventuellement `-plan.png`.
- `scenes/generated/<id>.manifest.json` : version Blender, statistiques,
  empreintes des entrées/sorties et statut d'inspection.

Les chemins d'assets web sont `/assets/scenes/<id>.glb`. L'intégration copie ou
sert ces fichiers ; le générateur ne modifie pas `web/`.

### Repère et enveloppe physique

Le catalogue et Blender utilisent **X, Y, Z en mètres, Z vers le haut**, avec
origine au coin inférieur avant gauche du volume intérieur. L'export glTF
transforme les coordonnées en `(x, z, -y)` ; le frontend doit utiliser cette même
conversion pour les sondes, les champs et la source.

La scène Blender sépare quatre collections :

| Collection | Contenu |
|---|---|
| `01_VISUAL_CUTAWAY` | Géométrie pour le rendu et le GLB, déjà en coupe. |
| `02_PHYSICAL_PROXY__enable_to_inspect` | Domaine, boîtes de calcul et annotations ; masquée initialement. |
| `03_COMPLETE_HULL__hidden_in_presentation` | Six parois fermant le compartiment ; masquées dans la présentation. |
| `04_STUDIO__excluded_from_GLB` | Éclairage, sol de présentation et trois caméras. |

Le GLB retire le plafond, la façade avant et la partie haute de la paroi droite.
Cette coupe facilite l'inspection ; **elle n'ouvre pas le domaine physique**.
Les parois physiques sont définies par les frontières de `bounds_m`. Les AABB
`role=wall` sont descriptives, situées hors du domaine intérieur et doivent être
exclues des obstacles internes (`OBST`) pour ne pas fermer les ventilations.

Les boîtiers de calcul sont des enveloppes AABB explicites. Les détails fins
(vis, fils, supports de sondes, moniteurs minces et rails) ne sont pas résolus
séparément. Les filtres et gros équipements sont à l'intérieur de leur enveloppe.
Leur géométrie interne ne crée pas automatiquement des conduits dans le solveur.
Une étude nécessitant ces passages doit les décrire avec d'autres proxies et
une résolution adaptée.

Les groupes et leurs pièces portent `object_id`, `role`, `material_id` dans les
extras glTF. Les murs visibles ont `surface_kind` et `cutaway=false` ; certaines
utilités décoratives hautes portent `cutaway=true`. Il ne faut pas masquer tous
les objets `role=wall` pour activer la coupe initiale, déjà présente.

## Variantes

| ID | Géométrie et différences |
|---|---|
| `habitat` | Trois racks latéraux, console, gestion des fluides, paillasse, armoire et banc expérimental. Soufflage avant et reprise arrière haute. |
| `cargo` | Même compartiment avec trois caisses retenues et échantillon PMMA. Les nouveaux obstacles sont inclus dans le proxy. |
| `crossflow` | Soufflage bâbord/arrière, extraction tribord/avant et déflecteur central. Le déflecteur est un obstacle physique. |
| `soyuz` | Capsule compacte inspirée du module de descente Soyouz : coque courbe en coupe, trois sièges inclinés avec harnais, tableau de bord, hublots, câblage et ventilation latérale. |

La source de référence est à `[2.65, 3.55, 1.50]` m. L'échantillon est centré à
`[2.65, 3.55, 1.35]`, sur un support fin au-dessus du socle. Les proxies socle et
échantillon sont séparés de 0,2 m pour conserver des cellules distinctes au
maillage initial ; les petits montants sont décoratifs. Aucun matériau de vol
n'est déduit d'une apparence visuelle. Les références cellulose et PMMA sont
marquées génériques tant que les paramètres ne sont pas calibrés.

### Capsule Soyouz : périmètre propre

La capsule est une **interprétation visuelle originale**, pas un plan constructeur
ni une réplique certifiée. Son domaine de calcul est une boîte approximative de
**3 × 3 × 2,6 m**, avec quatre obstacles d'angle pour approcher la section ronde.
Ce domaine n'épouse pas exactement la coque artistique courbe : cette différence
est conservée dans `provenance.scientific_status` et `visual_detail_policy`.
Une validation quantitative d'une capsule réelle exigerait une géométrie mesurée,
des passages d'air détaillés et des essais comparables.

Les trois sièges ont des proxies pleins, tandis que l'image montre leurs coques,
coussins, harnais et supports. La source est à `[1.5,0.75,1.7]`, le coupon à
`[1.5,0.75,1.5]`. Soufflage à `[0,1.5,0.8]`, reprise à `[3,1.5,0.8]`. Le défaut
`mesh_cell_m=0.2` est explicite ; le backend doit contrôler la compatibilité des
grilles de sortie et de ses modèles avec ce domaine plus petit. Un modèle entraîné
seulement sur Aster ne devient pas validé pour Soyouz grâce à l'ajout d'un GLB.

## Génération sous Windows

Cible : **Blender 4.5 LTS**, Python intégré. Aucun add-on ni package supplémentaire.
Minimum attendu 4.2 ; seul un essai réel établit la compatibilité d'une autre
version. Les calculs de rendu ont lieu sur le PC Windows, jamais sur le VPS.

Depuis la racine du checkout `E:/IGNIS-Valley/app`, régénérer le catalogue :

```powershell
python tools/blender/scene_catalog.py
```

Premier aperçu réel, GPU, 1600 × 1100 pixels :

```powershell
& 'E:/IGNIS-Valley/tools/blender-4.5.9-windows-x64/blender.exe' `
  --background --python-exit-code 2 --python tools/blender/build_scene.py -- `
  --scene habitat --output scenes/generated `
  --render --gpu --samples 16 --width 1600 --views overview
```

Génération finale des quatre variantes et des deux vues :

```powershell
& 'E:/IGNIS-Valley/tools/blender-4.5.9-windows-x64/blender.exe' `
  --background --python-exit-code 2 --python tools/blender/build_scene.py -- `
  --scene all --output scenes/generated `
  --render --gpu --samples 32 --width 1600 --views overview,detail
```

Pour générer la capsule seule, utiliser `--scene soyuz`. Le module Python
`soyuz_geometry.py` doit rester dans le même dossier que `build_scene.py`.

Omettre `--render` produit `.blend` et `.glb` sans rendu. Omettre `--gpu` demande
explicitement Cycles CPU. Si `--gpu` est demandé et aucune carte compatible
n'est trouvée, le script échoue au lieu de lancer silencieusement un rendu CPU.
`--views plan` fournit une troisième vue de dessus. Ne pas lancer ces rendus
en parallèle d'un entraînement ou d'un job Ollama occupant la VRAM.

Le premier essai Windows documenté par le coordinateur a produit le modèle
habitat avec **844 objets visuels, 72 296 triangles et un GLB d'environ 3,7 Mo**,
en 11,77 s, dont 7,02 s de rendu à 16 échantillons. Ce chiffre est un benchmark
de cette révision et de cette machine, pas une garantie pour les suivantes.
Le manifeste du rendu courant donne les statistiques faisant autorité.

Contrôler le paquet complet sur Windows après génération :

```powershell
python tools/blender/validate_assets.py --require-all-artifacts
```

Le même outil peut fonctionner sur le VPS sans Blender : il lit uniquement les
en-têtes GLB/PNG, métadonnées et empreintes. Sans `--require-all-artifacts`, il
signale les `.blend` absents du checkout au lieu de les confondre avec des
fichiers vérifiés. Un `.blend` présent mais périmé est toujours une erreur.

### Inspection visuelle attendue

1. L'aperçu montre tout le compartiment en coupe, avec marge autour de la coque.
2. Les équipements sont lisibles, le banc central reste visible, les couleurs
   permettent de distinguer structure, surfaces, câblage et instrumentation.
3. La vue détaillée montre de la géométrie réelle : grilles, connecteurs, filtres,
   câbles courbes, clavier et porte ; aucun plan portant une fausse image 3D.
4. Cargo montre trois conteneurs ; crossflow montre le déflecteur et les bouches
   déplacées ; Soyouz montre trois sièges distincts et sa coque courbe.
   Les proxies et le GLB correspondent à la même variante.
5. Les images sont lisibles à 1600 pixels minimum, sans objet flottant accidentel,
   matériau manquant ou découpe de caméra. Les sondes marquent des positions de
   mesure ; leur support fin n'est pas une nouvelle obstruction de calcul.
6. Le GLB doit charger dans le navigateur et permettre la sélection par ID.
   Contrôler le coût de rendu réel, pas seulement le nombre de triangles.

Un manifeste a `render_inspected=false` par défaut. Le rendu terminé ne prouve
pas son inspection ni le bon fonctionnement du parcours web. Les preuves de
revue sont consignées séparément par le coordinateur.

## Importer un modèle 3D existant

Le fichier visuel peut venir d'un GLB/glTF, OBJ ou STL importé dans Blender, ou
d'un scan correctement mis à l'échelle. Le générateur Aster n'est pas requis.
L'exporteur fonctionne sur le `.blend` courant après annotation explicite.

### Préparer le fichier

1. Mettre à l'échelle et orienter la géométrie : un mètre Blender doit être un
   mètre réel ; `scene.unit_settings.scale_length = 1`. Le coin minimum du
   domaine physique doit être `[0,0,0]`. L'exporteur refuse une conversion
   implicite d'unités.
2. Déplacer la géométrie visuelle dans `IGNIS_VISUAL`. Les textures peuvent
   rester purement graphiques ; elles ne déterminent pas la thermochimie.
3. Créer `IGNIS_PHYSICS` et un cube de domaine avec `ignis_role="domain"`.
   Cette boîte doit être alignée sur les axes et entourer le domaine intérieur.
4. Créer des boîtes explicites pour les obstacles et combustibles. Les maillages
   complexes visuels ne sont pas acceptés à leur place. Les boîtes ne doivent
   pas se recouvrir. Conserver une marge adaptée au maillage du solveur.
5. Ajouter les ventilations, sondes et une source. Définir les paramètres
   physiques par défaut dans la propriété de scène `ignis_defaults_json`.

### Propriétés Blender

Les propriétés personnalisées sont accessibles depuis l'onglet Objet. Les
coordonnées utilisent les transformations globales, pas les positions locales
d'un objet parenté. L'exporteur évalue temporairement les collections masquées
ou exclues de la vue, capture les transformations globales, puis rétablit leur
visibilité. Blender peut sinon laisser leurs matrices globales à l'identité,
même après une simple mise à jour de la vue.

| Objet d'annotation | Propriétés |
|---|---|
| Cube de domaine | `ignis_role="domain"`, dimensions et position explicites. |
| Cube obstacle/combustible/paroi | `ignis_role="obstacle"`, `"fuel"` ou `"wall"` ; `ignis_id` ; `material_id` ; optionnel `ignis_name`. |
| Bouche (Empty) | `ignis_role="inlet"` ou `"outlet"` ; `ignis_id` ; `ignis_size_m=[largeur,0,hauteur]` selon l'axe ; `ignis_normal=[0,1,0]` ; `nominal_speed_m_s=0.2`. |
| Sonde (Empty) | `ignis_role="sensor"` ; `ignis_id` ; optionnel `ignis_name`. |
| Source (Empty) | `ignis_role="source"` ; `ignis_id`. Une seule source dans le contrat initial. |
| Groupe visuel sélectionnable | `ignis_id` identique à l'objet physique associé. La propriété est propagée aux enfants à l'export. |

Les IDs sont minuscules, commencent par une lettre et contiennent lettres,
chiffres, `_` ou `-`, sur 64 caractères maximum. Les bouches sont situées aux
frontières du domaine. Leur normale pointe **vers l'intérieur pour l'entrée**
et **vers l'extérieur pour la sortie**. Deux dimensions de bouche sont positives,
la troisième est nulle. La première version nécessite une entrée et une sortie.

Exemple de `ignis_defaults_json` à renseigner comme chaîne JSON sur la scène :

```json
{"source_model":"prescribed_source","gravity_g":0.0001,"airflow_m_s":0.2,"oxygen_percent":21,"material_id":"cellulose","ignition_power_w":500,"ignition_duration_s":15,"duration_s":60,"seed":42}
```

Les paramètres doivent également satisfaire les contrôles du backend lors de
l'import/enregistrement ; cet export ne prouve pas la stabilité numérique d'une
simulation. L'exporteur contrôle la structure, les matériaux connus, les unités,
les limites, les normales et les recouvrements.

### Valider puis exporter

```powershell
& 'E:/IGNIS-Valley/tools/blender-4.5.9-windows-x64/blender.exe' `
  --background 'E:/mes-scenes/cabine-annotee.blend' `
  --python-exit-code 2 --python tools/blender/export_scene.py -- `
  --scene-id cabine-personnelle --name 'Cabine personnelle' `
  --provenance 'Modèle original, autorisation du propriétaire' `
  --output scenes/imported/cabine-personnelle --validate-only
```

Relancer sans `--validate-only` écrit un paquet avec `catalog.json`,
`cabine-personnelle.blend`, `cabine-personnelle.glb` et `manifest.json`.
Le `.blend` source est préservé, le fichier de sortie est une copie. Les paramètres
`--visual-collection` et `--physics-collection` acceptent d'autres noms.
`--material-catalog` permet une bibliothèque enrichie, sous réserve de fournir
les propriétés physiques correspondantes au backend.
`--python-exit-code 2` garantit un code de sortie non nul si le script Blender
échoue ; les automatisations doivent aussi vérifier le marqueur final d'export.

Les scènes Aster générées contiennent elles-mêmes les annotations d'import.
On peut donc vérifier l'aller-retour avec les collections
`01_VISUAL_CUTAWAY` et `02_PHYSICAL_PROXY__enable_to_inspect`. Les résultats du
backend doivent rester distincts pour une scène importée : aucun poids entraîné
sur Aster ne garantit sa validité sur une géométrie externe.

### Aller-retour vérifié sur Soyouz

Le 14 novembre 2026, l'essai réel sur Windows avec Blender **4.5.9 LTS** a validé
le `.blend` Soyouz, exporté un paquet `soyuz-import-check`, puis rouvert et validé
le `.blend` produit. Le fichier source est resté identique par SHA-256. Le GLB
exporté conserve **326 nœuds et 12 IDs sémantiques**, sans proxies physiques,
studio ni ressource externe. Les empreintes des trois fichiers exportés ont
été contrôlées.

Les **15 objets, 2 bouches et 4 sondes** conservent leurs coordonnées à
`1,05 × 10⁻⁷ m` près au maximum, avec tous les paramètres par défaut préservés.
`compile_case` a compilé le contrat importé sans surcharge de paramètres :
maillage **15 × 15 × 15**, soit **3 375 cellules**, et **1 280 dispositifs**.
Une compilation séparée du catalogue initial donne le même masque de cellules
fluides, le même nombre de dispositifs et les mêmes boîtes discrétisées à
`10⁻⁵ m` près. Aucun calcul FDS ni nouveau rendu n'a été lancé pour cet essai.
Cette vérification porte sur le contrat d'import, pas sur la validité physique
d'une capsule réelle ni sur une nouvelle inspection visuelle.

Les preuves sont dans `evidence/blender-verification.json` et
`evidence/blender-roundtrip/final/`. L'échec initial, qui a révélé
les transformations non évaluées de la collection masquée, reste conservé dans
`evidence/blender-roundtrip/initial/`. Les scripts de reproduction Windows sont
`evidence/blender-roundtrip.py` et `evidence/blender-compare-contracts.py` ; le
premier refuse d'écraser un paquet importé existant.

## Composants et matériaux pour les incidents localisés

Le contrat accepte désormais des points électriques `ignis_role="component"`,
attachés explicitement à `source_object_id` sur sa face supérieure (`source_face=3`).
Les propriétés `combustible_material_id`, `thermal_thickness_m`, `ignis_critical`
et `ignis_passage` conservent les informations utiles aux conséquences de l'incident.
Voir [INCIDENTS.md](INCIDENTS.md) pour les propriétés, limites et le parcours.
L'export ne devine pas les propriétés thermiques à partir de l'apparence des objets.
