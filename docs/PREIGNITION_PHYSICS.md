# Modèle électrothermique local avant feu

`ignis.preignition.thermal.simulate_thermal(config)` calcule l'échauffement d'un
fil de laboratoire NiCr/LDPE, la fusion de son isolant et une petite perte de
masse par pyrolyse. **Il ne calcule pas l'allumage.** Les sorties portent toujours
`summary.ignition_supported=false`, `ignition_time_s=null` et
`ignition_probability=null`. Toutes les températures sont **simulées**.

Ce modèle a des vérifications numériques décrites ci-dessous. Il n'a pas de
validation thermique expérimentale : les points de délai d'allumage extraits
d'une publication ne mesurent pas sa température de surface et ne valident pas
ce solveur. Un éventuel estimateur empirique de délai d'allumage reste un autre
modèle, avec son propre domaine et sa propre évaluation.

## Source et matériau couverts

Guo, Kawaguchi, Hashimoto et Fujita, « Identifying two ignition modes of polymer
insulated wires with continuous excess current in microgravity », *Fire Safety
Journal* 141 (2023), 103925,
[DOI](https://doi.org/10.1016/j.firesaf.2023.103925),
[manuscrit auteur accessible](https://hdl.handle.net/2115/95853).
Les pages citées ici sont celles du manuscrit, après la couverture du dépôt.

| Grandeur | Valeur utilisée | Localisation |
|---|---:|---|
| Longueur utile, rayon du conducteur, épaisseur d'isolant | 70 mm ; 0,25 mm ; 0,15 mm | Page 2, §2 |
| Résistivité électrique NiCr à température ambiante | 1,1 × 10⁻⁶ Ω·m | Page 2, §2 |
| Masse volumique NiCr ; LDPE solide | 8 410 ; 920 kg/m³ | Page 4, tableau 2 |
| Chaleur massique NiCr ; LDPE solide ; liquide | 481 ; 2 300 ; 2 500 J/(kg·K) | Page 4, tableau 2 |
| Conductivité NiCr ; LDPE solide ; liquide | 17,4 ; 0,34 ; 0,25 W/(m·K) | Page 4, tableau 2 |
| Émissivité LDPE solide ; liquide | 0,3 ; 0,1 | Page 4, tableau 2 |
| Température et chaleur latente de fusion | 391,15 K ; 140 600 J/kg | Page 4, texte |
| Préfacteur et énergie d'activation de pyrolyse | 5 × 10¹⁸ s⁻¹ ; 300 000 J/mol | Page 4, équation 1 |
| Chaleur absorbée par pyrolyse | 962 000 J/kg | Page 4, texte |

La valeur arrondie de résistivité donne 5,60 Ω/m pour ce rayon ; les auteurs
rapportent une résistance mesurée de 5,5 Ω/m ±7 %. Le calcul utilise la
résistivité et la géométrie, sans les mélanger avec une résistance de contact.
Il conserve une résistance constante avec la température par défaut, comme le
modèle de l'article. Aucun coefficient thermique du NiCr étudié n'a été ajusté.
Un coefficient linéaire non nul reste une **hypothèse utilisateur de sensibilité**.

La masse volumique liquide de 760 kg/m³ publiée n'est pas utilisée pour modifier
la géométrie. L'expansion, le déplacement du polymère fondu et l'exposition du
conducteur ne sont pas résolus. Le conducteur est un nœud isotherme ; sa
conductivité est conservée comme propriété documentaire, sans prétendre résoudre
une conduction axiale distribuée. La conductance vers les supports est une
entrée explicite du scénario.

La figure 2 indique 20 °C, 1 atm, 21 % d'O₂, g=0 et une paroi à 20 °C pour le
**modèle numérique de l'article**. Ces valeurs servent de scénario de départ ;
elles ne sont pas présentées comme une télémétrie thermique mesurée. Le fil
NiCr/LDPE étudié n'est pas un câble qualifié pour un véhicule spatial ni un
connecteur réel de Soyouz. Modifier sa géométrie produit un scénario synthétique,
pas un nouveau matériau validé.

## Équations et bilan

Deux nœuds thermiques représentent le conducteur et l'isolant. Le nom de sortie
`surface_temperature_k` désigne la température représentative de l'isolant ;
la variation radiale de température n'est pas résolue.

La résistance est `R(Tc)=ρe L/(π rc²) × [1+α(Tc−293,15)]` et le chauffage
`Pj=I²R`. Le courant est imposé, constant par morceaux. Aucune résolution de
circuit, résistance de contact, coupure automatique, rupture ou arc n'est ajoutée.

La conductance radiale approchée vaut
`G=2π k L/ln(ro/rc)`, avec conductivité de l'isolant interpolée suivant sa
fraction liquide. Le transfert interne est `Qci=G(Tc−Ts)`.
Le nœud conducteur contient `Uc=mc cp,c (Tc−293,15)`.

L'enthalpie spécifique `h(Ts,f)` de l'isolant est référencée au solide à
293,15 K : chaleur sensible solide jusqu'à 391,15 K, palier de fusion de
140 600 J/kg à température constante, puis chaleur sensible liquide. La fusion
et la solidification sont réversibles dans ce modèle d'équilibre. Il ne prend
pas en charge le sous-refroidissement ou l'hystérésis. `Up=m h` utilise la
**masse restante**, qui diminue pendant la pyrolyse.

Pour l'isolant entièrement fondu, la cinétique choisie est
`q = −dm/dt = m A exp(−Ea/(Rgas Ts))`, sans résidu solide. C'est une adaptation
explicite en fraction de masse restante des paramètres publiés, pas une copie
de mots-clés entre versions FDS. Avant fusion complète, `q=0`.

Les équations d'énergie sont :

```text
dUc/dt = Pj − Qci − Qsupport
dUp/dt = Qci − Qgas − Qrad − q Lpyro − q h
dm/dt  = −q
```

Le terme `q h` retire l'enthalpie de la matière quittant le nœud. Le gaz produit
n'est pas conservé comme un nouveau nœud thermique : son transport, sa
température ultérieure et ses réactions restent hors modèle. L'approximation
d'énergie transportée est l'enthalpie instantanée du polymère retiré ; la chaleur
de pyrolyse représente le coût supplémentaire de transformation.

Les intégrales sont calculées dans le même système différentiel et exportées :

```text
input_energy_j = stored_energy_j + loss_energy_j
                 + pyrolysis_energy_j + carried_energy_j + balance_error_j
loss_energy_j = convection_energy_j + radiation_energy_j + support_energy_j
```

`stored_energy_j` est la variation de l'énergie interne des deux nœuds depuis
l'état initial, avec la masse restante. Les pertes sont signées : des supports
ou une enceinte plus chauds peuvent apporter de l'énergie, donc produire une
« perte » négative. `convection_energy_j` inclut, pour compatibilité du schéma,
le transfert par conduction dans le gaz stagnant ; `heat_transfer_regime` précise
le mécanisme retenu. Le bilan est recomposé indépendamment à partir des colonnes
exportées par `audit_energy_balance` ; un écart supérieur à 10⁻⁶ J fait échouer
le calcul, au lieu de produire un exemple supposé sain.

## Échanges avec le contexte

`heat_transfer_mode` propose trois modes :

- `auto` : conduction gazeuse, corrélation d'écoulement transversal lorsque son
  domaine est respecté, convection naturelle seulement à 1 g.
- `prescribed_h` : coefficient fourni explicitement dans
  `heat_transfer_coefficient_w_m2_k`, pour une hypothèse ou une mesure externe.
- `adiabatic` : transfert gazeux nul, utile pour les vérifications analytiques.
  Le rayonnement et les supports restent des termes séparés.

En gaz stagnant, la microgravité supprime la flottabilité, **pas la conduction
thermique**. Le modèle utilise la solution stationnaire cylindrique
`hgas=kair/[ro ln(Rambient/ro)]`. Le rayon extérieur isotherme
`gas_conduction_radius_m`, 70 mm par défaut, est une hypothèse explicite inspirée
de la demi-largeur du domaine de l'article. Il ne reproduit pas la diffusion
transitoire de chaleur dans le gaz ni les parois rectangulaires de la chambre.

Le transfert forcé suit la corrélation de
[Churchill–Bernstein (1977)](https://doi.org/10.1115/1.3450685) pour un cylindre
en écoulement **transversal**, avec garde conservatrice `Re Pr ≥ 0,4` et
`Re ≤ 10⁷`. En dehors de ce domaine, ce terme n'est pas utilisé. Une vitesse
parallèle au câble ne peut pas être interprétée comme une vitesse transversale.

À **1 g uniquement**, la corrélation de
[Churchill–Chu (1975)](https://doi.org/10.1016/0017-9310(75)90222-7) pour un
cylindre horizontal est utilisée si `10⁻⁵ ≤ Ra ≤ 10¹²`. Les autres gravités,
y compris la gravité résiduelle d'un vol parabolique, n'activent pas cette
corrélation terrestre : leur flottabilité n'est pas résolue. Ainsi, ce prototype
ne produit pas une interpolation validée entre 0 g, la Lune, Mars et 1 g.

Le maximum des coefficients disponibles est une approximation de mécanisme
dominant ; ce n'est pas une solution de convection mixte. Les valeurs d'air
`k=0,0257 W/(m·K)`, `μ=1,81×10⁻⁵ Pa·s`, `cp=1005 J/(kg·K)` sont des
approximations d'ingénierie constantes à température ambiante, sans calibration
sur l'essai. Seule la masse volumique varie par le gaz parfait à la température
de film, avec `Rair=287,05 J/(kg·K)`. Leur précision se dégrade à chaud ; le calcul
n'est pas une solution de transport thermophysique haute fidélité.

Le rayonnement est `ε σ A (Ts⁴−Trad⁴)`, avec une enceinte environnante isotherme
et un facteur de vue de 1. La conductance de support donne
`Qsupport=Gsupport(Tc−Tsupport)` ; sa valeur nulle par défaut déclare des supports
axialement adiabatiques. Aucun échange avec un solveur de cabine n'est installé
dans ce module : vitesse d'air et températures sont des conditions prescrites.
`oxygen_percent` est conservé comme contexte, sans effet chimique dans ce modèle.

## Contrat, événements et limites

```python
from ignis.preignition.thermal import simulate_thermal

trajectory = simulate_thermal({
    "material_preset": "nichrome_ldpe_guo2023",
    "wire_length_m": 0.07,
    "core_radius_m": 0.00025,
    "insulation_thickness_m": 0.00015,
    "current_profile": [
        {"time_s": 0.0, "current_a": 2.0},
        {"time_s": 3.0, "current_a": 4.0},
    ],
    "cutoff_s": 4.0,
    "duration_s": 20.0,
    "sample_interval_s": 0.1,
    "max_step_s": 0.02,
    "gravity_g": 0.0,
    "airflow_m_s": 0.0,
})
```

Le dictionnaire d'entrée est copié et validé ; les champs inconnus sont refusés.
Le profil doit commencer à zéro et ses dates doivent croître strictement. Il
remplace `current_a` lorsqu'il est fourni. La coupure annule tous les courants
ultérieurs, tout en continuant l'évolution thermique. Les valeurs instantanées
aux changements de courant correspondent au côté droit du changement ; aucune
énergie impulsionnelle n'est ajoutée. Les points de changement et la dernière
date observée sont ajoutés à l'échantillonnage régulier.

La sortie contient `schema_version`, `config`, `samples`, `events`, `summary`,
`provenance` et `limitations`. Les unités figurent dans les noms. Chaque sample
contient courant, tension, résistance, températures, fraction liquide, masse
restante et perdue, puissances et énergies cumulées. Les fractions de pyrolyse
sont rapportées à la masse initiale d'isolant ; `melt_fraction` concerne la masse
**restante**. Les pics du résumé utilisent les pas internes acceptés du solveur,
plus fins que l'échantillonnage de sortie.

Les événements enregistrent la première atteinte de chaque condition, y compris
un état initial qui la satisfait. Ils ne sont jamais des événements de feu :

| Événement | Sens |
|---|---|
| `melting_started`, `melting_completed` | Début et fin du palier d'enthalpie de fusion |
| `mass_loss_reporting_fraction_reached` | Perte cumulée de 0,1 % par défaut ; seuil de restitution, pas initiation chimique |
| `user_surface_thermal_limit` | Limite thermique fournie avec un libellé `surface_limit_source` obligatoire |
| `electrical_cutoff` | Coupure électrique explicitement programmée |
| `fixed_geometry_mass_loss_limit` | Arrêt par défaut à 1 % de perte de masse |
| `maximum_temperature_limit` | Arrêt numérique de domaine à 1 200 K par défaut |

Les deux dernières conditions sont des gardes du modèle, pas des seuils de
danger, des points expérimentaux ni des valeurs d'allumage. La limite de perte
de masse est configurable jusqu'à 10 %, ce qui n'établit pas une validité
physique jusqu'à cette valeur. Après un arrêt de domaine, les températures
ultérieures sont inconnues. Même un calcul achevé sans événement ne constitue
pas un label « absence de feu ».

Les sources citées ne permettent pas de remplacer la chimie du gaz par une
température arbitraire : l'article décrit notamment une inflammation éloignée
du fil dans un nuage de pyrolyse. Ni les arcs, ni les batteries, ni les contacts
électriques, ni les fréquences réelles de défaut ne sont couverts ici.

## Vérifications numériques reproductibles

Le système d'enthalpie utilise `scipy.integrate.solve_ivp`, méthode RK45,
tolérance relative 10⁻⁶ par défaut, pas maximal 0,05 s. Chaque discontinuité de
courant démarre un intervalle d'intégration distinct. Les événements de domaine
arrêtent l'intégration à leur racine. Les petites bornes internes de masse et
température servent uniquement à rendre évaluables des étapes d'essai RK hors
domaine ; le trajet accepté s'arrête avant ces états.

Les tests de `tests/physics/test_preignition_thermal.py` vérifient :

| Vérification | Critère fixé |
|---|---|
| Équilibre sans courant | Températures constantes à 10⁻¹⁰ K près |
| Solution analytique à deux nœuds sous fusion | Écart ≤3×10⁻⁶ K ; énergie à 10⁻⁹ J près |
| Courant variable et coupure entre deux sorties | Intégrale analytique de `I²R` à 10⁻⁸ J près |
| Coupure courte | L'isolant peut continuer à chauffer pendant que le conducteur refroidit |
| Fusion | Palier à 391,15 K ; énergie latente de 140 600 J/kg |
| Pyrolyse | Arrêt à la fraction choisie ; chaleur de réaction et enthalpie emportée présentes |
| Échanges thermiques | Refroidissement par gaz, rayonnement et supports, bilan signé |
| 0 g / 1 g / écoulement forcé | Conduction gazeuse conservée à 0 g, différences thermiques attendues |
| Raffinement temporel analytique | Erreur finale <10⁻⁸ K et >100 fois plus faible au pas fin |
| Raffinement avec changements de phase et pyrolyse | Dates à 0,002 s et pic isolant à 0,1 K près |
| Domaine et provenance | Champs invalides refusés, aucun événement étiqueté allumage |

Exécution depuis le dépôt :

```bash
python -m pytest tests/physics/test_preignition_thermal.py
```

Ces contrôles ne mesurent ni erreur expérimentale, ni avance d'alerte, ni taux
de fausses alertes. Le modèle reste une référence de précurseurs thermiques et
un outil de sensibilité sous hypothèses déclarées, pas une qualification de
sécurité ni une probabilité de départ de feu.
