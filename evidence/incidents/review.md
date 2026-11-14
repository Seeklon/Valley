# Revue indépendante — incidents localisés

14 novembre 2026. Relecteur distinct des auteurs backend/ML, sur les fichiers
`api.py`, `engine.py`, `schema.py`, `incidents.py`, `ml/incidents.py` et le pilote.

Trois constats reproduits et corrigés :

1. Une trame entièrement absente après l'état froid initial laissait zéro
   équipement exposé. La couverture inconnue produit désormais `null` ; test de
   régression `test_missing_later_frame_cannot_make_initially_cold_equipment_safe`.
2. Le worker exportait la requête avec les champs `None`, alors que le compilateur
   utilisait `physical_config()`. L'export conserve maintenant la configuration
   réellement compilée, notamment pour la vérification des empreintes.
3. Le résultat ML omettait `provenance.incident`, donc le marqueur utilisait la
   position annotée au lieu de la position discrétisée. Le manifeste est maintenant
   transmis au rendu avec la source réellement appliquée.

Les correctifs ont été relus. 37 tests workflow/ML réussis au moment de la revue.
Prévalidation indépendante : 60/60 scénarios compilables et compatibles avec
les features ML ; 12 géométries physiques distinctes, aucune fuite entre les
partitions. Aucun autre blocage confirmé. Cette revue de code ne constitue pas
une validation expérimentale du simulateur ou de son émulateur ML.
