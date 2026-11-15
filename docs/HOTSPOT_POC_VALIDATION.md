# Validation minimale du POC visuel de zones chaudes

Protocole aligné le 14 novembre 2026 sur le contrat arrêté avant le premier fit, pour la démonstration du 15 novembre à 18 h Paris. Périmètre : un entraînement court sur les données existantes, comparaison visuelle et mesures honnêtes ; aucune nouvelle campagne FDS. Ce document ne lance aucun calcul et ne modifie aucun modèle. Le contrat d'export est détaillé dans `HOTSPOT_POC_MODEL.md`.

## Contrat du modèle

- Pour **un départ et des conditions donnés**, prédire un score spatial de chaleur à chaque instant observé. Vérité : `temperature_c >= ambient_temperature_c + 5`, sur les sondes gazeuses mesurées. L'ambiante vient de la configuration effective compilée, pas d'une constante 20 °C.
- Le score est un score de classification non calibré : ni température, ni probabilité réelle d'incendie ou de panne. Le champ `hotspot_score` reste distinct de `temperature_c`, qui contient uniquement la référence FDS. Les positions associées sont `sample_positions_m` ; les temps, scores, températures et masques conservent le même ordre des points. Un score faible ne prouve pas qu'une zone est sûre.
- Un classifieur chaleur seul ne prédit pas la fumée, l'intensité du pic, l'allumage des équipements ou la vitesse intérieure. Ces champs restent absents côté ML. Si la fumée FDS est affichée, sa provenance doit être distincte ; ne pas fabriquer de fumée nulle ou dérivée du score.
- Les coordonnées, dimensions et temps sont ceux du corpus : grille `12 × 16 × 8`, horizon jusqu'à 30 s. Interpoler le rendu n'ajoute pas de résolution physique. Les maxima globaux FDS et températures de paroi ne remplacent pas les cibles gazeuses.

## Données et absence de fuite

Le chemin de référence est `E:/IGNIS-Valley-dev/datasets/spatial-compact-200-v1`, identifiant interne `spatial-compact-v1` : **120 train / 40 validation / 40 test historique**, respectivement 60/20/20 dispositions. Les familles structurelles sont séparées ; les deux gravités d'une disposition restent ensemble. Conserver les membres et empreintes du snapshot, les signatures physiques et les neuf sources historiques gelées.

1. Optimiser uniquement sur train. Les transformations apprises, poids de classe et choix d'exemples chauds proviennent du train ; les instantanés d'une même trajectoire ne changent jamais de partition. Toute augmentation éventuelle hérite de sa scène d'origine.
2. Les entrées sont géométrie/matériaux, source, conditions et temps. Aucune température, masque chaud, localisation du vrai pic, vitesse FDS observée ou conséquence cible n'entre à l'inférence. Le masque gazeux géométrique est permis ; les masques d'observation servent à exclure les données absentes de la perte et des métriques.
3. Sélectionner checkpoint et seuil uniquement sur validation : maximiser la moyenne des F1 regroupés microgravité et Terre, sur tous les points/temps observés après t=0. Le seuil commun vient de la grille fixée `sigmoid(-12 à +12, pas 0,1)` plus le candidat explicite « tout froid » (seuil supérieur à 1). À objectif égal entre seuils, choisir le moins de faux positifs puis le seuil supérieur ; à objectif égal entre checkpoints, conserver le plus ancien. Figer seuil et poids avant le test. Aucun seuil par scène, aucune sélection après lecture du test. Une perte pondérée ne rend pas le sigmoid calibré.
4. Le test historique de 40 cas a déjà été examiné pendant les recherches précédentes. Le présenter comme **diagnostic sur des scènes hors entraînement déjà connues**, jamais comme nouveau test indépendant. La validation elle-même est réutilisée : une amélioration reste exploratoire, sans garantie de généralisation.
5. Aucune activation ou réécriture des anciens modèles. Le nouveau checkpoint, sa sortie POC et ses métadonnées ont une identité distincte, en développement. Premier fit borné à 650 secondes, dont 150 secondes réservées en fin de parcours ; plafond cumulé de 20 minutes GPU, vérification comprise, avec au plus une correction justifiée par la validation. Les sources et la recette exactes de chaque essai doivent être archivées. Le budget inclut les évaluations nécessaires, avec marge pour sauvegarde et arrêt.

## Références simples et comparaison équitable

Deux références suffisent : **tout froid** et **proximité de la source**. La seconde produit `exp(-distance au patch source / 1 m)`, où la distance euclidienne est celle entre la sonde et la boîte du patch compilé, nulle à son intérieur. Le score reste constant dans le temps. Son seuil suit exactement la grille, l'objectif et les départages de la sélection validation du ML ; son rayon équivalent est `-log(seuil)` mètres pour un seuil au plus égal à 1, et le candidat tout froid n'a pas de rayon. Figer ce choix avant toute mesure test. Le calcul des scores n'utilise ni les cibles ni leur masque de disponibilité ; seul le choix global du seuil utilise la validation. Elle reste une heuristique, pas une simulation de transport.

Évaluer références et ML sur les mêmes cas, coordonnées, instants `t > 0` et masque de température disponible. Tous les instants de chaque trajectoire sont évalués, pas seulement les temps chauds suréchantillonnés pendant l'apprentissage. Conserver les contrôles froids ; le temps initial imposé à l'ambiante ne gonfle pas artificiellement les scores.

| Mesure indispensable | Pourquoi et agrégation |
| --- | --- |
| TP / FP / FN / TN, rappel, précision, IoU | Détecter les zones manquées et les nappes d'alertes. Afficher les comptes, les scores regroupés et les moyennes par disposition ; l'accuracy seule est trompeuse avec ~0,242 % d'observations chaudes dans le train compact. |
| Microgravité et Terre séparées | Les observations chaudes terrestres ne doivent pas cacher les erreurs de la mission microgravité. Ajouter le type d'incident et les lignes par cas, avec leurs dénominateurs. |
| Cas chauds entièrement manqués | Nombre de trajectoires possédant une observation chaude mais aucun vrai positif ; à distinguer du rappel global de points/instants corrélés. |
| Fausses alertes sur cas froids | Fraction de cas sans chaleur mesurée présentant au moins une alerte, et fraction de sondes/instants faussement chauds. « Froid mesuré » ne signifie pas absence de chaleur ailleurs dans FDS. |
| Au lieu/instant du vrai pic | Score et décision binaire au maximum gazeux échantillonné ; utile pour repérer un fort événement manqué. Le classifieur ne peut pas fournir une erreur d'amplitude en °C. |
| Temps complet et mémoire | Chargement/préparation, inférence, export et chargement du visuel séparés lorsque mesurables. Rapporter la mesure réelle, jamais une extrapolation d'un batch GPU à toute l'application. |

Une métrique sans dénominateur valide reste `null` : précision sans prédiction positive, rappel sans cible positive. Pour les moyennes par disposition, indiquer combien de dispositions contribuent. Ne pas attribuer un score parfait aux volumes vides puis le mélanger aux cas chauds.

## Démonstration visuelle et conclusion permise

- Afficher sur la même géométrie et au même instant **zones chaudes FDS / score ML / écarts** ; même seuil et même légende entre cas. Les faux positifs et faux négatifs doivent être consultables. Le FDS reste explicitement une référence simulée.
- L'index léger `demo/hotspots.json` référence les fichiers `demo/cases/{id}.json`, chargés à la demande. Le navigateur permet de consulter les 200 cas, leurs échecs et leurs contrôles froids, avec la partition visible. Les raccourcis utilisent uniquement la validation microgravité : médiane inférieure d'IoU parmi les cas avec dépassement observé, plus faible IoU du même groupe pour l'échec, premier identifiant sans dépassement pour le contrôle froid. Les métriques portent sur le lot complet, pas ces seules images ; un cas train consulté reste explicitement un cas connu.
- La comparaison porte sur un foyer sélectionné. Le corpus compact ne compare pas tous les composants d'une même scène aux mêmes conditions : **aucune revendication de classement global fiable** n'est obtenue par ce seul POC. Une agrégation de départs ne doit jamais être animée comme un feu simultané.
- Si le ML améliore l'IoU tout en conservant un rappel utile et des fausses alertes maîtrisées face à la proximité, la démonstration montre un apprentissage spatial au-delà de cette règle. Sinon, montrer honnêtement la limite et la comparaison ; cela n'impose ni nouvel entraînement long ni activation du modèle comme moteur de risque.
- Un succès train démontre l'ajustement de cas connus. Un succès sur ces scènes historiques hors entraînement est un indice de transfert limité, pas une validation générale, expérimentale NASA ou de sécurité.

À archiver pour la revue du patch/résultat : paramètres et graine, membres train/validation/test, empreintes sources/données/poids, seuil et règle de sélection, étapes réellement exécutées, temps GPU et mémoire, mesures par cas et référence, liste des exports visuels et rechargement exact du checkpoint. Le test de développement doit aussi vérifier le lien score/coordonnées/temps et le refus de champs non prédits.

Base factuelle relue : `fit/dataset-snapshot.json`, `docs/HOTSPOT_AUDIT.md`, `tools/remote/hotspot_spatial.py`, `fit_hotspot_spatial.py`, `verify_spatial.py` et leurs contrats hérités. Le présent protocole est aligné avec `docs/HOTSPOT_POC_MODEL.md` et le contrat du nouveau classifieur ; il ne constitue pas à lui seul un verdict sur les poids ou les résultats de l'entraînement.
