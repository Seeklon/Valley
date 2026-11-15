# Audit du signal thermique avant un nouvel essai GPU

## Conclusion

Deux problèmes distincts sont mesurables sur les **données d'entraînement** :
les foyers thermiques occupent très peu de sondes et la contribution initiale
de la suie à la perte spatiale est beaucoup plus grande que celle de la
température. Il reste cependant de vrais pics échantillonnés, jusqu'à
**372,06 °C** : un diagnostic d'apprentissage sur ces cas est pertinent.
Augmenter la capacité ou multiplier les époques n'est pas encore une solution
démontrée. Aucun défaut qui effacerait systématiquement la source ou le temps
n'a été identifié dans les entrées examinées.

Les archives existantes ne contiennent **aucun champ dense supplémentaire**
permettant de récupérer les pics manqués par les sondes. Il ne faut ni inventer
leur localisation à partir du maximum global, ni traiter une température de
paroi comme une température du gaz.

## Périmètre et provenance

Audit en lecture seule, sans FDS, sans apprentissage et sans sélection à partir
du test réservé. Les calculs ci-dessous portent sur les **120 cas / 60
dispositions train** de `E:/IGNIS-Valley-dev/datasets/spatial-compact-200-v1`.
Ce dossier contient 200 cas au total et conserve l'identifiant logique
`spatial-compact-v1`. Les 50 cas historiques qui complétaient l'entraînement
précédent ne sont pas inclus dans les statistiques ci-dessous.

- SHA-256 de `manifest.json` :
  `ee4026c94a6cd29f6d036262e23f374fe702f2dd9a766cf45172afa9c188cbac`.
- Les 120 empreintes `npz_sha256` ont été recalculées et comparées à l'index.
- Les listes de membres des 120 ZIP FDS concordent avec `raw_members_sha256`.
  Deux cas ont également fait l'objet d'une comparaison brute détaillée décrite
  plus bas ; les contenus de tous les CSV n'ont pas été reparcourus.
- Révision locale examinée : `eed0d9c9c88b9e96a0bcc6d0443f359d74c85dd7`.
  SHA-256 de `backend/ignis/ml/spatial_network.py` :
  `d03c25cc2aafd90c437222c83bd432bb227fb2fd53bd4100ceee8137b166f1b7`.

Méthode : filtrer `split == train`, lire les coordonnées et masques du NPZ,
exclure `t == 0`, définir chaud par `T >= ambiance + 5 °C` et fumée par
`S >= 1e-7 kg/m³`. Les fractions portent sur des **points × instants corrélés**.
Les distances utilisent les coordonnées réelles et le centre du patch source
du manifeste. Le maximum global FDS et le maximum aux sondes sont calculés
séparément, sans supposer leur égalité ou leur simultanéité.

## Ce que les cibles permettent réellement d'apprendre

| Mesure sur les 120 cas train compacts | Résultat |
| --- | ---: |
| Cas contenant au moins un point chaud | 68 / 120 |
| Observations chaudes / observations valides après t=0 | 12 954 / 5 358 116, soit 0,242 % |
| Nombre médian de positions ayant été chaudes dans un cas | 1 |
| Nombre médian d'instants contenant un point chaud | 4 |
| Distance médiane entre source et sonde gaz la plus proche | 0,229 m |
| Distance maximale entre source et sonde gaz la plus proche | 0,509 m |
| Cas sans sonde gaz à moins de 0,25 m de la source | 38 / 120 |
| Cas sans sonde gaz dans la colonne verticale du patch | 112 / 120 |
| Cas avec pic global ≥25 °C mais toutes les sondes <25 °C | 32 / 120 |
| Médiane des maxima par cas aux sondes | 25,79 °C |
| Médiane des maxima globaux FDS par cas | 75,83 °C |

La colonne verticale signifie ici une position gaz au-dessus de la face
supérieure et dont x/y appartiennent à l'emprise du patch. Elle ne décrit pas
la direction réelle du panache, particulièrement en microgravité.

La rareté dépend fortement du type d'incident : **0/24 arcs**, 9/24 batteries,
24/24 flammes imposées, 19/24 surchauffes et 16/24 émissions couvantes ont des
points chauds mesurés. Ce sont les incidents équivalents du compilateur, pas des
modèles complets de plasma, d'emballement électrochimique ou de combustion
couvante. L'absence de point chaud gaz n'est pas une preuve d'absence
d'échauffement du composant.

Le temps est également sous-échantillonné pour certains événements. Les 24
arcs ont une impulsion de 1 s, mais **aucun n'a de mesure strictement entre
0 et 1 s**. L'état initial et l'après-impulsion ne supervisent pas le pic pendant
l'impulsion. Sur tout le compact train, 116 cas ont 31 instants, les quatre
autres en ont 25, 24, 21 et 29 ; l'écart maximal entre instants réels est
1,851 s. Les chargeurs utilisent ces temps réels, sans les remplacer par des
entiers. Le maximum aux sondes survient au dernier instant dans 38/120 cas,
dont 19 cas chauds : l'horizon de 30 s peut tronquer leur évolution ultérieure.

### Vérification des archives et exemples

Les 120 archives contiennent exactement `engine.log`, `ignis.out`, `ignis.smv`,
`ignis_cpu.csv`, `ignis_devc.csv`, `ignis_git.txt`, `ignis_hrr.csv` et
`ignis_steps.csv`. Aucun fichier de coupe, de volume ou de Plot3D ne contient
des températures plus denses à récupérer. Le fichier SMV décrit la scène et
les sorties disponibles ; il ne fournit pas les champs absents.

Deux cas train ont été comparés entre NPZ, `result.json.gz` et CSV DEVC brut :

| Cas | Maximum aux sondes | Maximum global | Contrôle brut |
| --- | ---: | ---: | --- |
| `procedural-0003-electrical-03-overheating-microg-c0` | 372,06003 °C | 443,32846 °C | `P0548_T = 372,06004` à 29,220199 s |
| `procedural-0090-electrical-03-battery-microg-c1` | 23,39082 °C | 477,94180 °C | `P0371_T = 23,390818` à 30 s |

Les empreintes du résultat compressé et du CSV brut concordent avec l'index.
Les matrices T et suie du NPZ sont exactement égales à celles du JSON converties
en float32, valeurs absentes comprises. Le second cas démontre qu'un foyer
global intense peut être absent des cibles spatiales sans erreur d'extraction.
À l'instant de son maximum global, son maximum aux sondes n'est que 20,10 °C.

Les deux archives contiennent aussi de vrais U/V/W et O2 aux sondes. Le premier
cas a 139 221 composantes de vitesse finies, le second 137 733 ; ce sont trois
composantes par point gaz et par instant. Leurs modules maximaux de composante
sont respectivement 0,183 et 0,286 m/s. Ces données sont utilisables pour une
supervision auxiliaire future ; elles ne densifient pas les mesures de T.

Chaque cas compact dispose aussi de deux sondes gaz supplémentaires et de 5 à
14 sondes de surface. Aucune sonde gaz supplémentaire n'est à moins de 25 cm du
foyer : la distance minimale observée est 0,669 m. Une sonde de surface existe
sur l'objet source dans les 120 cas, mais le compilateur exclut le patch de
brûleur/émetteur pour les incidents non thermiques. Les températures de ces
parois et flux de pyrolyse sont des cibles distinctes des températures du gaz.

## Perte, échelle physique et gradients

La cible thermique est `asinh((T - ambiance) / 20)`. Les écarts de 5, 20,
100 et 352,06 °C deviennent respectivement 0,2475, 0,8814, 2,3124 et 3,5620.
Le codage ne supprime pas les pics, mais compresse leur amplitude. La dérivée
de SmoothL1 est plafonnée dès que l'erreur encodée dépasse 1 : à prédiction
ambiante, un pic à +100 °C et un pic à +352 °C reçoivent le même module de
dérivée locale avant pondération. Le plafonnement de décodage n'intervient pas
dans la perte d'entraînement.

La perte historique calcule, par frame, `sum(w * SmoothL1) / sum(w)`, en sommant
ensemble les deux champs et les positions. `w=5` sur points actifs et `w=1`
ailleurs, avec zéro sur valeurs non observées. Il n'y a pas de normalisation
indépendante des tâches T et suie. À sortie ambiante, moyenne des frames puis
des 120 cas, **hors terme global pondéré par 0,25** :

| Contribution | Température | Suie | Ratio suie / T |
| --- | ---: | ---: | ---: |
| Perte spatiale | 0,0008441 | 0,0693188 | 82,1 |
| Somme des modules de dérivée par rapport aux sorties encodées | 0,0027091 | 0,0553064 | 20,4 |

La température représente seulement 1,20 % de la valeur initiale de cette
perte spatiale. Ces chiffres établissent un déséquilibre de signal, **pas** une
preuve de domination de la suie dans chaque gradient de paramètre : le
Jacobien du réseau, Adam et les tâches globales modifient leur contribution.
Ils motivent une ablation de tâche plutôt qu'un diagnostic causal acquis.

Les têtes de sortie sont initialisées à zéro. Cela impose l'ambiante au départ
et rend nul le gradient vers l'encodeur lors du tout premier passage arrière ;
les têtes reçoivent néanmoins un gradient et débloquent ensuite cet apprentissage.
Les anciens diagnostics ont appris des foyers : aucun blocage permanent de
sortie n'est démontré. Les deux réductions par moyenne peuvent affaiblir un
signal très local, mais les connexions U-Net conservent une voie à la résolution
des sondes. Leur présence ne remplace pas des cibles physiques manquantes.

La tête globale est séparée de la tête spatiale. Ne pas imposer une égalité
entre le maximum du champ échantillonné et `G_TMAX` : elle contredirait les
cibles dans les 32 cas mentionnés plus haut. Un terme de pic spatial doit
utiliser **le maximum observé aux mêmes sondes et au même instant**.

## Source, géométrie et conditions

Le calcul effectif de `geometry_channels` donne 60 tenseurs statiques distincts
pour 120 cas : les paires terre/microgravité partagent la scène et se distinguent
dans les conditions. Les sources ne sont donc pas toutes identiques. En
revanche, chaque disposition compacte ne possède qu'**un site et un type
d'incident**, appariés sur les deux gravités. Ce lot ne teste pas, dans une même
géométrie, la dépendance à plusieurs positions de départ.

Le canal `source_patch_fraction` est non vide dans 120/120 cas. Son maximum
varie de 0,05 à 0,267 et sa somme de 0,133 à 0,333. Sa projection sur la couche
de sondes la plus proche se trouve entièrement dans des cellules marquées
solides dans 22/120 cas. Le réseau reçoit tout de même ces valeurs : le masque
supprime les cibles gaz solides, pas les entrées. Les canaux `source_dx/dy/dz`,
distance et position scalaire conservent aussi le site exact. Cette projection
est une approximation de représentation à tester ; elle n'efface pas la source.

Dans chacun des 120 cas, les quatre conditions temporelles varient : temps,
durée écoulée, temps après source et facteur de rampe. Ambiance et pression
sont les seules conditions constantes sur tout ce lot. Le temps n'est donc
pas accidentellement figé. Toutes les temporisations de départ sont nulles.
Le calcul de durée écoulée ne soustrait pas `ignition_delay_s` et ce délai n'a
pas son propre canal : c'est une limite à traiter avant d'ajouter des départs
retardés, pas une explication des erreurs du compact actuel.

## Trois tests discriminants, dans cet ordre

1. **Vérifier l'apprentissage d'un pic déjà observé.** Sur un ou quelques cas
   train compacts forts, fixer les mêmes frames et initialisations. Comparer
   objectif historique multitâche et régression température seule, sans perte
   suie ni globale. Conserver des frames calmes et mesurer pic, localisation,
   rappel et faux positifs sur ces cas d'ajustement. Si la température seule
   s'ajuste et pas le multitâche, investiguer le partage de pertes/gradients.
   Si aucun ne s'ajuste, vérifier directement tête, gradients et optimisation
   avant d'interpréter l'échec comme un manque de généralisation.
2. **Comparer échantillonnage uniforme et échantillonnage d'instants chauds.**
   Garder même objectif, cas, seed, nombre de mises à jour et évaluateur ;
   mélanger instants actifs et calmes. Sélectionner sur validation et détailler
   erreurs de pic, support chaud et fausses alertes. Une amélioration mesurera
   l'utilité de réexposer des cibles existantes ; elle ne créera pas le signal
   absent des arcs ou des foyers entre les sondes. Ne pas cumuler dans ce même
   A/B changement d'architecture, d'échelle et de pondération de tâche.
3. **Ne densifier qu'un petit témoin physique si les tests précédents plafonnent.**
   Pour un prochain essai explicitement budgété, reprendre un cas train
   conservant un fort pic et un cas train manqué par les sondes ; garder le
   solveur/maillage fixés et ajouter des sondes près de la source et des mesures
   temporelles pendant le pulse. Comparer convergence des mesures et coût avant
   une campagne. Ce test n'a pas été exécuté dans cet audit. Il distingue
   manque de supervision et besoin de capacité ; la convergence du maillage
   physique devra être examinée séparément.

Aucun score de cet audit n'est une nouvelle performance de généralisation.
Le test réservé ne doit pas décider de ces recettes ; si ses résultats ont
guidé un développement, la nouvelle version nécessitera un autre test figé.
