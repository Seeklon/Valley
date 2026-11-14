# Modèles de prévention — protocole et évaluation

Exécution du 14 novembre 2026 sur le PC Windows, sans Ollama. Codex explique les
résultats ; les estimations numériques proviennent des modèles décrits ici.
Les modèles de transport FDS existants restent documentés dans [MODELS](MODELS.md).

## Délai d'allumage expérimental

`ignition-delay-guo-v1` apprend le délai depuis la mise sous courant constant
d'un fil NiCr/LDPE dans Guo et al., *Fire Safety Journal* 141 (2023), 103925,
[manuscrit](https://hdl.handle.net/2115/95853). Ce n'est pas une étude NASA.

Les 26 marqueurs colorés de la figure 5 sont extraits des vecteurs du PDF ;
marqueurs noirs simulés exclus. Figure et deux ancres textuelles vérifiées.
Le PDF original, son empreinte, les coordonnées, une enveloppe de lecture
graphique et les partitions sont dans `data/prevention/ignition/`.
L'enveloppe de lecture de 5 % n'est pas un intervalle expérimental de confiance.
Ces points ne sont pas 26 essais bruts dont l'indépendance serait établie.

Partition fixée avant ajustement :

| Partition | Courants (A) | Points |
|---|---|---:|
| Entraînement | 3,5 ; 4 ; 5 ; 6 ; 6,5 ; 8 ; 10 ; 18 | 12 |
| Validation | 5,5 ; 9 ; 13 | 5 |
| Test | 4,5 ; 7 ; 7,5 ; 11 ; 15 | 9 |

Toutes les installations à un même courant restent dans la même partition.
Une régression Ridge sur log(courant)/log(délai) compare les degrés 1–3 ;
sélection par erreur logarithmique de validation et monotonie sur le domaine
d'entraînement. Le degré 1 a été retenu. Aucun réajustement sur toutes les données.
La référence `coefficient / courant²` est ajustée sur l'entraînement uniquement.

| Test, pondération égale par courant | Régression | Référence I⁻² |
|---|---:|---:|
| Erreur absolue moyenne | 0,1573 s | 0,3307 s |
| Erreur relative moyenne | 5,11 % | voir métadonnées |
| Erreur absolue maximale | 0,3348 s | voir métadonnées |

Avec un horizon illustratif d'une seconde, les neuf dates estimées produisent
une alerte avant l'allumage publié ; avance minimale 0,665 s. Cela n'établit
aucun taux de détection opérationnel. Aucun cas sans allumage ni dénominateur
de fonctionnement normal n'est disponible : fausses alertes/heure, probabilité
calibrée et intervalle prédictif restent `null`.

Domaine : fil de 70 mm, rayon NiCr 0,25 mm, épaisseur LDPE 0,15 mm,
3,5–18 A constants et maintenus, gaz initialement calme. Les trois installations
de microgravité sont regroupées (10⁻⁵–0,03 g) ; le modèle n'apprend pas un effet
causal de la gravité. Le contexte nominal 20 °C, 21 % O₂ et 101 325 Pa vient
du modèle numérique associé de l'article ; les journaux atmosphériques de chaque
essai ne sont pas disponibles. Air forcé, coupure, autre matériau, 1 g ou
atmosphère différente refusent le délai. Un délai au-delà de l'horizon n'est
pas une indication de faible risque.

## Température future apprise

`thermal-history-forest-v1` est une régression Extra Trees de température
d'isolant, entraînée sur le [modèle électrothermique local](PREIGNITION_PHYSICS.md).
96 familles × deux gravités × courant maintenu/coupure donnent 384 trajectoires.
La graine est 20261114, deux processus CPU ; génération mesurée : environ 17 s.
Le matériel 12 Go VRAM/16 Go RAM suffit ; ce modèle tabulaire n'exige pas de GPU.

Courants de scénario 0–20 A, air prescrit 0–0,5 m/s, ambiance 0–50 °C,
10⁻⁴ g ou 1 g, pression 101 325 Pa ; géométrie et matériau fixés. Historique
jusqu'à 0,1–10 s, horizon 0,1–20 s. Pression, temps ou gravité hors domaine
sont refusés. L'oxygène reste un contexte, sans chimie gazeuse dans ce modèle.

Les entrées sont le temps écoulé, la dernière température et deux retards,
le courant présent, la commande future déclarée, le temps d'alimentation prévu,
l'horizon, l'air, la gravité et l'ambiance. Aucun état caché du conducteur,
température future, date d'arrêt de simulation ou label d'événement ne devient
une entrée. Une coupure programmée est une commande connue, distincte d'une
coupure révélée a posteriori.

| Partition | Familles | Trajectoires | Fenêtres disponibles / demandées |
|---|---:|---:|---:|
| Entraînement | 65 | 260 | 7 469 / 14 560 |
| Validation | 15 | 60 | 1 479 / 3 360 |
| Test | 16 | 64 | 1 940 / 3 584 |

La physique s'arrête notamment à 1 % de perte de masse, limite de géométrie
fixe. Les cibles ultérieures sont absentes. Une trajectoire terminée sans
pyrolyse n'est pas un exemple d'absence de feu. Les scores sont conditionnels
aux fenêtres disponibles (54,1 % des fenêtres test demandées), pas à toute la
durée envisagée. La couverture affichée est limitée par la projection physique,
elle n'est pas prédite par le ML.

96 arbres, profondeur maximale 20, taille minimale de feuille sélectionnée
parmi 1/3/8 sur validation seule. Pondération égale par famille ; pas de refit.

| Erreur sur test | ML | Dernière température | Extrapolation linéaire |
|---|---:|---:|---:|
| MAE | 10,05 °C | 89,94 °C | 190,01 °C |
| RMSE | 18,15 °C | 142,69 °C | 1 057,58 °C |
| Maximum absolu | 129,30 °C | 468,54 °C | 15 704,85 °C |

Ce test porte sur 16 familles réservées de simulations propres, sans bruit,
retard ni panne de capteur. Il n'évalue ni une nouvelle géométrie, ni un nouveau
matériau, ni le transfert à des capteurs réels. `ignition_supported=false`.

## Reproduction et conservation

Code : `tools/nasa/extract_guo_ignition.py`, `tools/remote/train_ignition.py`,
`tools/remote/train_thermal.py`. Extraction PDF : PyMuPDF uniquement pour cet
outil d'archivage ; pas de dépendance de l'application.

Sur Windows :

```powershell
$env:PYTHONPATH='E:/IGNIS-Valley/app/backend'
$env:OMP_NUM_THREADS='2'
$env:OPENBLAS_NUM_THREADS='2'
Set-Location E:/IGNIS-Valley/app
# Un nouveau répertoire/version est nécessaire pour refaire une campagne.
& E:/IGNIS-Valley/.venv/Scripts/python.exe tools/remote/train_thermal.py --benchmark
```

Les deux premiers entraînements sont conservés, sans réouverture des tests pour
choisir une amélioration. Les scripts refusent l'écrasement d'un modèle ou d'une
campagne existante. Une future version exige de nouvelles familles d'évaluation.
Les garde-fous d'archivage ajoutés après entraînement ne changent ni poids ni
scores ; les empreintes du code effectivement utilisé sont conservées.

Localisateurs Windows : `runtime/prevention/models/` (poids et métadonnées),
`runtime/prevention/datasets/thermal-families-v1/` (plan, Parquet, journaux),
`runtime/prevention/analyses/` (analyses et preuves figées). Copies légères des
métadonnées dans `evidence/prevention/`. Les artefacts locaux sont vérifiés par
SHA-256 au chargement ; aucun pickle utilisateur n'est accepté.
