# Sources NASA avant allumage

Revue du 14 novembre 2026. Le [catalogue](../data/prevention/evidence/catalog.json)
contient **13 sources, 22 conclusions et 3 journaux expérimentaux sélectionnés,
soit 49 lignes clairsemées**. Il apporte des preuves sur la surchauffe, les fumées,
les pilotes d'allumage et les limites de transfert. Il ne fournit pas un jeu
supervisé prêt à entraîner ou à valider un modèle d'auto-inflammation résistive
de câble en cabine.

Les annotations éditables sont dans
[curated.json](../data/prevention/evidence/curated.json). Les documents publics,
métadonnées, textes et empreintes sont sous
[raw/](../data/prevention/evidence/raw/). Les pages dont les valeurs ou l'OCR
demandaient une vérification visuelle sont conservées sous
[views/](../data/prevention/evidence/views/). Les inventaires déjà présents dans
`data/sources/` n'ont pas été modifiés pour cette recherche.

## Ce qui peut être utilisé

Le moteur documentaire peut classer des conclusions selon le mécanisme,
l'isolant exact, l'atmosphère, la gravité et le protocole du composant étudié.
Les signatures d'aérosols SAME peuvent alimenter une étude de détection dans un
domaine compatible. Les journaux de 1965 permettent de présenter des observations
historiques traçables, avec leurs cellules absentes et leurs événements réels.

Aucun de ces usages ne démontre une probabilité de départ de feu en mission.
Les fréquences de défaut, les expositions opérationnelles et un jeu moderne
apparié courant/température/événement/témoins manquent. Les trois journaux restent
explicitement exclus de l'entraînement, de la validation du modèle d'allumage et
de la validation thermique. Le jeu complémentaire Guo 2023 est hors NASA : sa
provenance, son domaine NiCr/LDPE et ses résultats doivent rester séparés de ce
catalogue.

## Sources et observables

Les pages PDF indiquées ci-dessous sont les pages physiques, comptées à partir
de 1. La pagination imprimée est également conservée dans les annotations.

| Source publique | Localisateur principal | Résultat exploitable et limite |
|---|---|---|
| [NTRS 19660008736 — câblage, volume I](https://ntrs.nasa.gov/citations/19660008736) | PDF 28, 30–33 | Protocole II-B : paliers de courant, oxygène humide à 5 psia, fil vertical, éclateur intermittent ; température déduite de résistance. Fraction finale d'O₂ et vitesse non chiffrées. |
| [NTRS 19660008892 — câblage, volume II](https://ntrs.nasa.gov/citations/19660008892) | PDF 84, 111, 122, 124 | Trois journaux transcrits ; températures généralement sous-estimées selon les auteurs. Un épisode de flamme autoextinguible, deux fins sans allumage observé. |
| [NTRS 19940024209 — isolants en faible gravité](https://ntrs.nasa.gov/citations/19940024209) | PDF 4, 14, 16, 18 | WIF allumé par fil chaud externe ; quelques flammes Kapton/Tefzel dans des essais autochauffés en microgravité. Pas de trajectoires ni de dénominateur utilisable comme probabilité. |
| [NTRS 19950026252 — PFPI](https://ntrs.nasa.gov/citations/19950026252) | PDF 3–4 | À 60 A, temps moyens de **fusion électrique** de 24,8 et 14,4 s, six spécimens par groupe. Le paragraphe de fumée présente une incohérence secondes/ampères ; aucun label reconstruit. |
| [NTRS 20130000422 — SAME-2](https://ntrs.nasa.gov/citations/20130000422) | PDF 7, tableau 1 ; PDF 12 | 40 cellules de diamètres/moments d'aérosols pour cinq matériaux, avant/après vieillissement. Les 720 s mesurent le vieillissement de la fumée, pas un délai d'allumage. |
| [NTRS 20160000940 — morphologie des fumées](https://ntrs.nasa.gov/citations/20160000940) | PDF original 16, 21 | Morphologie Kapton à des consignes de 540 et 640 °C ; ces consignes ne sont pas des seuils d'allumage. Citation secondaire PFPI contradictoire conservée et exclue des labels. |
| [NTRS 20210022143 — détection précoce](https://ntrs.nasa.gov/citations/20210022143) | PDF 2 | Besoin de couvrir la surchauffe avant flamme ; synthèse des non-détections SAME. Aucun nouvel essai indépendant ni taux d'allumage. |
| [NTRS 20240006315 — article wire-break](https://ntrs.nasa.gov/citations/20240006315) | PDF 5–9, 11–12 | Préchauffage puis arc à rupture, à 23,5 ± 1 psia et > 99 % O₂. Les courants dépendent du montage ; aucune série de délais individuels extraite. |
| [NTRS 20240008688 — présentation wire-break](https://ntrs.nasa.gov/citations/20240008688) | PDF 6, 19 | Version du même travail avec une ligne Kerlix différente. Ne constitue pas une réplication. |
| [NTRS 20240014551 — nouvelle méthode](https://ntrs.nasa.gov/citations/20240014551) | PDF 1 | Résumé d'une page annonçant une méthode sous arc piloté ; aucune mesure, trajectoire ou témoin chiffré. |
| [NTRS 20210011385 — rapport BASS-II](https://ntrs.nasa.gov/citations/20210011385) | Texte officiel, lignes 3656–3660 | Tentatives manuelles d'allumage externe de PMMA jusqu'à 230 s avec flamme et jusqu'à 500 s sans flamme entretenue. Bornes narratives, pas délais depuis un défaut électrique. |
| [PSI-25 — BASS-II](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25) | Métadonnées `/experimentalTable/0` et CSV existant | Conditions et inventaires ; existence de vidéos de tentatives d'allumage. Leur contenu et les fichiers supplémentaires ne sont pas tous examinés. |
| [PSI-26 — BASS](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26) | Métadonnées `/experimentalTable/0` et CSV existant | Inventaire de combustion solide ; aucun jeu apparié avant allumage établi par les seules tables inspectées. |

Les 827 et 236 objets de fichiers repérés dans les métadonnées PSI incluent
l'historique : ce ne sont ni des nombres d'essais, ni des décomptes certifiés de
fichiers actuels uniques. Des noms de fichiers README et de matrices ont été
repérés ; leur contenu n'a pas été obtenu ni utilisé. L'absence de labels est
donc une conclusion sur les tables examinées, jamais sur tout le dépôt PSI.

## Journaux de 1965 et censure

| Identifiant | Lignes | Observation de flamme | Fin d'observation |
|---|---:|---|---:|
| `NASA-1965-3-IIB-1` | 13 | Très petite flamme jaune autoextinguible à la ligne 21 min (1 260 s), sans précision temporelle chiffrée ; flamme entretenue non établie. | 1 380 s, ligne « Off » |
| `NASA-1965-6-IIB-3` | 18 | Aucun allumage sous décharge d'étincelle à la dernière ligne ; temps d'événement `null`. | 1 350 s, règle d'arrêt non précisée |
| `NASA-1965-9-IIB-2` | 18 | Aucune flamme malgré l'éclateur périodique ; temps d'événement `null`. | 1 155 s, coupure après destruction de l'isolant |

Les temps imprimés en minutes sont conservés avec leur conversion en secondes.
Aucune interpolation ni propagation de la dernière valeur connue n'est faite.
Les cellules blanches restent `null`. « Off » devient `current_status:
"power_off"` avec `current_a: null`, car ce n'est pas une mesure de 0 A. La valeur
`>800 °C` reste `temperature_c: 800, temperature_qualifier: "gt"`. Les
températures sont inférées de la résistance, avec biais bas signalé par les
auteurs et incertitude non chiffrée.

Les deux essais sans événement sont censurés à la fin documentée. Le dernier
peut présenter une censure informative liée à la destruction de l'isolant.
Aucune durée de surveillance après coupure n'est inventée. La présence de
l'éclateur empêche d'attribuer la petite flamme à une auto-inflammation sans
pilote. La sélection de trois exemples n'est ni aléatoire ni exhaustive.

## Contradictions et distinctions conservées

- **PFPI :** le résumé de 2016 cite 35 s à 10–15 A, alors que le primaire de
  1995 décrit 10 A puis +5 A toutes les 30 s et comporte lui-même une ambiguïté
  secondes/ampères. Les deux textes sont accessibles ; aucune correction
  supposée ne produit de label de fumée ou d'allumage.
- **Kerlix :** l'article indique 52 AWG/TBD pour une nouvelle série, la
  présentation 54 AWG/0,39 A. Les versions restent distinctes, sans moyenne ni
  seuil arbitrairement résolu.
- **Classement des isolants :** une résistance dans un montage terrestre et
  des flammes dans d'autres essais en microgravité n'établissent pas un effet
  causal de la seule gravité. Les formulations, chauffages et pilotes diffèrent.
- **Vieillissement SAME :** pour Teflon, le diamètre géométrique passe de
  0,081 à 0,070 µm tandis que d'autres moments augmentent. Une hausse universelle
  de tous les diamètres serait contraire au tableau.

La valeur 9,23 A pour Gore-Tex est un essai **sans allumage dans ses conditions**,
pas un seuil sûr. Les auteurs wire-break rejettent la puissance calculée par
tension d'alimentation × courant comme puissance utile du fil, en raison des
contacts et de l'alimentation à courant constant. De même, `I²t` a l'unité
A²·s ; il ne devient une énergie en joules qu'avec une résistance appropriée.

## Contrat du catalogue

`schema_version: 1` expose `sources[]`, `conclusions[]`, `experimental_records[]`,
`contradictions[]`, `data_gaps[]` et `ranking_contract`. La clé d'une source est
`source_id`. Chaque source relie notice officielle, artefacts, tailles et SHA-256,
nature des données, limites et sources apparentées. `curated.json` utilise un
objet `sources` indexé par identifiant ; l'outil produit la liste du catalogue.

Chaque conclusion possède un statut épistémique (`observation`,
`author_interpretation`, `protocol`, `data_gap`), une ancre de page/ligne/pointeur,
des conditions, quantités et unités, des incertitudes et les usages compatibles
ou invalides. Les catégories `primary_measured`, `primary_sparse`, `summary`,
`method_only`, `inventory` décrivent la preuve documentaire. Ce ne sont pas des
notes calibrées de fiabilité ni des probabilités de feu. La qualité de chaque
conclusion prime sur la catégorie générale du document : un rapport primaire
peut contenir une citation secondaire.

Le classement examine d'abord mécanisme, matériau, gravité, oxygène/pression,
chauffage et observable. Une condition inconnue reste inconnue. Il distingue
ensuite source primaire/secondaire, incertitudes, disponibilité des essais et
indépendance. `independence_group` regroupe notamment article/présentation
wire-break, protocole/résultats de 1965, reprises SAME et citation PFPI. Une
publication dérivée ne compte pas comme une nouvelle réplication. Un score
documentaire ne se convertit jamais en risque physique.

## Archives et reproduction

Le lot fait environ 17,3 Mio. Les PDF publics sont bornés à 15 000 000 octets par
téléchargement dans l'outil. Deux exceptions d'archivage sont explicites :

- Pour le rapport `NTRS-20160000940`, le PDF original de 7 122 986 octets a été
  téléchargé et examiné, puis son texte complet et un extrait vectoriel de
  530 020 octets ont été conservés pour limiter le lot. Les pages 1–6 de
  `selected-pages.pdf` correspondent aux pages originales **1, 5, 6, 16, 21,
  30**. URL, taille et SHA-256 du PDF original restent dans `remote_original_pdf`.
  Le manifeste décrit l'extraction avec PyMuPDF 1.23.7, sans rasterisation.
- Le PDF BASS-II `NTRS-20210011385` fait 48 972 416 octets et n'a pas été archivé.
  Le texte officiel NTRS est conservé avec son empreinte. Ses ancres sont des
  lignes de texte ; aucune pagination PDF vérifiée n'est revendiquée.

Depuis la racine du dépôt, sans accès réseau pour les vérifications :

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/nasa/preignition_sources.py --check
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -p no:cacheprovider tests/test_preignition_sources.py
.venv/bin/ruff check --no-cache tools/nasa/preignition_sources.py tests/test_preignition_sources.py
```

Après une modification revue de `curated.json`, exécuter l'outil sans `--check`
pour reconstruire `catalog.json`. Le mode par défaut reste hors ligne. Seul
`--archive-ntrs IDENTIFIANT` demande un nouveau téléchargement NASA public,
non brouillon et de taille bornée ; `pdftotext` est alors nécessaire. Un fichier
brut existant dont les octets diffèrent n'est jamais remplacé. Les documents
sont traités comme des données, sans exécution de macros ni d'instructions.

Les vérifications comparent les empreintes, les listes de sources, les ancres,
les conversions et les fenêtres d'observation ; elles refusent aussi une
promotion des journaux à l'entraînement ou à la validation. Elles protègent
l'intégrité de l'extraction, sans remplacer la relecture scientifique des
documents ni établir la validité d'un modèle prédictif.
