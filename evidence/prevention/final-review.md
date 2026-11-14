# Contrelecture finale — prévention avant allumage

14 novembre 2026. Relecture de livraison du code, de la documentation et des
preuves archivées. Aucun entraînement, accès Windows, changement Git ni
publication effectué pendant cette contrelecture. Seul ce rapport a été écrit.

**Avis : aucun écart bloquant identifié dans le périmètre examiné après les
correctifs ci-dessous.** La tranche livrée répond au parcours de recherche
annoncé : conclusions NASA résumées et classées, interprétation sourcée, délai
conditionnel issu d'une étude complémentaire, et températures simulées/prédites
distinguées. Cet avis ne constitue pas une validation physique indépendante,
une qualification du câblage d'un véhicule ou une estimation du risque de mission.

## Correctifs relus

| Point signalé | État vérifié |
|---|---|
| Preuves d'un export recalculées depuis un catalogue susceptible de changer | Corrigé : `service.py` conserve `evidence_snapshot` et `evidence_snapshots_by_component`, avec leurs SHA-256 ; `routes.py` exporte l'instantané enregistré dans `evidence_findings.json`. |
| Motifs du fil par défaut réutilisés pour expliquer un autre composant | Corrigé : l'interprétation lit maintenant l'instantané du composant demandé. Le test `test_codex_uses_frozen_applicability_of_the_selected_component` contrôle le contexte envoyé à Codex pour la batterie non caractérisée. Il figure dans le rapport Windows final. |
| PDF Guo archivé remplaçable par une autre version | Corrigé : l'outil vérifie le SHA-256 connu du manuscrit avant extraction et refuse une archive existante différente. La notice « manuscrit inchangé » reste liée aux octets vérifiés. |
| Gravité terrestre non reconnue, atmosphère et débit sans effet sur le tri | Corrigé : les régimes terrestre/microgravité sont distingués ; débit, oxygène et pression contribuent au classement et aux motifs. Les informations absentes restent signalées comme inconnues. |

Localisateurs : [service.py](../../backend/ignis/preignition/service.py),
[routes.py](../../backend/ignis/preignition/routes.py),
[evidence.py](../../backend/ignis/preignition/evidence.py),
[extract_guo_ignition.py](../../tools/nasa/extract_guo_ignition.py),
[test_prevention.py](../../tests/test_prevention.py).

Les trois analyses conservées dans le rapport navigateur contiennent chacune
22 conclusions NASA et une conclusion complémentaire explicitement non NASA.
Le recalcul local des empreintes des instantanés communs et par composant
correspond aux six empreintes archivées. Aucune probabilité d'allumage numérique
n'apparaît dans les composants de ces analyses : les valeurs restent `null`.

## Documentation confrontée aux résultats

[PREVENTION_MODELS.md](../../docs/PREVENTION_MODELS.md) et
[PREIGNITION.md](../../docs/PREIGNITION.md) concordent avec les métadonnées
d'entraînement et les comptes ci-dessous.

| Élément | Résultat vérifié | Portée conservée dans les textes |
|---|---|---|
| Corpus NASA | 13 sources, 22 conclusions, 3 journaux et 49 relevés clairsemés | Les journaux historiques ne deviennent pas des labels d'entraînement ou de validation des nouveaux modèles. |
| Guo, figure 5 | 26 marqueurs expérimentaux ; 12 entraînement, 5 validation, 9 test ; tous les points d'un courant dans la même partition | Les points ne sont pas présentés comme 26 essais bruts indépendants ; la source est distincte de NASA. |
| Délai Guo, test | 9 points / 5 courants ; MAE pondérée par courant 0,157309 s ; erreur relative moyenne 5,1073 % ; maximum 0,334769 s | Évaluation réservée au sein de la même publication, sans nouvelle étude indépendante. La référence I⁻² atteint 0,330693 s de MAE. |
| Alerte illustrative Guo | Horizon de 1 s ; 9 dates d'alerte avant les événements publiés ; avance minimale 0,665231 s | Aucun taux opérationnel de détection ni de fausses alertes : seuls des cas publiés ayant allumé sont disponibles. |
| Campagne thermique | 96 familles, 384 trajectoires ; 65/15/16 familles et 260/60/64 trajectoires selon entraînement/validation/test | Températures synthétiques d'un matériau et d'une géométrie fixes, sans label d'allumage. |
| Couverture thermique test | 1 940 fenêtres disponibles sur 3 584 demandées, soit 54,129 % | Les scores portent sur les fenêtres où la physique fournit encore une cible ; les arrêts ne deviennent pas des exemples « sans feu ». |
| Température apprise, test | MAE 10,052186 °C ; RMSE 18,151219 °C ; maximum 129,301913 °C | Évaluation sur 16 familles simulées réservées, sans bruit, retard, panne de capteur ou validation sur capteurs réels. |

Le choix du degré 1 pour le délai et de la taille minimale de feuille 1 pour
Extra Trees correspond aux candidats et aux métriques de validation archivés.
Les textes ne présentent pas ces choix comme un réglage sur le test. Les
références, la pondération par groupe/famille et l'absence de réajustement global
sont cohérentes avec les scripts et métadonnées.

Le SHA-256 du dataset Guo courant correspond à celui du modèle entraîné ; les
paramètres sauvegardés correspondent à leur empreinte. Les métadonnées du
dataset thermique incluses dans le modèle sont identiques à
[thermal-dataset.json](thermal-dataset.json). Les fichiers `thermal.py` et
`materials.py` correspondent toujours aux empreintes du code ayant produit la
campagne. Les modifications ultérieures de garde-fous et d'interface ne sont
pas présentées comme de nouveaux entraînements ou de nouveaux scores.

Sources des chiffres :
[métadonnées du délai](models/ignition-delay-guo-v1/metadata.json),
[paramètres du délai](models/ignition-delay-guo-v1/parameters.json),
[métadonnées de température](models/thermal-history-forest-v1/metadata.json).

## Résumer, classer et interpréter les conclusions NASA

- **Résumer :** les cartes affichent la conclusion, son statut, les conditions,
  limites de transfert et un lien/localisateur de source. Les incohérences PFPI
  et Kerlix restent exposées dans le corpus ; elles ne produisent pas de labels
  numériques réparés arbitrairement.
- **Classer :** les motifs rendent visibles les compatibilités et les inconnues.
  Le classement documentaire est séparé des couleurs et délais des composants.
  La catégorie de preuve n'est pas annoncée comme une probabilité. Les groupes
  documentaires rappellent que les reprises ne constituent pas des réplications.
- **Interpréter :** le texte reçoit les résultats, limites et faits figés du
  composant. Il distingue NASA, Guo et thermique simulée. Le repli extractif est
  conservé si Codex manque ou ne respecte pas le contrat de citation. Le contrôle
  des citations reste syntaxique : il ne prouve pas que chaque affirmation
  générée est scientifiquement impliquée par la source.

La conclusion `GUO-2023` est étiquetée « hors NASA » et ajoutée après les
conclusions NASA. Le nom générique `evidence_findings.json` évite d'attribuer
cette étude complémentaire à NASA dans l'export.

## Vérifications de livraison disponibles

| Preuve relue | Résultat archivé |
|---|---|
| [windows-tests.xml](windows-tests.xml), 14 novembre à 13:53:45 +01:00 | 131 tests, 0 échec, 0 erreur, 0 ignoré ; inclut le test du contexte Codex par composant. |
| [local-tests.xml](local-tests.xml), exécution antérieure | 130 cas, 123 réussis et 7 ignorés pour les fonctions propres à Windows ; aucun échec ni erreur. Ce rapport précède l'ajout du dernier test. |
| [application-verification.json](application-verification.json) | 9 contrôles réussis : partitions/empreintes, poids et métriques sauvegardées, inférence, domaines distincts, coupure, absence d'effet géométrique inventé et export. |
| [parcours navigateur](ui/prevention-verification.json) | 12 contrôles réussis, aucune erreur de page ; modèle Codex déclaré `gpt-6.1-sol`, méthode réelle `codex_grounded_in_prevention_evidence`, comparaison, téléchargement ZIP, batterie inconnue et limites de domaine. |

Les captures référencées par le parcours navigateur sont présentes. La
[capture d'analyse](ui/ignis-prevention-analysis.png) a été examinée : l'interface
montre la probabilité non quantifiée, l'incertitude non quantifiée, le caractère
hypothétique de la scène et les courbes séparées « historique simulé »,
« projection physique » et « prévision ML ». L'instant estimé au-delà de
l'horizon n'est pas présenté comme une absence de danger.

Cette contrelecture a inspecté les rapports existants et recalculé les petites
vérifications d'intégrité ci-dessus. Elle n'a pas répété la campagne Windows,
les entraînements ni le parcours navigateur.

## Limites scientifiques à conserver lors de la présentation

Le modèle de délai apprend seulement la relation courant/délai des cas
expérimentaux publiés ayant allumé. Il n'apprend pas un effet de gravité, de
ventilation, de matériau ou de position dans la cabine. Le contexte atmosphérique
nominal vient du modèle numérique associé à l'article, faute de journaux
atmosphériques par essai. Un cas hors protocole ne reçoit pas de délai.

Le modèle thermique local et sa régression de température ne produisent ni
allumage gazeux ni extinction. La pyrolyse, la fusion, l'arrêt de validité
géométrique et une coupure électrique restent distincts d'un événement de feu.
Leur qualité numérique et les scores sur simulations ne valident pas les
températures de fils réels.

La probabilité calibrée, les fausses alertes par durée de fonctionnement, les
intervalles prédictifs validés, le couplage à un champ de cabine réel et la
qualification d'un véhicule restent absents. Les documents les placent dans
les limites ou la feuille de route, sans les revendiquer dans la tranche livrée.
