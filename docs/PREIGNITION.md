# IGNIS — prévoir le départ de feu avant l'allumage

Orientation demandée par Thomas le 14 novembre 2026. Une première tranche est
implémentée et entraînée sur Windows : délai conditionnel d'allumage du fil
NiCr/LDPE, modèle thermique exploratoire, prévision de température, marqueurs 3D,
preuves NASA classées, comparaison et export. Les objectifs plus larges du plan
ci-dessous restent une feuille de route, notamment la probabilité calibrée et
le couplage au champ d'air réel de la cabine.

État du socle dans [REPRISE](../REPRISE.md), protocole et chiffres de prévention
dans [PREVENTION_MODELS](PREVENTION_MODELS.md), physique locale dans
[PREIGNITION_PHYSICS](PREIGNITION_PHYSICS.md), corpus NASA dans
[PREIGNITION_SOURCES](PREIGNITION_SOURCES.md).

## Résultat concret et périmètre

| Élément | État actuel |
|---|---|
| Sources NASA | 13 sources archivées, 22 conclusions et 49 relevés historiques avec pages et limites ; ils ne deviennent pas des labels d'allumage automatique |
| Modèle expérimental | 26 points de figure Guo 2023, complément non NASA ; test 9 points/5 courants, MAE 0,157 s, sans validation sur une autre étude |
| Modèle thermique | Deux nœuds conservatifs, fusion, pertes et pyrolyse ; contrôle analytique et convergence, aucune validation thermique expérimentale |
| ML temporel | 384 trajectoires, partitions par famille ; test 1 940 fenêtres disponibles/16 familles, MAE 10,05 °C, maximum 129,30 °C |
| Interface | Soyouz initialement sans foyer, sélection de composants, couleurs selon délai/horizon, passé simulé et deux prévisions distingués, preuves et comparaison |
| Traçabilité | Configurations, séries, poids et sources versionnés ; instantané des preuves par composant, export ZIP et empreintes |
| Probabilité/intervalle | Non calculables avec ces seules données, conservés inconnus ; cas sans allumage et fausses alertes absents |
| Couplage cabine | Air prescrit localement ; aucun transfert du champ FDS vers le fil et aucune validation du câblage Soyouz réel |

Les témoins thermiques à faible courant ou avec coupure servent à comparer
l'échauffement. Ils ne sont pas étiquetés « aucun feu ». Les arcs et batteries
restent non pris en charge, visibles comme inconnus. Les températures sont
simulées, sans capteurs réels ni bruit de mesure. Les couleurs ne représentent
pas des probabilités. Le modèle de délai utilise le courant constant uniquement ;
le modèle thermique utilise un historique mais ne prédit pas l'allumage gazeux.

## Question produit et lien avec le challenge

Dans un environnement spatial 3D, quels composants présentent les conditions
d'un départ de feu à un horizon donné, quelles observations annoncent cette
évolution, et quelles modifications réduisent le risque dans le domaine étudié ?

Le premier cas est l'échauffement résistif d'un fil de laboratoire NiCr/LDPE
positionné dans la scène inspirée du Soyouz. La thermique couvre gravité
terrestre et microgravité ; le délai expérimental est limité à la microgravité.
La scène Soyouz reste une interprétation, sans qualification d'un véhicule réel.

La réponse au challenge repose sur trois résultats visibles ensemble :

1. Résumer les conclusions expérimentales NASA pertinentes pour le composant,
   son matériau, son atmosphère et son écoulement.
2. Classer ces conclusions par pertinence et qualité des preuves ; afficher
   aussi les contradictions, les absences et les limites de transfert.
3. Transformer ces connaissances en exploration préventive : carte 3D,
   prévision conditionnelle, comparaison d'aménagements et explication sourcée.

Le classement des équipements à examiner est distinct du classement des
preuves. Une belle carte de risque sans conclusions NASA comparables ne suffit
pas à remplir le challenge.

## Deux usages avec des informations différentes

| Usage | Informations disponibles | Résultat à viser |
|---|---|---|
| Prévention lors de la conception | Géométrie annotée, matériaux, circuits, ventilation, profils de fonctionnement et hypothèses de défaut | Sensibilité des composants et risque conditionnel aux scénarios explicitement choisis |
| Alerte pendant le fonctionnement | Configuration plus historiques horodatés de capteurs réellement disponibles | Probabilité d'allumage dans l'horizon, conditionnelle à l'absence d'allumage et aux observations présentes et passées |

Le prototype pourra rejouer de la télémétrie simulée ou expérimentale. Aucun
capteur de cabine réel n'est actuellement connecté. Une géométrie 3D seule ne
révèle pas un défaut électrique latent ni la date d'un incident futur.

La quantité cible future, **non implémentée sous forme de probabilité**, est
`P(t < T_allumage <= t + horizon | pas encore allumé à t, observations <= t,
configuration, hypothèses de fonctionnement futur)`.
Les commandes futures ne sont des entrées que si elles sont connues à l'instant
de prévision ou explicitement choisies dans un scénario. Une coupure survenue
plus tard dans l'enregistrement ne doit pas être révélée au modèle.
La position de l'objet évalué est connue ; une position de foyer identifiée
après l'incident ne peut pas devenir une entrée de prévision. Les historiques
reproduisent les retards, le bruit et les absences des capteurs disponibles.

Le risque réel d'une mission exige aussi les fréquences de défaut, les durées
d'exposition et les régimes d'exploitation. Le pourcentage d'allumages dans une
campagne de défauts artificiellement équilibrée ne mesure pas ce risque.

## État des données et sources utiles

Audit du code et des tables archivées, 14 novembre 2026 :

- Le module historique `backend/ignis/ml/features.py` apprend température, oxygène, fumée, vitesse et
  puissance chimique en fonction d'une source prescrite. Aucun label de délai
  d'allumage ni historique électrique n'est utilisé par ces deux modèles FDS.
  Le nouveau module `backend/ignis/preignition/` sépare les modèles avant feu.
- Les 96 calculs pilotes servent à l'étude du transport après source imposée.
  Ils ne sont pas un dataset d'apprentissage de départs de feu.
- Le CSV BASS-II contient matériaux, réglages d'écoulement et concentrations
  initiales/finales ; le CSV BASS est un inventaire d'échantillons et d'essais.
  Ces tables ne fournissent pas les trajectoires électriques et les événements
  nécessaires à une prévision avant allumage. Cela ne préjuge pas des fichiers
  supplémentaires disponibles dans chaque investigation.
- Le CSV Saffire-I archivé contient deux enregistrements de combustion avec un
  allumeur imposé. La colonne `Ignition Time (s)` ne sera pas transformée sans examen du protocole
  en délai naturel d'un défaut électrique.

| Source | Apport prévu | Limite à conserver |
|---|---|---|
| [BASS-II, PSI-25](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25) et [BASS, PSI-26](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26) | Résultats de combustion de solides, matériaux et conditions d'écoulement ; extraction des conclusions et essais comparables | Inventaires déjà archivés, labels d'allumage électrique et mesures avant allumage non établis |
| [Saffire-I, PSI-98](https://psi.nasa.gov/physci/repo/data/investigations/PSI-98) | Effets du feu et du transport à une autre échelle ; contexte des conséquences | Allumage provoqué, géométrie et matériau propres au protocole |
| [NASA, Research Questions and Challenges for Improved Spacecraft Fire Detection](https://ntrs.nasa.gov/citations/20210022143) | Inclut explicitement l'échauffement avant apparition d'une flamme ; références SAME pour les émissions de pyrolyse et les capteurs | Rapport de recherche, pas un dataset prêt à entraîner un modèle d'allumage ; surchauffe détectée et allumage futur sont deux labels différents |
| [NASA, Wire-break Ignition Testing of Materials for Spacesuit Fire Hazard Control](https://ntrs.nasa.gov/citations/20240008688) | Essais de matériaux avec excitation électrique et contexte d'atmosphère | Allumage piloté par rupture/arc, contexte de combinaison ; aucune équivalence automatique à l'auto-inflammation résistive en cabine |
| [NASA, A New Test Methodology for Evaluating Fire Risk Due to Electrical Faults in Oxygen-Enriched Environments](https://ntrs.nasa.gov/citations/20240014551) | Variables de protocole : courant, pression d'oxygène, diamètre, dissipation thermique et volume environnant | Résumé méthodologique consulté ; accès et adéquation des mesures brutes à établir |

Les deux notices d'allumage électrique et le rapport de détection ont été
intégrés au corpus de conclusions. Ils ne servent pas à calibrer le délai
d'allumage : leurs protocoles ne fournissent pas les labels nécessaires.
La lecture du PDF de détection
confirme le besoin de couvrir l'échauffement avant flamme et l'effet des
conditions de chauffage sur les signatures. Elle ne démontre aucune performance
prédictive d'IGNIS.

Pour chaque résultat extrait : source/version/page ou cellule, unité,
matériau exact, dimensions, gravité, pression, oxygène, vitesse et direction
locales de l'air, protocole de chauffage, mesure, incertitude, interprétation
des auteurs et limites. L'absence reste explicite. Aucune substitution silencieuse
de SIBAL, Kapton ou isolant de câble par la cellulose/PMMA génériques du socle.

## Chaîne physique et apprentissage à compléter

1. **Scène instrumentée.** Associer les objets 3D aux câbles, connecteurs,
   matériaux, circuits, profils de charge, dissipations, bouches et capteurs.
   Distinguer valeur mesurée, donnée constructeur et hypothèse de scénario.
2. **Échauffement local.** Modèle électrothermique adapté au composant : résistance
   dépendant de la température, conduction, contacts, convection locale,
   rayonnement et protection électrique. Coupler la pyrolyse et l'allumage
   seulement avec des propriétés et une cinétique justifiées par des essais.
   Identifier les échanges pour la gravité et l'écoulement étudiés ; une
   corrélation terrestre de convection naturelle ne se transfère pas par défaut
   à la microgravité.
3. **Écoulement de cabine.** Réutiliser FDS pour les conditions environnantes
   après vérifications ciblées. Une maille de cabine de 20 cm ne résout pas
   l'isolant millimétrique d'un câble. Définir le couplage local et ses bilans ;
   traiter explicitement la recirculation au lieu de supposer de l'air frais.
4. **Campagnes avant feu.** Générer fonctionnement normal, surchauffe qui cesse,
   protection déclenchée, absence d'allumage jusqu'à la fin et allumage observé.
   Échantillonner des défauts pour apprendre la frontière, en conservant les
   distributions choisies et les poids. Les fréquences synthétiques restent
   distinctes des fréquences de défaut d'un équipement réel.
5. **ML temporel.** Commencer par une référence physique et une règle simple,
   puis un modèle compact de risque dans le temps prenant en charge la censure.
   Évaluer d'abord des variables de composants et des historiques courts ; une
   représentation 3D à l'écran n'impose pas un réseau neuronal volumique.
6. **Conséquences.** Explorer séparément ce qui se passerait après allumage.
   Les modèles actuels restent limités à leur domaine ; leur sortie ne valide
   pas un nouveau scénario de câble ni un risque toxique.

Définir l'événement d'allumage selon chaque protocole : premier flash, flamme
entretenue ou combustion couvante ne sont pas interchangeables. Un dépassement
de température arbitraire ne devient pas une preuve de feu. Documenter le critère
d'observation et la résolution temporelle ; conserver un intervalle si la date
exacte est inconnue. Après une coupure électrique, continuer l'observation pour
ne pas exclure un allumage retardé par construction.

Chaque trajectoire conserve `component_id`, `scene_id`, `family_id`, provenance,
horodatages, capteurs observables et incertitudes, événement, fenêtre de survenue
et fin d'observation. Un essai terminé sans événement est censuré à sa fin :
ce n'est pas une promesse d'absence de feu après cette date. Un calcul échoué
n'est jamais un exemple sain. Les horizons ne sont évalués que lorsque les
observations et le traitement de la censure le permettent.
Un arrêt d'observation provoqué par la surchauffe ou une intervention peut être
une censure informative : il doit être distingué d'une fin programmée et pris
en compte dans le protocole d'évaluation.

Les arcs et l'emballement des batteries exigent leurs propres modèles et essais.
Leur absence de prise en charge sera visible pour les composants concernés.

## Cible de la vue 3D et extensions restantes

- Avant toute flamme : composants colorés par une métrique nommée et un horizon
  explicite ; zones inconnues ou hors domaine en gris. Faible valeur ne signifie
  pas absence de danger. Aucune carte dense n'invente une précision spatiale
  supérieure aux données de composants/capteurs.
- Au clic : courbe d'échauffement, observations utilisées, estimation du délai
  et du risque lorsqu'elles sont défendables, incertitude, mécanisme couvert,
  preuves NASA pertinentes et écarts au cas étudié.
- Une indication permanente distingue mesure expérimentale, simulation,
  prédiction validée sur simulation et prédiction évaluée sur essais réels.
- Comparaison avant/après d'une modification de charge, de matériau, de
  protection ou de ventilation. L'écoulement peut modifier à la fois le
  refroidissement et l'apport d'oxygène ; aucune recommandation universelle
  d'augmenter ou de couper l'air n'est encodée.
- Classement des zones par risque conditionnel et conséquences renseignées,
  avec couverture des preuves séparée. Sans quantification défendable, afficher
  une sensibilité sous scénario et une insuffisance de données, sans pourcentage
  présenté comme fréquence réelle. Ne pas additionner des probabilités de
  composants corrélés pour fabriquer une probabilité de cabine.

Codex résume et explique les résultats avec leurs sources. Les valeurs de risque
proviennent des calculs et des modèles évalués. L'explication distingue une
association, un résultat expérimental et l'effet d'une intervention simulée.

## Critères scientifiques pour élargir la première tranche

| Étape | Livrable | Preuve nécessaire |
|---|---|---|
| 1. Faisabilité des données | Catalogue de conclusions NASA et matrice des observables/labels ; choix d'un couple composant/matériau | Essais avant allumage et témoins identifiés, accès et qualité documentés ; absence de données rendue visible |
| 2. Référence avant feu | Modèle local couplé au contexte Soyouz et événements traçables | Bilans, convergence locale et comparaison à des essais réellement compatibles ; seuils et tolérances fixés avant l'évaluation |
| 3. Dataset et ML | Trajectoires positives, négatives sur horizon observé et censurées ; modèle de référence puis modèle entraîné | Partitions par expérience/composant/famille ; aucune fenêtre voisine entre train et test ; transformations et calibration ajustées hors test |
| 4. Dashboard 3D | Carte avant allumage, courbes, comparaison et panneau de conclusions NASA classées | Un parcours complet lie composant, estimation, domaine et preuve ; hors domaine visible ; simulation et mesure jamais confondues |
| 5. Évaluation indépendante | Rapport et exemples de succès/échec reproductibles | Avance d'alerte, événements manqués, fausses alertes par durée observée, calibration par horizon et couverture du domaine ; comparaison à une règle simple au même budget de fausses alertes |

Les données expérimentales réservées doivent tester le transfert au réel.
Un bon score sur des simulations établit seulement l'approximation de leur
modèle physique. Les seuils d'alerte et critères d'acceptation seront figés sur
l'entraînement/validation avant d'ouvrir le nouveau test. Les anciens jeux de
test ne servent pas à choisir les améliorations.

Parcours actuel : ouvrir Soyouz sans foyer, analyser les fils témoins, consulter
le délai appris et les températures, puis les conclusions NASA ; comparer une
baisse de courant. Une coupure peut être explorée thermiquement, mais rend le
délai expérimental hors domaine. Il manque des cas réellement observés sans
allumage pour évaluer une matrice d'alertes complète.

Calcul et entraînement sur le PC Windows existant ; traitements par blocs et
petits modèles avant toute montée en volume. Un petit pilote mesure coût,
mémoire et qualité des labels avant génération massive. Le GPU 12 Go ne résout
pas l'absence d'observations pertinentes. Le pilote thermique et les deux
entraînements ont été réalisés ; leurs tests sont désormais réservés à cette
évaluation et ne doivent pas servir au réglage d'une prochaine version.
