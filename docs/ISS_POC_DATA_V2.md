# Campagne complémentaire ISS et habitats — 15 novembre 2026

Cette campagne répond à la demande de poursuivre l'entraînement du même modèle
avec davantage de diversité, y compris hors ISS. Elle reste indépendante du jeu
v1, de ses modèles et des anciens corpus. L'identifiant historique conservé pour
le contrat de chargement est `iss-poc-20261115-v2` ; le contenu couvre six familles,
pas uniquement l'ISS.

Le plan fixe **384 cas sur 48 dispositions nouvelles** : laboratoire à racks,
nœud de circulation, zone technique, soute avec stockage, cabine/capsule sous
forme de proxy rectangulaire et habitat à racks centraux. Il s'agit de géométries
originales synthétiques, pas de plans ISS ou Soyouz ni de mesures NASA. Les
familles sont partagées entre partitions ; cette campagne teste une extension
ciblée à des dispositions et conditions inédites, pas une généralisation à
n'importe quel véhicule.

Chaque famille possède huit dispositions. Les variantes 0 à 4 servent au train,
la variante 5 à la validation et les variantes 6 à 7 au test : **240 / 48 / 96
cas**, soit **30 / 6 / 12 dispositions entièrement séparées**. Les géométries
physiques compilées et les géométries normalisées sont toutes distinctes, et
aucune ne reproduit une disposition v1. Les grilles exactes de vitesse, puissance
nominale et durée principale sont définies par partition avant simulation.
Les familles, types d'incident, gravités et matériaux se recoupent volontairement.

Les changements réellement compilés comprennent :

- Dimensions et positions des racks, hauteurs, largeur/hauteur des baffles,
  échelle physique et organisation centrale ou périphérique.
- Supports aluminium, acier, verre ou isolant ; revêtement PMMA, cellulose ou
  absence de revêtement ; cinq épaisseurs entre 0,6 et 5 mm. Le compilateur
  traite le revêtement sur la face supérieure uniquement, pas sur toutes les
  faces visuelles d'un objet.
- Évents opposés selon X ou Y, avec les deux sens de circulation, dimensions et
  positions variables ; vitesses de 0,04 à 0,34 m/s. Les débits imposés viennent
  des surfaces réellement compilées.
- Trois sources électriques annotées par disposition, positions différentes
  sur les faces supérieures exposées. Les surfaces sources sont choisies près
  des colonnes de sondes pour observer leur effet, sans fabriquer de cibles.

Les huit cas de chaque disposition sont deux flammes sur des sites/conditions
différents, une émission de batterie équivalente à montée progressive, une
émission couvante à puissance réduite, une surchauffe, un arc thermique de 2 à
6 secondes, un témoin 0 W et la comparaison terrestre exacte de la première
flamme. Cela représente **336 microgravités à 0,0001 g**, **48 Terres** et
**48 témoins à puissance nulle**. Les sources sont des conditions aux limites
prescrites : le jeu ne mesure ni probabilité de panne/allumage, ni cinétique
réaliste de batterie ou d'arc.

Chaque cas dure **30 secondes physiques**, sur **13 824 à 17 280 cellules FDS**,
avec une grille d'observation **12 × 16 × 8**, inchangée pour le modèle.
La sortie demandée est de 1 seconde ; les timestamps FDS réels font autorité.
Les arcs les plus courts peuvent rester mal résolus : absence d'observation
positive ne signifie pas absence de danger physique. L'oxygène (21 %), la
pression (101 325 Pa) et la température ambiante (20 °C) restent fixes.

Le pilote prédéclaré comporte 12 cas train/validation des six familles, y
compris deux contrôles, les deux formes d'émission et les profils thermiques.
Aucun cas de test n'est choisi pour le pilote. Le diagnostic de présence des
labels utilise les seuils fixés `T >= ambiante + 5 °C` et `suie >= 1e-6 kg/m³`,
en float64, sur les observations valides après t=0. Les labels de test ne sont
pas résumés pour choisir le jeu ou adapter le fit.

Le générateur utilise quatre processus FDS à un thread chacun, le verrou de
calcul existant et un budget explicite. Le pilote et la campagne doivent tenir
dans **30 minutes cumulées de génération** ; le pilote décide si le débit est
compatible. Les sorties incomplètes restent archivées ; seul un jeu complet et
vérifié reçoit son index figé. L'entraînement CUDA intervient après libération
du verrou de génération et ne fait pas partie de ce budget FDS.

Chemins :

- Scènes : `scenes/iss-poc-v2/`.
- Scripts nouveaux : `tools/remote/iss_poc_v2_design.py`,
  `tools/remote/generate_iss_poc_v2.py`.
- Dataset Windows : `E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v2`.
- Preuves : `evidence/incidents/iss-poc-v2/dataset/`.
- Tests : `tests/test_iss_poc_v2_design.py` — cinq tests passent avant pilote,
  Ruff sans erreur.

Les performances du modèle seront mesurées séparément. Davantage de cas ne
constitue pas en soi une preuve d'amélioration.

## Pilote obtenu à 14:41 Paris

Les **12/12 cas** prédéclarés ont terminé en **49,609 secondes**, lecture et
archivage compris, sans échec. Les observations train/validation contiennent
**824 occurrences chaudes et 5 751 occurrences enfumées**. Les deux témoins 0 W
restent sous les seuils. Le cas d'arc capsule conserve sa cible sans événement
observé (maximum 20,25 °C) ; ce résultat n'a pas servi à fabriquer un incendie.

Les flammes, émissions de batterie/couvant et la surchauffe des racks centraux
donnent des observations actives. Le cas terrestre est plus coûteux que les
autres : 35,8 s contre environ 6 à 17 s de solveur/lecture/archivage pour les
autres cas du pilote. Le débit autorise le lancement des **372 cas restants**
avec un plafond de **1 750 secondes**, soit au plus 1 799,609 secondes cumulées
de génération avant éventuel archivage final. Cette valeur est une limite, pas
du temps déjà consommé.

Une seconde borne surveille le temps réel depuis le premier pilote, y compris
la pause de contrôle : **arrêt de cette seule campagne à 15:10:19 Paris** si elle
n'est pas terminée, soit 30 minutes depuis 14:40:19. Le drapeau d'arrêt reste
dans le répertoire v2 ; il ne concerne ni les services ni les modèles v1.

Le plan effectivement exécuté est conservé dans `pilot-plan.json` avec son
empreinte `97f77e5111e53f79b2a1392587de2075438ea3ba2e86a6b0b4ef4b09fa3254bd`.
La campagne complète n'est déclarée produite qu'après vérification de tous ses
artefacts et de son index final.

Pour une reprise depuis les poids v1, les conditions v2 ne doivent pas être
présentées comme entièrement inédites : certaines valeurs scalaires, par
exemple 0,08 m/s, étaient présentes dans v1. Les géométries, elles, sont toutes
nouvelles ; la séparation exacte des grilles décrite ci-dessus concerne v2.

## Campagne complète vérifiée à 15:06:33 Paris

Les **384/384 simulations** sont terminées, sans échec. La reprise a duré
**1 383,453 secondes**, soit **1 433,062 secondes actives avec le pilote**
(23 min 53 s de FDS, lecture et archivage). Le temps réel depuis le premier
lancement jusqu'à la sortie du générateur est de **25 min 59 s**, puis
**26 min 15 s** jusqu'à la fin de l'audit : la borne de 30 minutes est respectée.
Ces temps n'incluent aucun entraînement GPU.

L'audit a revérifié les **2 688 fichiers** attendus (sept par cas), le plan et
l'index figés, les contrats de provenance/coordonnées/temps/masques, ainsi que
les profils de labels train/validation. Les sorties archivées occupent
1 334 501 546 octets. Les empreintes du plan, du manifeste et de l'index v1 sont
inchangées. Le contrôle des processus effectué après la campagne ne trouve plus
aucun générateur/FDS v2 ; l'ancien corpus reste en pause.

| Partition | Cas | Cas avec chaleur | Cas avec fumée | Occurrences chaudes | Occurrences enfumées | Observations valides |
|---|---:|---:|---:|---:|---:|---:|
| Entraînement | 240 | 193 | 188 | 30 514 | 173 375 | 9 465 525 |
| Validation | 48 | 38 | 38 | 5 606 | 36 926 | 2 056 800 |
| Test réservé | 96 | — | — | — | — | — |

Les **36 témoins train/validation à 0 W** ne contiennent aucun label positif aux
seuils fixés. Les labels de test ne sont pas résumés dans cet audit et n'ont pas
servi à adapter les données. Le déséquilibre reste réel : environ 0,32 % de
points-temps chauds et 1,83 % enfumés dans le train. Ces statistiques établissent
la présence de signaux supervisés, pas la performance du réseau ni la validité
expérimentale du simulateur.

Le relais au réentraînement a été transmis dès le succès de l'audit. Le réseau
et les métriques d'apprentissage restent gérés séparément ; aucun autre calcul
FDS n'est lancé par cette campagne.

Empreintes finales :

- Manifeste : `6004eb0f27862106230e6f043fd5963b4da3ce28414b0559b94ca35724757a6f`.
- Plan : `97f77e5111e53f79b2a1392587de2075438ea3ba2e86a6b0b4ef4b09fa3254bd`.
- Index figé : `a2444f2141f858103dd9497726abc0c4540931775871e3b3a48f79f027a27644`.

Les preuves locales comprennent `verification.json`, `compute-ledger.json`,
`design-diversity.json`, les plans/index, les journaux réels et les états de
sortie des processus dans `evidence/incidents/iss-poc-v2/dataset/`.
