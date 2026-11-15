# Revue indépendante du POC chaleur — 14 novembre 2026

**Avis : démonstration ML exploitable et amélioration mesurée face à une règle de proximité, mais performance insuffisante pour un moteur généraliste de risque incendie.** Le gain en microgravité porte surtout sur la précision ; le modèle manque davantage de points chauds que la proximité. Les fausses alertes par scénario restent fréquentes. Aucun défaut bloquant d'export identifié après les corrections relues.

Revue locale de code, rapports et JSON existants uniquement : aucun entraînement, inférence, accès Windows ou nouveau FDS réalisé par le relecteur. La vérification indépendante des 200 replays a été exécutée par l'agent principal ; son rapport est lu et identifié ci-dessous.

## Sélection et cohérence des preuves

`selection.json` conserve **FIT1**, checkpoint 4 000 parmi 16 000 mises à jour, seuil commun **0,9478464126586914**. Sa moyenne des F1 microgravité/Terre sur validation est **0,324985**, contre **0,318139** pour FIT2. Le choix déclaré utilise la validation ; aucune sélection sur le test historique n'est revendiquée. Les poids et le seuil FIT1 sont gelés dans `fit1/frozen-selection.json` avant son évaluation historique.

Le modèle, les empreintes, les seuils, les métriques, les baselines, les cas et les exemples de `web/public/poc/hotspots.json` correspondent exactement à `fit1/report.json`. L'empreinte d'état correspond au candidat retenu. Le corpus contient **120/40/40 cas**, **60/20/20 dispositions**, avec les deux gravités d'une disposition dans la même partition et des familles structurelles distinctes. Le vérificateur confirme 200 cas, 100 dispositions, les comptes numériques et les masques affichés sur les mêmes coordonnées/instants.

FIT1 rapporte **191,766 s** de boucle d'apprentissage incluant ses validations et **266,703 s** de traitement total, sur RTX 4070 Ti, avec rechargement exact des poids. `checks.json` rapporte 14 tests pour FIT1, 17 pour FIT2 et un échantillon court de GPU à 98 % pendant FIT2 ; cette mesure n'est pas une moyenne sur toute la campagne. FIT1 est la recette BCE équilibrée, sans les réflexions/Dice de la correction FIT2.

## ML face à la proximité de la source

Référence : score `exp(-distance au patch source / 1 m)`, constant dans le temps ; seuil choisi sur validation selon le même objectif, rayon équivalent **0,220417 m**. Cible : température FDS ≥ ambiante + 5 °C, uniquement aux sondes disponibles et après t=0. Chaque cellule ci-dessous donne **ML / proximité**, en pourcentage ; les comptes complets sont conservés dans le rapport.

| Partition et gravité | Précision | Rappel | IoU | F1 |
| --- | ---: | ---: | ---: | ---: |
| Validation, microgravité | 39,61 / 29,70 | 39,61 / 51,58 | 24,69 / 23,22 | 39,61 / 37,69 |
| Validation, Terre | 20,07 / 2,50 | 34,55 / 1,44 | 14,54 / 0,92 | 25,39 / 1,82 |
| Test historique, microgravité | 52,30 / 32,52 | 47,12 / 53,04 | 32,96 / 25,25 | 49,58 / 40,32 |
| Test historique, Terre | 52,36 / 2,00 | 8,78 / 0,44 | 8,13 / 0,36 | 15,04 / 0,72 |

L'IoU microgravité progresse de **1,47 point** en validation et **7,71 points** sur le test historique, mais son rappel baisse respectivement de **11,97** et **5,91 points**. Le rappel terrestre historique de **8,78 %** interdit une conclusion de détection fiable. La référence tout froid ne détecte aucun des 3 058 dépassements validation ni des 5 421 dépassements historiques. La moyenne F1 des deux gravités passe de **70,14 % sur train** à **32,50 % en validation** : l'écart reste important. Ces observations corrélées ne sont pas autant d'essais indépendants.

## Contrôles froids et échecs consultables

| Partition | Cas sans dépassement mesuré | Avec au moins une fausse alerte ML | Proximité |
| --- | ---: | ---: | ---: |
| Train | 52 | 0 | 36 |
| Validation | 18 | 7 (38,89 %) | 14 |
| Test historique | 22 | 8 (36,36 %) | 16 |

En microgravité seule : **4/9** contrôles validation et **4/10** historiques ont une fausse alerte ML. Un faible taux de faux positifs par point/instant ne démontre donc pas un contrôle fiable des alertes par scénario. Le ML manque entièrement **4/22** cas chauds validation et **1/18** cas chauds historiques ; en microgravité, **1/11** et **0/10** respectivement.

Les raccourcis de démonstration respectent la règle déclarée : médiane inférieure d'IoU microgravité validation, pire cas du même groupe, premier contrôle froid. Le cas représentatif `procedural-0071-electrical-01-flaming-microg-c1` a une IoU de **32,50 %** et détecte son pic échantillonné de **234,73 °C**. Le cas d'échec `procedural-0094-electrical-03-battery-microg-c1` ne détecte aucun de ses 26 dépassements ; son pic de **48,14 °C** reçoit un score de **0,92037**, inférieur au seuil. Le contrôle proposé n'a aucune fausse alerte ; il ne représente pas tous les contrôles froids.

## Limites de la conclusion

Le résultat prédit une **classe de chaleur conditionnée à une source déjà imposée**, sans température ML, fumée, probabilité de départ ou classement de tous les composants d'un habitat. Les 200 scénarios, l'horizon de 30 s et la grille 12 × 16 × 8 n'établissent pas une généralisation à des géométries ou matériaux arbitraires. Aucun cas d'arc du corpus ne présente de dépassement mesuré : la capacité à détecter un arc chaud n'est pas évaluée. Le test historique a déjà été consulté auparavant ; la validation a servi aux choix répétés. Aucune validation expérimentale NASA ni garantie de sécurité n'est obtenue.

La démonstration permet de montrer un apprentissage spatial, ses erreurs et une comparaison reproductible au simulateur. Elle ne permet pas d'annoncer une prédiction générale de l'incendie ou une détection complète des zones sensibles.

## Empreintes relues (SHA-256)

| Artefact | Empreinte |
| --- | --- |
| `fit1/report.json` | `84366fd6a071b96531a338b3d100989bfb47136bac2cb16a1644ff36ed67d39c` |
| `fit1/frozen-selection.json` | `f486b381b1e2201dfda2aefeea65e9d3f60cbefceb294b9ce7085a1cba5278cb` |
| `selection.json` | `8757d66724c724d6da3b756113da641276c424dae0c212cc7590f45ef186fae9` |
| `checks.json` | `c2cac53a34758031e86d4f8050373b989da1f8f3487a8a57f8abece97ad1c080` |
| `web/public/poc/hotspots.json` | `e671ca2bf68f617d1928507bd8b6522a9b574f530a9298fa2f882641526305f8` |
| `export-verification.json` | `2c905f3c6778cec4b59d3d173b255da9579b3b8742d1d77b78da8d25a5787b18` |

Identité retenue : `hotspot-poc-20261114`. État des poids : `a7e47b7a18f7ea45f29a115c935c955d13f8fdf7cd4db526643e93e5055e487b` ; fichier de poids déclaré dans le rapport : `fe4f781dd50f66d27400f87beef91a2ce7c666c3319b143d5cb42c5f577ead60`. Aucun contrôle indépendant du fichier de poids n'est ajouté par cette revue documentaire.
