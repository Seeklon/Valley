# Preuves de livraison

Ces fichiers consignent les mesures et vérifications réalisées le 14 novembre
2026. Les simulations, l’entraînement, l’inférence et Blender ont été exécutés
sur Windows ; les contrôles légers et le navigateur de revue peuvent utiliser
le VPS. Les fichiers de preuve ne remplacent pas une nouvelle vérification de
disponibilité lors d’une utilisation ultérieure.

| Domaine | Preuves | Portée |
|---|---|---|
| Application réelle | [application-verification.json](application-verification.json) | 15 contrôles : FDS Soyouz, 4 scènes × 2 modèles, exports, annulation, campagne Parquet et Codex. |
| Navigateur réel | [browser-verification.json](ui/browser-verification.json) | 8 contrôles : quatre GLB, inspection, observations NASA, réponse Codex, modèles et mobile ; aucune erreur JavaScript. |
| Prédictions dans l’interface | [prediction-verification.json](ui/prediction-verification.json) | 7 contrôles : deux prédictions réelles, chronologie, comparaison, export, domaine, restauration et mobile. |
| Tests Windows | [windows-final-tests.xml](windows-final-tests.xml) | 58 tests réussis, aucun échec ni test ignoré. |
| Processus et lancement | [windows-lifecycle-tests.xml](windows-lifecycle-tests.xml) | 7 tests ciblés Windows, comprenant concurrence et crash. |
| Contrelecture | [final-review.md](final-review.md) | Corrections de lifecycle et Codex ; limites explicites de la revue. |
| Blender | [blender-verification.json](blender-verification.json) | 4 paquets d’assets contrôlés, export/import annoté Soyouz. |
| Physique | [physics-verification.json](physics-verification.json) | Cas FDS ; contrôles et limites détaillés dans le guide physique. |
| Dataset | [pilot-v2-manifest.json](pilot-v2-manifest.json) | 96 calculs et partitions, configurations et empreintes. |
| Modèles | [model-audit.json](model-audit.json), [model-metrics.json](model-metrics.json) | Évaluation indépendante de l’entraînement, sans changement des poids. |
| Identité physique | [model-scene-identity.json](model-scene-identity.json) | 96 fichiers FDS et échantillonnages identiques après normalisation numérique. |
| Métadonnées | [model-audit-metadata.json](model-audit-metadata.json) | Empreintes des métadonnées finales et poids inchangés. |
| NASA | [nasa-fan-calibration.json](nasa-fan-calibration.json) | Calibration d’instrumentation uniquement ; pas de validation de combustion. |
| Codex | [codex-verification.json](codex-verification.json) | Réponse réelle avec citations conformes au contrat final ; contrôle syntaxique. |
| Sauvegarde | [archive-verification.json](archive-verification.json) | Dataset et modèles sur G:, 1 351 fichiers relus avec SHA-256. |

Les comparaisons modèle/FDS utilisent des scénarios réservés au test. Elles ne
constituent pas une comparaison avec des mesures NASA. Les données brutes et les
poids restent sur le PC Windows, dans leurs dossiers et archive documentés.

Les captures conservées dans `ui/` proviennent de ces parcours réels. La dernière
correction du sous-titre des modèles, « domaine d’utilisation déclaré », ne
modifie ni les données ni le comportement ; les captures Modèles finales
reflètent ce libellé.
