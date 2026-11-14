# Incidents localisés — `ignis-incidents-1`

Le compilateur traduit un **incident supposé sur un composant annoté** en une
condition de frontière FDS 6.11.1. Il calcule ensuite le transport et la réponse
des surfaces combustibles. Il ne calcule ni la fréquence du défaut électrique,
ni sa probabilité, ni la probabilité d'allumage d'un véritable équipement.

L'activation exige les deux champs `incident_type` et `component_id`. La valeur
de `source_model` reste dans la configuration ; `incident_type` choisit
explicitement la condition de source, décrite dans `manifest.incident`.
Une sélection incomplète ou inconnue échoue. Aucun incident n'est redirigé vers
le coupon `fuel_sample`, même s'il est le combustible le plus proche.

Sans cette paire, le compilateur conserve `ignis-fds-2` et son comportement
historique. Les trois cas de vérification existants ont été enregistrés avant
modification : leurs decks sont identiques octet par octet, et leur texte JSON
est inchangé, aux fins de ligne propres à chaque plateforme près.

## Géométrie et matériaux

Un composant doit référencer un objet physique `fuel` ou `obstacle`, avec une
position en mètres sur sa **face supérieure originale** :

```json
{
  "id": "power-connector",
  "object_id": "console",
  "position_m": [0.5, 0.3, 0.4],
  "face": 3,
  "provenance": "Annotation synthétique de démonstration"
}
```

La source appliquée est un `VENT` d'une cellule sur la face supérieure du proxy
après alignement au maillage. L'annotation originale est vérifiée avant cette
projection ; le rectangle final est vérifié ensuite. Une position perdue par
la discrétisation, un obstacle au-dessus ou le plafond invalident la source.
Deux sites d'un même objet qui tombent dans la même cellule sont refusés :
il faut raffiner le maillage pour les distinguer. Un recouvrement partiel
ailleurs sur l'objet ne bloque pas une source exposée.

Le manifest conserve `requested_position_m`, `position_m` (centre du rectangle
appliqué), `bounds_m`, `area_m2`, `face`, `object_id`, `component_id` et la
provenance de l'annotation. Les faces latérales et inférieures ne sont pas
encore des sites de départ pris en charge.

Les matériaux du modèle 3D restent explicites :

- `material_id` décrit le matériau original de l'objet.
- `combustible_material_id`, s'il existe, définit une couche combustible sur
  la face supérieure : `pmma` ou `cellulose`.
- Pour un objet `role=fuel`, son propre `material_id` est le combustible par
  défaut ; le choix global de la configuration ne le remplace plus dans cette
  branche.
- `thermal_thickness_m` définit l'épaisseur thermique de cette face. Ce n'est
  pas la hauteur géométrique du proxy.

Les gaz, réactions, solides et résidus portent des identifiants distincts par
matériau (`IGNIS_FUEL_pmma`, `IGNIS_SOLID_cellulose`, etc.). Les paramètres
proviennent de la bibliothèque versionnée existante et gardent ses limites :
PMMA de démonstration et substitut générique de cellulose/bois sec, sans
équivalence à un câble, une batterie ou un matériau de vol.

Les faces supérieures combustibles restent réactives pour toutes les familles.
Le petit rectangle d'un brûleur ou émetteur prescrit remplace cependant la
couche réactive à cet endroit. Le reste de cette face et les autres combustibles
continuent à subir la pyrolyse calculée. Les côtés et le dessous restent les
parois inertes décrites dans le deck ; cette version ne simule donc pas une
propagation tridimensionnelle détaillée dans toute l'épaisseur d'un équipement.

## Les cinq familles

| `incident_type` | Condition appliquée sur le rectangle | Interprétation |
| --- | --- | --- |
| `overheating` | `EXTERNAL_FLUX` sur la couche thermique, `RAMP_EF` | Chauffage externe prescrit. La pyrolyse dépend du matériau ; aucune flamme de gaz n'est imposée. |
| `arc` | Même mécanisme, impulsion finie | Énergie thermique équivalente d'un défaut. Pas de plasma, circuit, projection de métal ni résolution de la durée réelle d'un arc. |
| `flaming` | `HRRPUA`, `SPEC_ID` du combustible émis et `RAMP_Q` | Foyer déjà allumé supposé. La puissance chimique nominale fixe le débit de combustible ; la HRR réellement obtenue reste calculée par FDS. |
| `smoldering` | `NET_HEAT_FLUX` avec `RAMP_Q`, `MASS_FLUX(SOOT)` avec `RAMP_MF` | Chaleur de frontière et suie prescrites indépendamment, sans combustible gazeux primaire ni flamme imposée. Ce n'est pas une cinétique de combustion couvante. |
| `battery` | Même émetteur thermique/suie, avec croissance puis palier | Profil hypothétique équivalent. Aucune électrochimie, réaction en chaîne entre cellules, explosion ou composition toxique des gaz. |

La famille `flaming` utilise le combustible annoté du composant. Sur un composant
inerte, elle utilise le substitut `material_id` de la configuration ; cette
hypothèse est enregistrée dans `emitted_fuel_material_id`. Le matériau de la
géométrie n'est pas modifié pour autant.

Le chauffage résistif existant peut définir la puissance des familles thermiques
avec `I²R × heat_fraction`, ou `V²/R × heat_fraction`, et une coupure. Cela reste
une source thermique équivalente, sans résolution du circuit. Les autres
familles refusent cette option afin de ne pas présenter une puissance de défaut
électrique comme une puissance chimique de flamme.

La suie des émetteurs est une espèce `SOOT` explicitement suivie. Le coefficient
de démonstration est **`1e-9 kg/J`** de chaleur de frontière prescrite. À 1 kW,
cela représente `1e-6 kg/s`. Il s'agit d'une hypothèse, sans mesure de couvant
ou de batterie. La source primaire ne consomme pas explicitement d'oxygène ;
seules les réactions secondaires des combustibles le font. La combustion
secondaire peut produire sa propre suie et sa propre HRR.

## Puissance, rampe et énergie

`ignition_power_w` est une puissance de pointe en watts ; les flux du deck
utilisent les kW/m² :

```text
flux_kw_m2 = ignition_power_w / 1000 / applied_area_m2
imposed_pulse_energy_j = ignition_power_w × intégrale de la rampe en secondes
```

Le manifest distingue `nominal_power_duration_j` de l'énergie intégrée réellement
demandée pendant la fenêtre simulée. Le sens énergétique dépend de la famille :

- chauffage/arc : flux externe incident avant absorptivité de surface ; ce n'est
  pas une garantie que toute l'énergie est absorbée par le solide ;
- foyer enflammé : énergie chimique nominale du combustible injecté ; le fichier
  HRR de FDS donne l'énergie chimique réellement libérée ;
- couvant/batterie : chaleur nette de frontière radiative et convective. Ce
  budget n'inclut pas l'enthalpie transportée par la faible injection de suie.

Une impulsion démarre à pleine puissance à `t=0`, ou monte en au plus `0.01 s`
après un délai. Elle descend en au plus `0.01 s` à la fin. Par exemple, 1 kW
pendant 1 s sans délai impose **995 J**, après intégration de la descente, et
non exactement 1 000 J. L'interface peut proposer 1 s comme défaut pour `arc` ;
le compilateur respecte la durée effectivement fournie.

Le profil batterie monte linéairement pendant les premiers 25 % de la durée,
puis atteint un palier et une courte descente. À 1 kW pendant 10 s, sans délai,
l'énergie est **8 745 J**. Une simulation arrêtée à 1 s ne compresse pas cette
croissance : elle ne reçoit que **200 J**. Si la source est désactivée, de durée
nulle ou démarre après la fin du calcul, l'énergie imposée est nulle.

La source occupe une cellule. Changer la résolution change sa surface et son
flux, même à puissance totale identique. Une étude de convergence doit examiner
cette dépendance avant toute interprétation quantitative d'une ignition.

## Mesures et usage pour l'apprentissage

Le contrat `surface_devices` est conservé : température de paroi (`T`), flux de
gaz combustible propre au matériau (`M`), épaisseur (`D`), flux thermique net
(`Q`). Le point est une cellule supérieure exposée. Pour une source thermique,
le point source est préféré ; pour un brûleur ou émetteur, le point évite le
rectangle prescrit. Sans cellule réactive disponible, aucun appareil de
pyrolyse factice n'est créé et un avertissement le signale.

Une mesure locale de pyrolyse n'est pas un état d'allumage de tout l'objet. La
HRR globale additionne source chimique éventuelle et réactions secondaires ;
elle ne démontre pas à elle seule qu'un objet voisin précis s'est enflammé.
L'absence de mesure ne signifie pas absence de danger.

Les données d'entraînement doivent identifier la version du compilateur, la
famille d'incident, la rampe, l'énergie, les paramètres du maillage, la position
appliquée, les matériaux et les empreintes de scène/configuration. Les modèles
entraînés sur l'ancien coupon fixe ne couvrent pas ces nouveaux incidents.
Les valeurs et profils synthétiques ne doivent pas être étiquetés observations
NASA, probabilités de panne ou propriétés expérimentales de batteries.

## Vérifications et références

Les tests du compilateur vérifient les deux sites sur un même objet, les faces
originales et discrétisées, les obstacles apparus après discrétisation, les
matériaux multiples, la présence des surfaces réactives voisines, les cinq
conditions de source, les unités, les intégrales, la mesure de pyrolyse et la
compatibilité des archives. Ils ne remplacent pas l'exécution réelle de FDS.

Les vérifications d'exécution doivent notamment examiner les fichiers HRR et
débits de matière, les températures, la suie indépendante pour les émetteurs et
les flux par matériau. Un foyer nominal de 1 kW n'est pas une assertion de
1 kW effectivement libéré : mélange, disponibilité en oxygène et extinction
numérique interviennent. Aucun réglage d'extinction ne doit être désactivé pour
faire simplement passer un seuil de test.

Références de syntaxe : [manuels officiels FDS](https://pages.nist.gov/fds-smv/manuals.html),
sections « Specified Heat Release Rate », « Species Boundary Conditions »,
« Time-Dependent Functions » et « Alternative Method of Specifying Smoke » ;
validation des combinaisons de flux et espèces dans
[`read.f90` de FDS 6.11.1](https://github.com/firemodels/fds/blob/FDS-6.11.1/Source/read.f90).
Les références des paramètres PMMA et cellulose restent dans
`backend/ignis/physics/materials.py` et `manifest.materials`.
