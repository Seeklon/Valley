# Physique IGNIS 3D — FDS 6.11.1

L'application compile les scènes en **calculs FDS 3D réellement exécutés sur le
PC Windows**. Le compilateur et le lecteur n'exécutent aucun calcul CFD sur le
VPS. Les champs affichés proviennent des sorties du solveur, pas d'une animation
paramétrique. FDS est un solveur de dynamique des fluides à faible nombre de Mach
avec transport, rayonnement et modèles de combustion ; son emploi ici reste
**exploratoire, non calibré sur les expériences NASA**.

Ce document décrit le modèle effectivement compilé. Il ne représente pas une
validation du comportement d'un incendie dans un vaisseau spatial.

## API et exécution

```python
from pathlib import Path
from ignis.physics import compile_case, parse_result

manifest = compile_case(scene, config, Path("runs/run-0001"))
# Le worker Windows lance ensuite FDS dans runs/run-0001 :
# fds.exe ignis.fds
# Il vérifie le code de sortie, le journal et l'absence d'instabilité.
result = parse_result(Path("runs/run-0001"))
```

Le répertoire doit être nouveau : un cas existant n'est pas écrasé. Les fichiers
`ignis.fds` et `manifest.json` conservent les entrées, versions, empreintes SHA-256,
dimensions originales/discrétisées, sondes et hypothèses. Le lecteur vérifie que
l'entrée n'a pas changé. Une exécution interrompue n'est pas acceptée comme
dataset complet ; `allow_partial=True` sert uniquement à l'inspection explicite.
Le code de sortie du processus reste à vérifier par l'ordonnanceur.

Toutes les longueurs sont en mètres, le temps en secondes, la puissance utilisateur
en watts et la gravité en multiples de 9,80665 m/s². Le compilateur convertit les
flux thermiques en kW/m², les puissances FDS en kW et les capacités thermiques en
kJ/(kg·K). Les valeurs de sortie sont reconverties en unités du contrat web.

## Géométrie et maillage

- Un compartiment rectangulaire, origine au coin inférieur, Z physique vers le
  haut. Les transformations d'affichage glTF ne changent pas les coordonnées FDS.
- Les objets `obstacle` et `fuel` sont des proxies parallélépipédiques alignés aux
  axes. Le GLB détaillé n'est pas interprété comme un maillage CFD.
- Les `wall` sont les limites du domaine. Leur épaisseur visuelle externe n'est
  pas ajoutée comme obstacle, afin de conserver les ouvertures de ventilation.
  Les objets `decoration` n'influencent pas le calcul.
- Les faces des proxies et des bouches sont explicitement arrondies aux plans de
  la grille. Un objet trop mince est représenté par au moins une cellule. Les
  bornes originales et finales sont conservées ; un avertissement rend ce choix
  visible. Les chevauchements, sorties du domaine, bouches bouchées et faces fuel
  supérieures couvertes sont refusés.
- La maille cible de 0,20 m donne **30 × 40 × 16 = 19 200 cellules** pour le
  compartiment 5,6 × 8 × 3,2 m. Le nombre par axe utilise les facteurs 2, 3 et 5
  adaptés au solveur de pression FDS. Une maille cible de 0,40 m donne
  15 × 20 × 8 = 2 400 cellules. Ce sont des niveaux de démonstration, pas des
  résolutions reconnues suffisantes pour des flammes millimétriques.
- La compilation refuse plus de 750 000 cellules. Ce plafond n'est pas une
  garantie de mémoire : le worker doit mesurer la consommation réelle et limiter
  la concurrence. Le plafond de sortie est de 4 096 points spatiaux par calcul.

Le changement de maille peut modifier l'aire d'une source. Le compilateur conserve
la puissance totale et recalcule son flux surfacique. Une comparaison de maillages
doit donc vérifier aussi l'aire de source, le blocage et les ouvertures ; comparer
seulement les températures serait insuffisant.

Les parois sont des feuilles d'aluminium génériques de 1 cm, conductrices avec
face arrière isolée. Les faces des équipements inertes sont également des
feuilles de 1 cm du matériau renseigné. Elles ne représentent pas la conduction
3D dans tout le volume de l'équipement. Les constantes sont des hypothèses
d'ingénierie explicites, pas des propriétés mesurées d'un équipement spatial.

## Air, ventilation et gravité

L'atmosphère est un mélange **sec O₂/N₂**, initialement homogène, à 20 °C et
101 325 Pa par défaut. `oxygen_percent` est une fraction molaire/volumique.
Le champ `Y_O2_INFTY` de FDS est massique :

\[
Y_{O_2}=\frac{x_{O_2}M_{O_2}}{x_{O_2}M_{O_2}+(1-x_{O_2})M_{N_2}}
\]

Les constantes utilisées sont 31,9988 et 28,0134 g/mol. La température et la
pression ambiantes sont configurables. L'humidité et le CO₂ ambiant sont ici nuls
et explicitement inscrits dans le manifeste. Les résultats O₂ utilisent la
quantité FDS `VOLUME FRACTION` multipliée par 100.

`airflow_m_s` est la vitesse moyenne normale dans les entrées discrétisées. Le
débit total est cette vitesse multipliée par leur aire totale. Chaque reprise
reçoit une part du même débit volumique, proportionnelle à son aire. FDS utilise
`VOLUME_FLOW` négatif en entrée et positif en sortie, indépendamment du signe de
l'axe ; `normal` identifie l'axe de la bouche. Les débits imposés et mesurés sont
exportés. À débit nul, les bouches sont fermées en vitesse.

**Ce modèle échange avec des réservoirs externes frais. Il ne recycle pas les gaz
d'une cabine fermée.** L'égalité des débits volumiques ne signifie pas égalité des
débits massiques lorsque la température change. La pression du domaine fermé et
sa masse gazeuse peuvent évoluer. Une future boucle HVAC recirculée devra porter
ses espèces et son enthalpie, sans réinjecter artificiellement de l'oxygène frais.
Les courbes de ventilateur, réseau de conduites, régulation et événements de
ventilation ne sont pas encore modélisés dans ce compilateur.

La gravité est `GVEC=(0,0,-9.80665*gravity_g)`. Zéro retire l'accélération
gravitationnelle ; l'écoulement forcé et les autres termes de transport restent
actifs. Le bruit initial FDS a une graine contrôlée par `RND_SEED`. Le manifeste
permet de répéter les entrées, sans promettre une identité bit à bit entre
versions, machines ou configurations de parallélisme.

## Sources : deux expériences numériques différentes

### Source prescrite

Un unique brûleur de surface est placé sur la face supérieure de l'objet `fuel`
le plus proche de `source_position_m`. `ignition_power_w` désigne dans ce mode la
**puissance chimique nominale**. `HRRPUA = puissance / aire_discrétisée / 1000`.
Les autres objets combustibles sont passifs ; aucune pyrolyse supplémentaire
n'est ajoutée. La combustion effective dépend du mélange et de l'oxygène.

La rampe applique la puissance pendant la durée demandée, avec une transition
de coupure de 0,01 s au maximum. L'intégrale exacte de cette consigne est stockée
dans `source.imposed_pulse_energy_j` ; l'énergie réellement libérée est calculée
à partir des sorties FDS. Ce mode étudie le transport d'un feu imposé et ne
prédit pas la puissance d'un incendie réel, ni son allumage.

### Combustion couplée aux matériaux

Les faces supérieures `fuel` portent un modèle de conduction 1D et de
décomposition. Le gaz combustible produit entre dans le calcul 3D et sa
combustion peut réchauffer les autres surfaces. Un **flux thermique externe**
chauffe seulement la face supérieure sélectionnée pendant la durée demandée.
Il n'y a aucun `HRRPUA` simultané : l'énergie chimique est produite par le calcul,
sans double comptage de l'allumage.

Dans ce mode `ignition_power_w` est la puissance incidente du chauffage. Une
puissance faible peut donner zéro inflammation, ce qui doit rester un résultat
valide. La consigne de chauffage ne doit pas être confondue avec la HRR mesurée.

Les paramètres de départ sont versionnés dans `materials.py` :

| Paramètre | Cellulose générique | PMMA noir |
|---|---:|---:|
| Masse volumique, kg/m³ | 500 | 1 100 |
| Conductivité, W/(m·K) | 0,20 | 0,20 |
| Capacité thermique, kJ/(kg·K) | 1,0 | 2,2 |
| Émissivité | 1,0 | 0,85 |
| Épaisseur active par défaut, m | 0,005 | 0,0085 |
| Enthalpie de décomposition, kJ/kg | 1 000 | 870 |
| Chaleur de combustion du gaz, kJ/kg | 16 000 | 25 200 |
| Fraction massique transformée en gaz | 0,60 | 1,00 |
| Fraction résiduelle inerte | 0,40 | 0 |

La cellulose utilise la première étape du tutoriel de TGA « dry wood » de FDS :
315 °C, 0,0056 s⁻¹, rampe TGA de 10 K/min. Le résidu est conservé inerte ici ;
l'oxydation ultérieure du char du tutoriel n'est pas reproduite. Ce n'est ni un
modèle identifié de cellulose pure ni un modèle du tissu SIBAL.

Le PMMA reprend les paramètres solides de la démonstration FAA Polymers de NIST :
`A=8.5e12 s⁻¹`, `E=188000 kJ/kmol`, coefficient d'absorption 2700 m⁻¹. Cette source
documente un essai essentiellement solide sous flux imposé. Elle ne valide pas
automatiquement le couplage gazeux ici ou une situation de microgravité.

Les gaz combustibles sont des substituts globaux C₆H₁₀O₅ et C₅H₈O₂ ; les
rendements de suie sont respectivement 0,015 et 0,020 kg/kg. La chaleur de
combustion cellulose, le substitut gazeux PMMA et son rendement de suie sont des
**hypothèses supplémentaires**. Le rendement de CO est fixé à zéro : les champs
ne permettent pas de conclure sur la toxicité d'un incendie.

Depuis `ignis-fds-materials-2`, les capacités thermiques gazeuses sont explicitement
fixées à **1,5 kJ/(kg·K)** pour le substitut cellulose et **1,8 kJ/(kg·K)** pour
le substitut PMMA. Ce sont des hypothèses génériques constantes, non des mesures
du corpus NASA. Elles évitent le défaut FDS `γR/M`, qui devient artificiellement
petit pour les molécules lourdes ; le guide NIST avertit que ce défaut peut
perturber le modèle d'extinction. La formule est déclarée dans `SPEC`, conformément
à la recommandation de FDS 6.11.1. Les propriétés moléculaires de transport non
définies utilisent toujours les relations FDS basées sur les paramètres de
Lennard-Jones de l'azote et la masse moléculaire déclarée. Les avertissements
effectivement émis par FDS sont conservés dans le résultat.

Les côtés et le dessous des objets fuel sont inertes, les objets restent fixes,
et le modèle ne fait pas disparaître leurs proxies (`BURN_AWAY` non utilisé).
Il n'y a ni fusion, gouttes, déformation, fissuration, smoldering détaillé, ni
combustion de tous les câbles visibles dans Blender. Ces choix limitent la
propagation étudiée aux surfaces actives explicitement annotées.

### Échauffement résistif

`ignition_kind=resistive` n'est accepté qu'en combustion couplée. La puissance
incidente est `I² R × heat_fraction` avec `current_a` et `resistance_ohm` ; une
entrée tension/résistance est également possible. Le courant et la résistance
sont constants. `cutoff_s`, lorsqu'il est présent, limite la durée de chauffage.
Il s'agit d'une consigne thermique localisée : pas d'arc électrique, de plasma,
de réseau de circuits, de disjoncteur I²t autonome ou d'emballement de batterie.

## Mesures spatiales et métriques

La grille d'affichage/apprentissage par défaut contient **8 × 10 × 4 points**.
Ses points sont placés sur des centres de cellules du maillage CFD, au plus près
des positions uniformes souhaitées. Leurs positions effectives figurent dans
`sample_positions_m` (une liste `[x,y,z]` par voxel) et dans `provenance.sampling`.
L'ordre est x, puis y, puis z, avec z variant le plus vite.

`sample_interval_s` fixe une cadence cible. FDS peut sortir moins d'instants si
son pas de temps est supérieur à cet intervalle : les données conservent les
`time_s` réellement écrits. Il ne faut pas interpréter l'indice d'une frame comme
un temps uniforme. Un rééchantillonnage pour le ML doit être explicite, documenté
et limité à l'intervalle effectivement simulé.

Chaque point gazeux porte six devices FDS, sans moyenne temporelle :

| Champ JSON | Quantité FDS | Conversion |
|---|---|---|
| `temperature_c` | `TEMPERATURE` | aucune |
| `oxygen_percent` | `VOLUME FRACTION`, `SPEC_ID='OXYGEN'` | × 100 |
| `smoke_kg_m3` | `DENSITY`, `SPEC_ID='SOOT'` | aucune |
| `velocity_m_s` | `U-VELOCITY`, `V-VELOCITY`, `W-VELOCITY` | 3 valeurs par point |

Les scalaires représentent la valeur de la cellule. Les composantes de vitesse
proviennent des faces décalées les plus proches de la grille FDS, et ne sont pas
une interpolation vectorielle collocative. Cette distinction importe pour les
calculs de divergence ou d'erreur physique.

`valid_mask=false` signifie point solide/non mesuré. Les valeurs correspondantes
sont `null`, y compris les trois composantes de vitesse. Aucun zéro, température
ambiante ou interpolation ne remplace ces absences. Le modèle ML doit utiliser
le masque dans sa fonction de perte et conserver la géométrie comme entrée.
Un champ manquant dans le CSV est une erreur ; une valeur non finie est conservée
comme `null` et signalée comme impropre à l'entraînement sans examen.

Les métriques globales ne sont **pas des moyennes des 320 sondes** : elles sont
calculées par FDS sur le volume gazeux complet (`VOLUME MEAN`, `MAX` et
`VOLUME INTEGRAL`). La HRR instantanée est l'intégrale volumique de `HRRPUV`, puis
convertie en watts. Son intégrale temporelle est estimée par trapèzes avec les
instants enregistrés ; elle n'est pas présentée comme un bilan énergétique exact.
La masse gazeuse totale et les débits aux bouches permettent un premier
diagnostic, sans constituer à eux seuls un bilan complet de conservation.

## Vérification et validation à poursuivre

Les tests logiciels couvrent le contrat et les erreurs d'intégration. Leurs CSV
construits pour les tests sont des fixtures, jamais des résultats scientifiques.

```text
PYTHONPATH=backend python -m unittest discover -s tests/physics -v
PYTHONPATH=backend python -m ignis.physics compile-check <nouveau-dossier> --case cold
PYTHONPATH=backend python -m ignis.physics compile-check <nouveau-dossier> --case transport
PYTHONPATH=backend python -m ignis.physics compile-check <nouveau-dossier> --case coupled
```

Les trois cas sont de petits compartiments de 2 m, 10³ cellules :

1. **Froid** : 5 s, débit imposé, aucune énergie ajoutée. Vérifier maintien de
   température et composition, directions des écoulements, débit et masse.
2. **Transport** : HRR nominale 1 kW pendant 3 s, observation 5 s. Vérifier énergie
   libérée, transport thermique et suie, puis réponse après coupure de consigne.
3. **Couplage, protocole v2** : PMMA sous 8 kW sur 0,16 m² (50 kW/m²), chauffage
   60 s, observation 90 s. Les sondes supplémentaires mesurent la température de
   surface, le flux massique de gaz combustible, l'épaisseur et le flux thermique
   net au centre de chaque face fuel. Ce sont des mesures ponctuelles, pas des
   moyennes de surface. Vérifier échauffement, décomposition puis HRR calculée.

Les versions, durées réelles et sorties d'exécutions Windows constituent les
preuves d'exécution ; la simple compilation n'en constitue pas une. Les critères
quantitatifs et études de sensibilité/convergence doivent accompagner les
campagnes avant toute interprétation prédictive du réel.

### Première série exécutée sur Windows, version physique 1

Les cinq cas suivants ont effectivement terminé sous FDS 6.11.1. Les CSV bruts
sont dans `runtime/verification-first/` ; les empreintes et la synthèse sont
conservées dans `tests/physics/evidence/verification-first.json`. Pour analyser
ces anciens cas, seule une copie temporaire de l'entrée a été convertie de CRLF
en LF, et son empreinte a été vérifiée contre le manifeste. Les fichiers originaux
sont préservés. Le compilateur utilise désormais des octets LF sur tous les OS.

| Cas | Temps physique | T maximale gaz | HRR maximale mesurée | Temps solveur annoncé |
|---|---:|---:|---:|---:|
| Froid | 5 s | 20,000009 °C | 0 W | 1,832 s |
| Source nominale 1 kW, 3 s | 5 s | 29,376 °C | 99,936 W | 1,821 s |
| PMMA chauffé 8 kW, 20 s | 30 s | 29,972 °C | 1,191 W | 2,358 s |
| Habitat, maille cible 0,40 m | 30 s | 43,617 °C | 583,655 W | 2,150 s |
| Habitat, maille cible 0,20 m | 30 s | 87,702 °C | 830,860 W | 4,853 s |

Le cas froid conserve 21 % d'O₂ et 9,5179746 kg d'air ; les débits mesurés sont
−0,032 et +0,032 m³/s. Les cas habitat donnent −0,1792 et +0,1792 m³/s. Les
signaux contiennent des réponses thermiques et de suie, sans valeurs non finies.

La source nominale prescrit un débit de combustible : sa puissance chimique
réellement brûlée peut être très inférieure ou décalée dans le temps. Cette série
ne doit pas être présentée comme une source thermique constante de 1 kW mesurée.
Le chauffage PMMA de 20 s a produit une pyrolyse extrêmement faible, d'où le
protocole plus long et l'instrumentation de surface ajoutés en version 2.

Le changement de maille de l'habitat modifie la masse d'air initiale de
141,70524 à 150,79465 kg, car les obstacles sont discrétisés différemment. Les
grands écarts de température/HRR **ne démontrent aucune convergence**. Cette
première série précède également la correction du Cp gazeux : les campagnes de
version 2 doivent rester identifiées séparément, sans mélange silencieux pour
l'apprentissage. Les temps ci-dessus sont ceux des logs FDS et ne comprennent
pas nécessairement l'ensemble du chargement, du parsing et des transferts.

### Deuxième série exécutée sur Windows, version physique 2

Les cinq cas ont été réexécutés avec `ignis-fds-2`,
`ignis-fds-materials-2` et FDS 6.11.1. Les entrées LF et leur empreinte concordent
sans adaptation. Les CSV bruts sont dans `runtime/verification-v2/` et la preuve
normalisée dans `tests/physics/evidence/verification-v2.json`.

| Cas | Temps physique | T maximale gaz | HRR maximale mesurée | Temps du runner |
|---|---:|---:|---:|---:|
| Froid | 5 s | 20,000009 °C | 0 W | 2,296 s |
| Source nominale 1 kW, 3 s | 5 s | 29,358 °C | 99,958 W | 2,297 s |
| PMMA chauffé 8 kW, 60 s | 90 s | 131,935 °C | 11 393,855 W | 4,360 s |
| Habitat, maille cible 0,40 m | 30 s | 43,556 °C | 583,672 W | 2,906 s |
| Habitat, maille cible 0,20 m | 30 s | 87,317 °C | 830,383 W | 5,391 s |

`assess_verification` accepte les trois cas de contrôle. Ils atteignent la durée
requise, les débits mesurés sont −0,032/+0,032 m³/s et aucun champ spatial non
fini n'apparaît. Le cas froid conserve 21 % d'O₂, sa température s'écarte de
moins de 0,00001 °C et sa HRR est nulle. Les cas chauffés produisent effectivement
une réponse thermique, de la suie et une HRR mesurées.

Dans le cas couplé, la sonde de surface mesure un maximum de **378,173 °C** et
un flux combustible de **0,003191394 kg/(m²·s)** vers 60,10 s. L'épaisseur passe
de 8,5 à 8,47486 mm à 90 s. L'intégrale échantillonnée de HRR est d'environ
**103 609 J**. L'allumage thermique de 60 s produit donc une décomposition puis
une combustion mesurables, sans imposer leur HRR. Ce contrôle ne démontre pas
la précision du modèle de pyrolyse ni la propagation entre plusieurs objets.

L'écart de température entre les deux maillages d'habitat demeure important ;
cette série **ne démontre toujours pas la convergence**. Les sondes froid/transport
donnent huit instants seulement sur cinq secondes, contre 91 instants pour le
couplage de 90 s : conserver les temps réels demeure nécessaire. Les critères
de `assess_verification` sont des contrôles d'intégration logiciel/solveur, pas
des seuils de validation expérimentale NASA. Le traitement instrumental réel
de BASS-II est documenté séparément dans [NASA.md](NASA.md).

Pour BASS/BASS-II, il faut reproduire dimensions d'échantillons, épaisseurs,
vitesses calibrées, atmosphère, protocole et critères d'observation. Une cabine
de plusieurs mètres ne peut pas être comparée directement à un échantillon BASS.
Le modèle de combustion turbulent/mélange de FDS sur une grille grossière ne
résout pas une flamme laminaire diffusante de microgravité, ses limites
d'extinction, flammes froides ou cinétique détaillée. Mettre `gravity_g=0` ne
supprime pas cette limite. La gravité partielle reste exploratoire.

Une étude NASA de Saffire V utilise FDS avec des sources mesurées pour calculer
des effets dans une cabine, et ne constitue pas une validation directe de la
flamme couplée. Les sources NASA ont une provenance séparée des simulations et
des prédictions. Un modèle entraîné sur les sorties présentes apprend en premier
lieu un substitut du solveur dans ce domaine d'entrée ; l'accord avec des essais
NASA indépendants reste une évaluation distincte.

## Références consultées

- [FDS, documentation officielle NIST](https://pages.nist.gov/fds-smv/manuals.html).
- [Guide utilisateur, source version FDS 6.11.1](https://github.com/firemodels/fds/blob/FDS-6.11.1/Manuals/FDS_User_Guide/FDS_User_Guide.tex) :
  `Velocity_BC`, `AIR`, `OBST_Basics`, `reaction_mechanism`,
  `simulating_the_cone_calorimeter`, `NOISE`, `statistics`, `DEVC`.
- [Exemple PMMA FAA Polymers](https://github.com/firemodels/fds/blob/FDS-6.11.1/Validation/FAA_Polymers/FDS_Input_Files/FAA_Polymers_PMMA.fds).
- [Tutoriel TGA dry wood/cellulose](https://github.com/firemodels/fds/blob/FDS-6.11.1/Verification/Pyrolysis/tga_analysis.fds).
- [Rapport NASA BASS-II](https://ntrs.nasa.gov/citations/20210011385).
- [NASA, modélisation de Saffire V](https://ntrs.nasa.gov/citations/20240008602).

Les paramètres empiriques retenus dans IGNIS sont identifiés séparément des
paramètres repris de ces références. Aucun ajustement sur BASS-II n'est revendiqué.
