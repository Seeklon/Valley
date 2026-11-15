# Recadrage : contribution vérifiable des ressources NASA

Revue du 14 novembre 2026, 20:49 UTC. Recherche et inspection des archives
existantes uniquement ; aucun calcul FDS, entraînement, accès Windows ou
changement de service. Cette note complète l'audit produit et ne constitue pas
une validation expérimentale du simulateur.

## Ce qui répond au challenge

Le [challenge Flame in Freefall](https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/)
demande de résumer, classer et interpréter les résultats de combustion en
microgravité pour éclairer la sécurité spatiale. La proposition adaptée est un
**explorateur de conséquences conditionnelles, relié aux preuves NASA** :
« Si un incident se produit sur ce composant, quels équipements seraient
exposés, et quelles observations expérimentales éclairent cette conclusion ? »

La 3D sert à comprendre la disposition, le scénario et les chemins de
propagation. Un panneau de preuves doit permettre de comparer les expériences,
leurs conditions et leurs limites de transfert. Un classement de conséquences
synthétiques seul ne répond pas à toute la demande documentaire du challenge.
Le score ne représente ni une probabilité de panne ni une probabilité de feu.

**Accès vérifié :** le titre et l'objectif de la page officielle sont indexés,
mais son ouverture directe, y compris les onglets Details et Resources, échoue
dans l'outil web pendant cette revue. La liste exhaustive actuelle de cet
onglet n'est donc pas revendiquée. Les notices NTRS ci-dessous sont lisibles.
Les pages PSI reposent sur une interface dynamique non lisible par cet outil ;
l'API officielle PSI-98 a répondu HTTP 200 et confirme le DOI, le CSV version 1
et sa taille de 469 octets. Les fichiers déjà archivés restent disponibles
indépendamment de ces limites d'affichage.

## État réel des données présentes

Les trois CSV de [data/sources](../data/sources/) correspondent à leurs
empreintes SHA-256 enregistrées. Leurs **255 lignes ne sont pas 255 trajectoires
de combustion**, encore moins 255 champs 3D :

| Ressource | Contenu local inspecté | Variables disponibles et usage concret | Limite à conserver |
|---|---|---|---|
| [BASS-II, PSI-25](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25), DOI 10.60555/4qc4-de67 | CSV de 129 essais ; métadonnées ; classeur de calibration du ventilateur. | Identifiants/date, matériau et description dimensionnelle, affichages AIR/Fan, réducteur, O₂/CO₂/CO avant et après. Permet de filtrer des expériences proches du matériau, de l'atmosphère et de la ventilation étudiés. | Affichage de ventilateur ≠ vitesse universelle ; mesures avant/après ≠ séries temporelles ni concentration spatiale. Vidéos référencées, contenu non entièrement examiné. |
| [BASS, PSI-26](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26), DOI 10.60555/58h4-dy80 | 122 lignes, dont 121 lignes d'essais et une note ; 116 identifiants d'essai distincts. | Date, identifiants d'exécution/d'échantillon, matériau. Sert de porte d'entrée vers les essais et documents associés. | Les répétitions d'identifiants exigent un rapprochement explicite ; le CSV ne fournit ni vitesse étalonnée ni champ de feu. |
| [Saffire-I, PSI-98](https://psi.nasa.gov/physci/repo/data/investigations/PSI-98), DOI 10.60555/0t15-1z43 | 4 lignes : deux essais S1/S2 et deux références de visualisation d'écoulement. | SIBAL, dimensions, vitesse, O₂, puissance/durée d'allumeur, durée de combustion, sens de l'écoulement, IDs caméra. Comparaison traçable de deux configurations d'écoulement. | Deux essais ne permettent pas d'isoler un effet causal ou d'entraîner un modèle généraliste. SIBAL est un composite spécifique, pas notre cellulose générique. |

Pour Saffire-I, le CSV donne 20 cm/s, soit **0,2 m/s**, un allumeur de
182 W pendant 8 s, et des durées de combustion de 420 s (S1, écoulement
concurrent) et 70 s (S2, opposé). Il indique une longueur de 40,6 cm, une largeur
de 94 cm et une épaisseur de 0,37 cm : ces intitulés sont ceux du CSV, à
rapprocher du montage et des images avant reconstruction. La durée d'allumeur
ne devient pas un délai de panne électrique ; longueur divisée par durée de
combustion ne devient pas automatiquement une vitesse de propagation.

La [calibration BASS-II déjà réalisée](NASA.md) apporte 211 paires instrumentales
admissibles et une conversion documentée de 24 affichages AIR scalaires de
l'inventaire. Elle caractérise l'instrument et ses variations entre sessions.
**Elle ne valide ni la combustion, ni FDS, ni un réseau spatial.**

## Rapports utilisables et contribution précise

| Source primaire | Observables ou résultat effectivement consulté | Contribution proposée et limite |
|---|---|---|
| [BASS-II, rapport 20210011385](https://ntrs.nasa.gov/citations/20210011385) | Notice officielle relue et texte officiel archivé : O₂, vitesse de ventilation, type/épaisseur/géométrie du combustible ; bilan O₂/CO₂/CO ; puissance dégagée estimée à partir de la consommation d'O₂ et de la durée. | Documenter les conditions des essais PSI et interpréter propagation/extinction. Avant comparaison quantitative, retrouver le bon essai, sa chronologie et l'incertitude. Un bilan global ne valide pas les pics locaux de température. Le PDF volumineux n'est pas archivé. |
| [Saffire IV/V, ICES-2021-266](https://ntrs.nasa.gov/citations/20210011521) | Notice officielle relue : images, vitesse de propagation, température de flamme, rayonnement, calorimétrie O₂, température/CO₂ répartis en cabine, autres gaz et aérosols. | Source pertinente pour séparer propagation au combustible et conséquences à distance ; justifie de considérer échantillon, confinement et écoulement. La notice annonce ces mesures ; cette revue n'a pas extrait de nouvelles séries brutes ni vérifié tous les fichiers associés. |
| [Saffire V, ICES-2024-310](https://ntrs.nasa.gov/citations/20240008602) | PDF officiel consulté en ligne, pages 4–7 : température et CO₂ en cabine avec sources imposées d'après capteurs. Pas de nouvelle archive locale. | Cas pertinent pour le transport. **Combustion et flamme ne sont pas modélisées**, explicitement p.4. Les mesures servent aussi à construire/ajuster l'entrée : elles ne sont pas toutes indépendantes. |
| [SAME-2, 20130000422](https://ntrs.nasa.gov/citations/20130000422) | PDF/texte archivés, notice relue : fumée produite par chauffage sous le point d'allumage, écoulement jusqu'à 8 cm/s, vieillissement, tailles et morphologie des particules. Le catalogue conserve 40 cellules de diamètres/moments pour cinq matériaux, avant/après vieillissement. | Explique pourquoi matériau, vieillissement et ventilation comptent pour la détection. Les 720 s du tableau concernent le vieillissement, pas l'allumage. Ni une taille de particule ni un signal optique ne se substituent directement à la concentration de suie simulée. |
| [Wire-break, 20240006315](https://ntrs.nasa.gov/citations/20240006315) | PDF/texte archivés, notice relue : préchauffage puis arc à rupture, matériau proche du fil ; essais tabulés à 23,5 ± 1 psia et > 99 % O₂. | Justifie de distinguer les mécanismes électriques et le matériau exposé. Ces conditions sont très différentes d'une cabine à environ 21 % O₂ ; les courants sont propres au montage. Aucun taux de défaillance opérationnelle n'en est déduit. |

Le [catalogue préallumage](PREIGNITION_SOURCES.md) existe déjà : 13 sources,
22 conclusions et trois journaux historiques sélectionnés, soit 49 lignes
clairsemées. Il conserve provenance, conditions, contradictions et exclusions.
Les journaux ne sont pas admis comme labels de validation d'allumage. Il faut
réutiliser ce travail documentaire au lieu de présenter un nouveau nombre de
scénarios synthétiques comme un enrichissement expérimental.

**Comparaison physique concrète proposée :** reprendre l'événement 6 PMMA de
Saffire V, puis examiner l'événement 8. Prescrire les courbes d'apport de chaleur
et de produits à la sortie du dispositif ; comparer température et CO₂ aux
capteurs distants. La géométrie cargo, la recirculation et le transfert aux
parois font partie du problème. Ces conditions exigent une configuration dédiée
et des séries encore à extraire ; le compilateur IGNIS actuel ne reproduit pas
automatiquement ce montage. Dans l'article, l'entrée CO₂ est corrigée à partir
des capteurs : une reproduction de cette procédure reste conditionnée aux
mesures, pas une validation indépendante. Les tableaux 1 et 3 donnent aussi
des valeurs d'O₂ différentes à clarifier avant calcul. Aucun de ces accords
ne valide par extension notre allumage, notre suie ou une cabine Soyouz.

## Intégration recommandée au parcours 3D

1. **Import et domaine.** Lire les annotations physiques explicites de Blender :
   matériau exact, formulation si connue, épaisseur, géométrie, composants,
   atmosphère, gravité et ventilation. Une texture ne remplit aucun de ces
   champs thermiques. Afficher ce qui manque ou a été simplifié.
2. **Scénarios et conséquences.** Évaluer les départs possibles séparément,
   conserver l'ID de la source et les hypothèses pour chaque région affectée.
   L'agrégation globale décrit des scénarios alternatifs ; elle ne montre pas
   plusieurs feux simultanés.
3. **Recherche de preuves.** Réutiliser le catalogue NASA pour rapprocher
   mécanisme, matériau/formulation, dimensions, gravité, O₂/pression,
   ventilation et observable. Inconnu reste inconnu ; proximité de nom ou de
   couleur ne vaut pas correspondance physique.
4. **Classement explicable.** Classer d'abord la compatibilité des conditions,
   puis la nature des mesures, leur traçabilité et l'indépendance des essais.
   Regrouper article et présentation du même essai. Ce classement documentaire
   est distinct du classement de criticité des composants.
5. **Inspection.** Le clic sur une zone montre scénario, conséquence calculée,
   expérience rapprochée, quantité réellement mesurée, différences de domaine
   et lien vers la source. Une synthèse assistée par IA peut expliciter ces
   rapprochements ; elle ne doit pas inventer les propriétés absentes.

Exemple de formulation utile : « L'équipement voisin est exposé dans notre
simulation pour ce départ et ce débit. BASS-II étudie également l'effet de
l'écoulement sur du PMMA, mais avec une autre épaisseur et un autre montage :
preuve de pertinence du paramètre, pas validation chiffrée de cette zone. »
Une recommandation de déplacement ou de ventilation doit rester rattachée à
la comparaison effectivement calculée ; les sources consultées n'établissent
pas une règle universelle où davantage de ventilation serait toujours mieux.

## Premier périmètre vérifiable, sans entraînement supplémentaire

- Une scène existante et quelques composants déjà annotés ; carte de
  conséquences et choix d'un seul scénario temporel. L'évaluation du moteur
  rapide relève du protocole produit, séparé de la preuve expérimentale.
- Un panneau de comparaison Saffire-I S1/S2 alimenté par le CSV existant :
  conditions, durées et limites visibles. Ne pas fabriquer de vidéo, de
  trajectoire ou d'effet causal manquants.
- Une fiche BASS-II reliée à l'essai exact et à la calibration instrumentale,
  et une fiche SAME montrant pourquoi la concentration simulée seule ne
  prédit pas la réponse d'un détecteur réel.
- Chaque recommandation conserve source, ancre, unités, conditions et statut
  « observé / calculé / extrapolé ». Afficher l'absence de référence comparable.

**Preuve quantitative à construire ensuite :** choisir un petit sous-ensemble
d'essais présentant géométrie, matériau, conditions et mesure temporelle
exploitables ; synchroniser vidéo/capteurs, conserver échelle et incertitudes.
Réserver des essais entiers avant tout ajustement. Comparer uniquement les
observables disponibles : régime entretenu/extinction et progression de front
pour la flamme ; arrivée et évolution aux capteurs pour le transport. Les
essais servant à prescrire une source ou régler un coefficient ne deviennent
pas des tests indépendants de ces mêmes quantités. Une bonne reproduction de
CO₂ n'est pas une validation automatique des aérosols ou de la visibilité.

Il faut maintenir trois résultats séparés : fidélité d'un éventuel ML au
simulateur sur des géométries nouvelles ; accord du simulateur avec des essais
NASA comparables ; utilité du classement pour détecter les zones sensibles.
Les archives examinées ne démontrent actuellement aucun des trois à elles seules.

**Charge indicative, non mesurée :** 0,5 à 1 journée de développement pour
relier l'interface existante à quelques fiches bien tracées ; 1 à 3 journées
d'analyse pour constituer un premier petit cas expérimental quantitatif,
conditionnées à l'accès et à la qualité des données temporelles. Aucune heure
GPU n'est nécessaire pour ce volet documentaire. Le coût d'une reproduction
physique doit être mesuré après définition du montage et du maillage, et ne
se déduit pas de ces estimations de développement.
