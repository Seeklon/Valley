# Reprise — IGNIS 3D / Valley

15 novembre 2026. Version consolidée pour `main` : moteur IGNIS, modèle ventilation,
site immersif issu de `codex/valley-pov-site`, tests et preuves. Lors d'une reprise, relire Git
et `/api/health` pour connaître l’état actuel du code et du service.

## Consolidation du projet dans main

Thomas a demandé explicitement de pousser tout le projet dans `main` : le
laboratoire, le backend, le site immersif intégré, les scènes, poids, scripts,
tests et documents sont réunis. Le site racine conserve les cinq commits de
`codex/valley-pov-site`, jusqu'à `0e7a2d1`. Les sources et preuves du laboratoire
sont conservées avec leur historique.

Les 216 replays courants sont versionnés, compressés individuellement, sous
`data/predictions/ignis-20261115-vent/` (276 960 518 octets avec index/manifeste).
Leur index et les JSON décompressés conservent les empreintes livrées. Les hooks
`predev`/`prebuild` des deux interfaces restaurent et vérifient les données
locales ; un import personnalisé explicite reste préservé. Le kit Python déjà
livré est copié sans changement dans `models/ignis-20261115-vent/`.
Le [README principal](README.md) décrit le démarrage depuis un clone.

Cette consolidation concerne Git et les vérifications locales ; elle ne
redémarre ni les services Windows ni le site public et ne lance aucun calcul
FDS, entraînement ou ajustement du modèle.

## Priorité actuelle — spécialisation ISS et intégration du 15 novembre

**Nouvelle instruction explicite de Thomas le 15 novembre vers 13:49 Paris :**
préparer une amélioration ciblée du modèle et son intégration dans la maquette
pour la présentation à **18 h Paris aujourd'hui**. La maquette sera envoyée ;
elle conduit de l'espace à une station puis à ses scènes intérieures. Thomas
confirme des géométries simples proches de l'ISS. Cette autorisation remplace
la consigne d'arrêt automatique de la livraison d'hier, pour ce lot borné.

**État courant : adaptation ventilation terminée, auditée et livrée sur dev
le 15 novembre vers 16:22 Paris.** Même réseau : 379 046 paramètres au total,
376 834 entraînables. 216 nouvelles simulations FDS appariées, 24 dispositions
et six familles ; 108 train / 54 validation / 54 test. Réentraînement depuis V2
sur ses 240 anciens cas train et les 108 nouveaux, avec réflexions X/Y sur GPU.
Génération + audit : 13 min 49 s ; fit, évaluations et export : 7 min 32 s,
dont une fenêtre entraînement/validation de 5 min 02 s. GPU médian 98 % dans
cette fenêtre, moyenne 85,27 %, maximum 99 %. Aucun nouvel entraînement lancé
après l'ouverture du test ; le corpus initial de 20 000 reste en pause.

Sur les 54 nouveaux cas de test, face au V2 recalibré selon la même procédure :
F1 chaleur 0,388 → 0,553, fumée 0,393 → 0,579 ; rappel chaleur 0,347 → 0,601,
fumée 0,359 → 0,594. Réponse signée aux variations de ventilation : F1 chaleur
0,126 → 0,374, fumée 0,127 → 0,448. Les six témoins 0 W sont sans faux positif.
**Limites :** les faux positifs chaleur augmentent de 3 841 à 4 971 ; légère
régression chaleur sur les racks centraux. Ces décomptes sont des observations
de sondes dans le temps, pas des incendies indépendants. Voir
`docs/ISS_POC_VENT_MODEL.md` et `evidence/incidents/iss-poc-vent/final-review.md`.

Les poids/seuils ont été figés avant le test ; checkpoint 5 000. La contrelecture
indépendante confirme les gardes de sélection. Les 216 replays, scores archivés,
comparaisons et références FDS ont été vérifiés indépendamment :
`evidence/incidents/iss-poc-vent/export-verification.json`.
Poids SHA256 `ce0ffc80e51d9be2da94fc50f098fc4ac3c223203d09c8908ea8bbd6f4eff292` ;
index SHA256 `7e587516076d6f50abb26dd9cb0119072c64764a26e920a4d8ba179c9bf9246e`.
Livraison statique : `evidence/incidents/iss-poc-vent/dev-delivery.json`,
229 fichiers changés sans redémarrer le backend. V2 locale conservée dans
`runtime/iss-poc-v2-public-preserved`, sauvegarde dev dans
`E:/IGNIS-Valley-dev/runtime/iss-backup-20261115T152133Z`.

L'interface propose sans débit / lent / rapide / inversé pour un même quartet,
en conservant caméra et temps visé. Elle affiche le temps réellement observé
sans interpoler les relevés. 34 tests frontend, build, non-régression V2 et
contrôle navigateur du quartet réel passent. Contrôle final du dev terminé
à 16:30:07 Paris : 17 contrôles, 33 captures, aucune erreur JavaScript ni
écriture ; index et poids identiques avant/après. Preuves dans
`evidence/incidents/iss-poc-vent/browser-dev/`.
L'apprentissage reste une approximation de FDS : aucun champ de vitesse
intérieur complet en entrée, ni validation expérimentale NASA. La prédiction
est conditionnelle à une source imposée, pas une probabilité de départ de feu.

**Dernière instruction de Thomas : livrer d'abord le modèle, revenir sur les
seuils après.** Les poids et seuils sélectionnés sont conservés. Une lecture
exploratoire des seuils voisins sur les 54 nouvelles validations a été sauvegardée
dans `validation-threshold-sensitivity.json`, sans sélection ni changement livré.
Ne pas lancer d'autre entraînement ou ajustement de seuil par anticipation.

Paquet du modèle livré et relu par HTTP :
<https://desktop-m4hkr86.tail609f26.ts.net:8444/downloads/ignis-model-20261115-vent.zip>.
Copie locale `runtime/ignis-model-20261115-vent.zip`, 1 798 192 octets, 30 fichiers,
SHA256 `b7e1da6b6e97f2f4bc4c74fe092acbc5eca19fd27f878a227fb146ea1fb892e7`.
Poids, code d'inférence Python, dépendances, exemple, métriques et preuves inclus.
Inférence CPU réelle du paquet exécutée sur Windows : cinq instants × 1 536
sondes × deux champs, depuis scène et conditions, sans FDS ni apprentissage.
Preuves : `evidence/incidents/iss-poc-vent/model-delivery.json` et
`model-kit-verification.json`. Le paquet ne contient pas les gros replays de
l'interface ; le kit frontend V2 reste disponible en attendant la maquette.

**Étape précédente : réentraînement v2 terminé, contrôlé et livré vers
15:29 Paris.** Même réseau, 379 046 paramètres au total, 376 834 entraînables.
384 scénarios nouveaux, 48 dispositions, six familles (dont cargo, cabine et
racks centraux), 240 train / 48 validation / 96 test. Génération 23 min 53 s,
fit complet 8 min 32 s ; GPU médian 98 %, maximum 99 %. Compute terminé,
verrou libéré. **Instruction de Thomas vers 15:32 Paris :** améliorer
rapidement les zones manquées et l'effet de la ventilation en microgravité.
La campagne bornée de 216 cas FDS appariés et le réentraînement GPU décrits
ci-dessus ont répondu à cette demande. Les poids V2 ont été conservés jusqu'à
mesure de l'amélioration. Les nouvelles dispositions de test sont restées
réservées jusqu'au gel de la sélection.
Le FDS installé reste un solveur CPU ; les augmentations et l'apprentissage
GPU ne sont pas de nouvelles simulations CFD.

Sur les mêmes 84 cas de test microgravité : F1 chaleur **24,6 → 48,5 %**, fumée
**27,6 → 54,3 %**, face aux poids v1 recalibrés. Poids choisis sur validation
à l'étape 1 000, puis test ; 14 387 mises à jour effectuées. Les six familles
gagnent, mais la qualité reste celle d'un POC synthétique. Les géométries sont
distinctes des partitions v1, pas les familles ni toutes les conditions.

Audit indépendant : `evidence/incidents/iss-poc-v2/export-verification.json`
(384 replays contre les observations FDS, poids et comparaisons v1 archivées).
Rapport : `evidence/incidents/iss-poc-v2/model/fit1/report.json`.
Poids SHA256 `37bf3e0c5394cbe52fe520ebf85cbf393cd9b4203751d5b1db5c0c79641f987a` ;
index SHA256 `94d4c81e9ec55a9178f3d004ad52ece238d67faf9b6318e88aa17664bd68a5a7`.
Livraison : `evidence/incidents/iss-poc-v2/dev-delivery.json` (386 fichiers
changés, exports réutilisés depuis le fit Windows après contrôle des hashes).
V1 locale conservée dans `runtime/iss-poc-v1-public-preserved`, sauvegarde dev
dans `E:/IGNIS-Valley-dev/runtime/iss-backup-20261115T142633Z`.

Kit autonome créé : `runtime/ignis-integration-20261115-v2.zip` (476 744 556
octets, SHA256 `ab73293cf09358d265df995a77d3b88299185f63b8f340b7479854fb611b2550`).
Il contient la vue React/Three, les 384 exports, les poids et l'inférence CPU.
Contrôle navigateur dev terminé à 15:34:50 Paris : 16 contrôles, 31 captures,
six familles, aucune erreur JavaScript ni écriture. Preuve :
`evidence/incidents/iss-poc-v2/browser-realistic-dev/browser-report.json`.
Kit autonome : build, trois contrôles navigateur et inférence CPU Windows
réels réussis (`standalone-kit/` et `model-kit-verification.json` dans le même
dossier de preuves). Ce kit V2 est conservé ; le dev utilise désormais les
poids de l'adaptation ventilation indiqués en tête de document.

**Première tranche livrée sur dev le 15 novembre à 14:35 Paris** :
<https://desktop-m4hkr86.tail609f26.ts.net:8444/#iss>. 108 scénarios FDS vérifiés,
18 dispositions, 72 train / 18 validation / 18 test. Réseau U-Net 3D identique
au backbone existant, 379 046 paramètres, deux sorties chaleur/fumée. Poids
sélectionnés à l'étape 1 000, après validation ; test réservé ensuite.
F1 test microgravité : chaleur 67,3 %, fumée 67,4 %, contre 36,8 % et 33,5 %
pour la proximité du foyer. 7 min 18 s de génération, 4 min 55 s pour le fit
complet ; GPU médian 96 %, maximum 99 %. Lire `docs/ISS_POC.md` pour les
limites, preuves et parcours. L'interface lit des inférences enregistrées.

Le contrôle indépendant des 108 exports compare toutes les observations,
masques, géométries et métriques aux données FDS et lie les fichiers aux vrais
poids et au dataset figé. 18 tests modèle Windows, 16 tests vérificateur,
94 tests frontend initialement, puis 14 tests ciblés d'interface après les
correctifs caméra/timeline. Contrôle navigateur réel local réussi sur les
modules, témoin, échec, test, navigation et chronologie. Preuves sous
`evidence/incidents/iss-poc/`. Le backend dev reste sur 8766 / HTTPS 8444.
Le service historique 8765 / 8443 n'a pas été redémarré ; le corpus initial
reste en pause. L'ancien POC est toujours accessible sur `#poc`.

**Nouvelle instruction utilisateur après cette première tranche :** générer
plus de scénarios divers, y compris hors ISS, et améliorer le réalisme 3D.
Thomas précise : réentraîner le même modèle, sans changer d'architecture.
Campagne v2 distincte terminée : 384 cas / 48 dispositions, six familles
(laboratoire, nœud, service, cargo, cabine simplifiée, racks centraux), cible
240 train / 48 validation / 96 test. Budget génération 30 minutes maximum,
puis fit/évaluation 10 minutes, tous deux respectés. Résultats réels ci-dessus.
Initialisation depuis v1 déclarée. Comparer v1 figé, v1 seulement recalibré
sur nouvelle validation, et poids réentraînés sur les mêmes données réservées.
Aucun résultat test ne doit guider le fit. Pas de reprise des 20 000 anciens cas.

Rendu réaliste livré sur le même dev vers **15:04 Paris** : équipements,
panneaux, textures locales et lumière aux dimensions des proxies, sans modifier
les passages d'air ni déplacer les sondes. Les prédictions v2 sont maintenant servies.
15 tests ciblés, build et 13 contrôles navigateur locaux réussis ; 19 captures
dans `evidence/incidents/iss-poc/browser-realistic-final/`. Une première passe
navigateur interrompue reste documentée séparément, cause non établie.
La maquette externe est toujours attendue ; préparer le paquet
réutilisable, mais ne pas prétendre l'avoir intégré avant de l'avoir reçue.
Aucune prétention à une réplique ISS vérifiée, généralisation universelle ou
validation expérimentale NASA. Les scores ne sont pas des probabilités de
feu, des températures, ni des concentrations de fumée.

## Livraison précédente — POC ML visuel du 14 novembre

**Nouvelle instruction explicite de Thomas, le 14 novembre vers 22:11 Paris :
terminer ce soir un entraînement ML simple et démontrer visuellement la
détection des points chauds pour la présentation du lendemain.** Cette demande
remplace la limite « proposition uniquement » ci-dessous. Le planning de 4–7
jours n'est plus celui du rendu. Aucun objectif de modèle généraliste ou de
validation NASA complète n'est ajouté au POC.

**Calcul terminé et modèle figé le 14 novembre à 22:37 Paris.** Deux essais CUDA,
9 min 22 s au total, validation/export inclus ; aucune nouvelle génération FDS.
FIT1 conservé selon validation (F1 moyen des gravités 0,325 contre 0,318 pour
FIT2). GPU mesuré à 98 % durant FIT2 après optimisation des lots et de la boucle.
Les poids FIT1 sont conservés malgré cette optimisation du second essai.
120 cas train / 40 validation / 40 historiques, 100 dispositions. Le test
historique est déjà connu des essais précédents ; ce n'est pas un test vierge.
Les deux processus sont terminés, ancien corpus toujours en pause. Aucun
entraînement ni génération supplémentaire à lancer automatiquement.

POC livré sur la version de développement à **22:41 Paris** :
`https://desktop-m4hkr86.tail609f26.ts.net:8444/#poc`. Comparaison 3D synchronisée
FDS/détection ML, chronologie, 200 cas, exemples représentatif/échec/témoin,
comparaison avec la proximité source et fréquence des fausses alertes par cas.
Les vues relisent des inférences enregistrées. Les services 8443 et 8444 sont
sains ; aucun backend redémarré. Copies de sauvegarde de l'interface précédente
dans `E:/IGNIS-Valley-dev/runtime/hotspot-backup-20261114T214105Z`.

Vérification indépendante des 200 replays réussie : valeurs exactes, masques,
métriques, groupes et séparation des dispositions. 82 tests frontend et build
passés ; 17 tests modèle Windows et 8 tests du vérificateur passés. Les résultats
restent limités : rappel microg 39,6 % validation / 47,1 % historique, Terre
historique 8,8 % ; fausses alertes dans 7/18 puis 8/22 cas sans dépassement.
Lire `docs/HOTSPOT_POC.md` pour le pitch et le parcours ; ne pas annoncer de
probabilité de départ, fumée ML, généralisation fiable ou validation NASA.

Sources nouvelles dans `tools/remote/train_hotspot_poc.py`,
`web/src/components/HotspotPocView.tsx` et `docs/HOTSPOT_POC*.md`.
Preuves et captures : `evidence/incidents/hotspot-poc/` ; modèle Windows
`E:/IGNIS-Valley-dev/runtime/hotspot-poc/20261114-evening/fit1`.

## Historique — recadrage produit et arrêt précédent

**Demande explicite du 14 novembre : ne pas poursuivre la feuille de route ML.
Livrer une proposition argumentée avant tout nouveau calcul lourd.** Lire
[la proposition consolidée](docs/RECADRAGE_PRODUIT.md), puis les audits
[produit](docs/RECADRAGE_ETAT_PRODUIT.md),
[options](docs/RECADRAGE_OPTIONS.md) et [NASA](docs/RECADRAGE_SOURCES_NASA.md).
Les étapes proposées dans les sections historiques ci-dessous ne sont pas
des instructions de reprise automatique.

Vérification Windows du 14 novembre à **20:49 UTC / 21:49 Paris** : aucun
processus FDS/génération/entraînement actif ; API 8765 et dev 8766 répondent
`status=ok`. Le générateur initial a traité `STOP` et est **arrêté à 64 cas** ;
`PAUSE` est conservé. Les 100 cas supplémentaires du lot prospectif n'ont
**jamais été lancés** ; leur répertoire de sortie n'existe pas. Les scripts
préparés et listes d'appartenance sont des plans, pas des résultats.

Le fit hors ligne `hot` est terminé : 20 000 mises à jour, checkpoint 7 250,
577,36 s, 120 train / 40 validation. Rappel thermique de validation 35,81 %,
précision 28,66 % au seuil ambiance + 5 °C ; de forts pics sont encore manqués.
L'ablation `hot_peak` a été interrompue à 20:41:36 UTC après vérification du
checkpoint sauvegardé **9 500**. Le runner n'ayant pas de contrôle STOP, seuls
ses processus ont été terminés : sortie wrapper −1, pas de finalisation normale.
Poids rechargés strictement sur CPU, tenseurs finis et SHA-256 vérifié ; aucun
forward, aucun calcul GPU pour ce contrôle. Ne pas présenter cet essai partiel
comme comparable à 20 000 mises à jour ni comme un entraînement finalisé.

Preuves dans `evidence/incidents/spatial-hotspots/` : `user-stop.json`,
`recadrage-runtime-state.json`, `recadrage-artifact-check.json`, `fit/report.json`
et `fit-peak/validation-step-009500.json`. Poids/logs conservés sur Windows sous
`E:/IGNIS-Valley-dev/runtime/hotspots/20261114-h1`. Aucun nouveau modèle activé ;
l'interface incidents utilise toujours l'ancien Extra Trees exploratoire
`incident-field-v1`. Aucune modification de l'application ni des services
pour ce recadrage ; seulement contrôles légers, archivage et documentation.

## Historique — essai spatial borné, modèle non activé

Essai du 14 novembre terminé : **44 min 58 s de phases**, **50 min 55 s écoulées**,
génération et entraînement compris. Ne pas lancer de calcul supplémentaire au
nom de ce budget ni reprendre automatiquement les 20 000 cas. Le contrôle final
à 19:49 UTC confirme zéro processus de calcul, deux API saines, campagne initiale
**en pause à 64 cas**, anciens modèles préservés.

Le compact final `E:/IGNIS-Valley-dev/datasets/spatial-compact-200-v1` contient
200 cas / 100 dispositions : 192 nouveaux FDS et 8 réutilisés de l'ancien corpus.
Le premier compact de 100 cas est conservé séparément. L'identifiant interne des
deux datasets reste `spatial-compact-v1` ; consulter chemin et empreinte du plan.
Entraînement CUDA neuf `spatial-recovery-v1` : 170 cas / 66 dispositions après
réutilisation des seuls trains historiques, validation 40 cas / 20 dispositions,
test réservé 40 cas / 20 dispositions. 52 époques, époque 32 retenue ; 7 min 32 s.
Poids dans `E:/IGNIS-Valley-dev/runtime/models/spatial-recovery-v1`.

Résultat insuffisant : rappel chaleur global 1,94 %. La fumée globale atteint
87,09 % de rappel / 57,37 % de précision, mais la microgravité seule donne
71,99 % / 18,52 %. Les pics restent sous-estimés. Aucune activation UI ; le
parcours Prédiction conserve son modèle précédent exploratoire. Le test final
est maintenant connu ; tout ajustement futur exige un autre test réservé.

Lire le [bilan mesuré](evidence/incidents/spatial-recovery/README.md), le
[registre de calcul](evidence/incidents/spatial-recovery/compute-ledger.json)
et la [recherche ML](docs/SPATIAL_RESEARCH.md). Prochaine priorité proposée :
supervision près des foyers et rareté des observations chaudes, avant davantage
de génération uniforme. Les archives ont U/V/W ; les cibles actuelles n'utilisent
que température/suie. Aucun nouvel apprentissage ni calcul lancé après le test.

## Parcours incidents et corpus spatial — travail du 14 novembre 2026

La version de développement isolée est `E:/IGNIS-Valley-dev`, port 8766,
URL privée Tailscale `https://desktop-m4hkr86.tail609f26.ts.net:8444`.
La version précédente et ses données restent dans `E:/IGNIS-Valley` sur 8443.

L'accueil devient Prédiction, avec Simulation par point sensible et Sources NASA.
Chaque incident sélectionne un composant annoté ; ses objets voisins gardent
leurs matériaux combustibles. Cinq familles : surchauffe, arc thermique équivalent,
feu déclaré, couvant et batterie équivalente. Aucun risque probabiliste n'est déduit.
Les limites et inconnus sont visibles ; les anciens écrans restent sous Outils.

Pilote réellement exécuté : 60 calculs FDS, 12 dispositions, train30/validation15/test15.
ExtraTrees `incident-field-v1` entraîné CPU en109s. Les scores du test montrent
qu'il ne surpasse pas la référence ambiante sur température moyenne de champ et
HRR ; ne pas annoncer un modèle généraliste. Poids/données conservés sur Windows,
métadonnées, résultats et preuves légères dans `evidence/incidents/`.

Thomas a ensuite demandé beaucoup plus de diversité : nouveau corpus procédural
cible1000 environnements ×20 cas =20000 FDS, dix familles structurelles, 1536 points.
Il a aussi demandé à être prévenu au lancement effectif du trainingGPU. Le réseau
est spatial3D (U-Net), pas un LLM ; voir les documents SPATIAL_*.
Relire progress.json et les journaux avant d'affirmer l'avancement.
Ne pas confondre cette cible avec des simulations déjà produites ni avec le pilote.

**GPU réellement exécuté** le 14 novembre, premier pas à 16:10:29 UTC,
fin à 16:12:20 UTC : RTX 4070 Ti, PyTorch 2.7.0+cu128, U-Net 834486 paramètres,
20 époques, époque 19 retenue sur validation. Modèle `spatial-pilot-v1` dans
le runtime dev, preuves `evidence/incidents/spatial-pilot/`. Thomas a été prévenu
immédiatement après le premier backward/optimizer synchronisé.
Le score composite test bat l'ambiance, mais température moyenne, suie moyenne
et HRR restent moins bons ; surchauffe et arc régressent. Pas d'activation UI.
Le parcours Prédiction utilise toujours `incident-field-v1`, clairement signalé
comme exploratoire. Aucun des deux pilotes n'est un modèle généraliste validé.

Le nouveau lanceur `tools/remote/run_spatial_study.py` enchaîne corpus complet
puis entraînement CUDA `spatial-corpus-v1`. Il refuse un corpus incomplet et
respecte PAUSE/STOP avant le training ; chaque enfant possède son verrou de
calcul, aucun verrou de calcul imbriqué. Ne pas relancer un poids existant.

**Campagne initialement lancée, mise en pause puis arrêtée à 64 cas**. Journal détaché :
`E:/IGNIS-Valley-dev/runtime/training/study-735d5f67483b4030ad0140e05de7bb38/worker.log`.
État léger : `datasets/spatial-corpus-v1/progress.json`, également accessible par
`GET /api/incidents/campaign`. Le test navigateur a repris les deux premiers
cas puis vérifié pause après le cas courant et reprise à quatre cas achevés,
sans erreur JS. Ce compteur est historique ; relire l'état avant de le citer.
Une éventuelle reprise nécessite une nouvelle décision après le recadrage ;
ne pas retirer STOP/PAUSE au nom de l'ancienne feuille de route. Une fermeture
du PC nécessite de relancer le job ; aucun démarrage automatique Windows
n'est installé. Ne pas lancer un second orchestrateur.

Validation de cette tranche : 299 tests Windows, puis 21 tests du trainer après
l'ajout des empreintes source ; Ruff et vérification du diff réussis. Frontend :
65 tests, build et formatage ; 12 contrôles navigateur incidents et 5 contrôles
de campagne réels. Revue indépendante et résultats dans `evidence/incidents/`.
Les deux premiers cas procéduraux ont été relus : 31 instants, 1536 points,
archives gzip/ZIP vérifiées par SHA, six champs conservés. Les poids du pilote
3D ont également été rechargés et exécutés en inférence CPU avec succès.

## Version précédente : vue mission immersive — 14 novembre 2026

L'accueil est maintenant **Mission** : POV équipage dans Soyouz, fumée douce
colorée par température, couches fumée/température/ventilation, caméras orbite
et dessus, lecture/pause/vitesse et panneau latéral repliable. Le mode avant
allumage affiche les températures des composants et partage la session avec
les paramètres de Prévention. La fumée n'est jamais déduite de ces prévisions.

- Relecture Soyouz réelle `52687f69460643ada9ff8d8a7573dbca`, 61 champs sur 60 s ;
  sélection dynamique depuis `/api/runs`, hors résultats purement scalaires.
- Échelles fixes sur le replay, interpolation aux temps réels, axes non uniformes
  et masque des cellules respectés. Le lissage n'ajoute pas de résolution physique.
- Coque artistique complétée visuellement en POV ; données, proxies, moteur et
  poids inchangés. Aucun entraînement ni nouveau calcul FDS pour cette refonte.
- **34 tests frontend**, build TypeScript/Vite et formatage réussis ; **12 contrôles
  navigateur réels**, aucune erreur JavaScript. Captures, revue et preuve du
  déploiement statique dans `evidence/mission/`.
- Lire `docs/MISSION_VIEW.md` pour navigation, unités et portée du rendu.
  Le backend n'a pas été redémarré ; les anciens assets restent disponibles
  pour les onglets déjà ouverts, et l'ancien index est sauvegardé dans le runtime.

## Prévention avant allumage livrée

L'onglet Prévention ouvre Soyouz sans foyer. Quatre composants hypothétiques par scène,
dont deux fils NiCr/LDPE, un faisceau non caractérisé et une batterie non couverte.
Le délai vient d'un modèle expérimental restreint ; température physique et
prévision ML sont distinctes. Comparaison, preuve par composant, Codex et ZIP
fonctionnent. Aucune probabilité calibrée ni intervalle n'est inventé.

- 13 sources NASA, 22 conclusions et 49 relevés historiques archivés ; une étude
  complémentaire Guo, explicitement hors NASA, fournit 26 points d'allumage.
- `ignition-delay-guo-v1` : test 9 points/5 courants, MAE 0,157 s, maximum 0,335 s.
  Protocole NiCr/LDPE sous courant maintenu en microgravité uniquement.
- `thermal-history-forest-v1` : 384 trajectoires Windows, 16 familles test,
  1 940 fenêtres couvertes ; MAE 10,05 °C, maximum 129,30 °C. Physique locale
  exploratoire, pas de chimie d'allumage ni de validation thermique expérimentale.
- 131 tests Windows, Ruff, 22 tests frontend, build/format passent. 9 contrôles
  réels des modèles/API, 12 contrôles navigateur prévention et 8 contrôles
  de non-régression du laboratoire réussis ; aucune erreur JavaScript.
- Explication réelle par Codex `gpt-6.1-sol`, avec faits figés par composant.
- Preuves et revue indépendante : `evidence/prevention/`. Modèles/datasets
  dans `E:/IGNIS-Valley/runtime/prevention/`, distincts du registre FDS.
- Archive vérifiée de 99 fichiers, 39 142 723 octets :
  `G:/IGNIS-Valley-archives/ignis-prevention-v1-20261114T125618Z.zip`.
  SHA et vérification de chaque entrée dans `evidence/prevention/archive-verification.json`.

Lire `docs/PREVENTION_MODELS.md`, `PREIGNITION_PHYSICS.md`,
`PREIGNITION_SOURCES.md` et `PREVENTION_API.md`. L'air local est prescrit ; la
position 3D ne couple pas encore le fil au champ FDS. Les fréquences de panne,
cas sans allumage et données indépendantes nécessaires à un risque réel manquent.
Les datasets/modèles archivés ne doivent pas être écrasés ni leurs tests utilisés
pour choisir une amélioration. Les scripts refusent leur réécriture.

## Accès et exploitation

- Dépôt `/home/platform-admin/projects/Valley`, branche `codex/ignis-3d-lab`.
- URL privée Tailscale : `https://desktop-m4hkr86.tail609f26.ts.net:8443`.
- Sur le PC Windows : `http://127.0.0.1:8765`.
- Lanceurs : `tools/windows/start-ignis.ps1` et `stop-ignis.ps1`.
  Ils survivent à la fermeture SSH et contrôlent l’identité du service.
- Dernier démarrage vérifié : PID 24436, wrapper 6472. Ces numéros sont
  historiques ; utiliser le fichier d’identité pour arrêter le service.
- État du service : `E:/IGNIS-Valley/runtime/service/api-process.json`.
- Pas de tâche au démarrage Windows : relancer avec `docs/WINDOWS.md`.
- L’interprétation utilise **Codex**, détecté dans l’installation Windows déjà
  authentifiée. Aucun appel Ollama dans IGNIS. L’autre service Ollama sur HTTPS
  443 a été préservé.

## Socle FDS et preuves antérieures

- Quatre scènes Blender/GLB détaillées : habitat, cargo, crossflow et Soyouz.
  Soyouz est une interprétation originale avec proxy physique simplifié.
  `evidence/blender-verification.json` contrôle assets et import/export annoté.
- FDS 6.11.1 : froid, transport, combustion couplée et chauffage I²R réellement
  exécutés. Compilateur `ignis-fds-2`, matériaux `ignis-fds-materials-2`.
  Convergence de maillage non établie.
- 96 simulations pilotes, 5 800 instants ; deux modèles entraînés et préchargés :
  `field-mlp-v2`, `metrics-forest-v2`. Séparation 48/12/36 par calculs/familles.
- Audit Windows : CSV originaux, 96 fichiers FDS et échantillonnages identiques,
  partitions, domaines, latences et poids vérifiés. Identité physique version 2
  normalisant uniquement les flottants entiers ; hashes FDS exacts inchangés.
- Tables NASA BASS-II/BASS/Saffire-I archivées avec DOI/version/hash.
  Calibration ventilateur : 211 paires, 171 pour ajustement et 40 pour test.
  Calibration instrumentale uniquement ; aucune validation de combustion.
- Parcours réel complet : **15 contrôles réussis**, couvrant les huit prédictions
  scène/modèle, FDS Soyouz, export, domaine, annulation, campagne Parquet et Codex.
  Preuve : `evidence/application-verification.json`.
- **58 tests Windows réussis** et Ruff sans erreur. XML dans
  `evidence/windows-final-tests.xml`. Les 7 tests lifecycle sont aussi conservés
  dans `evidence/windows-lifecycle-tests.xml`.
- Contrelecture indépendante : `evidence/final-review.md` ; constats de
  concurrence des lanceurs, fermeture des processus et validation des citations
  corrigés et vérifiés.
- Navigateur sur l’URL Windows : 8 contrôles généraux et 7 contrôles de prédiction
  réussis, aucune erreur JavaScript, vues desktop/mobile inspectées. Rapports
  et captures dans `evidence/ui/`. Les aperçus temporaires du VPS ont été arrêtés.

## Localisateurs Windows

- Connexion SSH privée ignorée `.remote-pc.json`, contrôleur `tools/remote/pc.py`.
  Ne jamais afficher de clés ou recopier des secrets dans Git.
- Dossier isolé `E:/IGNIS-Valley` : `app/`, `.venv/`, `tools/`, `runtime/`,
  `datasets/pilot-v2/`. Ryzen 7 3700X, 16 Go RAM, RTX 4070 Ti 12 Go.
- Blender 4.5.9 LTS, Python 3.11.2, Torch 2.7.0+cu128, FDS 6.11.1.
- Poids : `E:/IGNIS-Valley/runtime/models/`. Copies de métadonnées et métriques
  dans `evidence/models/` et `docs/MODELS.md`.
- Archive vérifiée :
  `G:/IGNIS-Valley-archives/ignis-pilot-v2-models-20261114T112409Z.zip`.
  1 351 fichiers, 157 279 419 octets compressés, empreintes relues ;
  `evidence/archive-verification.json` et manifeste adjacent sur G:.
  Les métadonnées finales des modèles correspondent à cette archive.
- Les gros calculs et rendus restent sur Windows. Le VPS coordonne et conserve
  code, sources et petites preuves. Son port 8765 appartient à un autre projet.

## Limites et suite scientifique

Lire `docs/PHYSICS.md`, `NASA.md`, `MODELS.md` et `SCENES.md` avant d’élargir le
domaine. Les modèles imitent des simulations FDS exploratoires à 0,20 m ; ils
ne prédisent pas la vérité expérimentale NASA. Le réseau ne contraint pas la
cohérence moyenne/maximum/champ et sous-estime certains pics Soyouz. Les erreurs
par scène et gravité sont visibles dans l’interface. Aucun ajustement sur le test.

Une nouvelle géométrie doit être annotée, compilée, simulée et faire l’objet
d’un nouvel entraînement. La visualisation seule ne lui donne pas un domaine
prédictif. Réserver de nouvelles familles de test avant toute amélioration ML.
Thomas a précisé la priorité : prévoir le départ de feu avant l'allumage et
localiser le risque dans la 3D. Le cadrage est dans `docs/PREIGNITION.md` :
premier cas de surchauffe électrique, conclusions NASA comparables, trajectoires
avant feu et témoins, modèle temporel, validation indépendante et incertitude.
La première tranche est livrée selon le périmètre décrit en tête de ce document.
Les 96 calculs de source prescrite restent distincts du dataset d'allumage.
La prochaine étape scientifique exige cas témoins, validation indépendante et
couplage fil/cabine ; les températures simulées seules ne comblent pas ces données.

## Méthode conservée

Le plan est dans `PLAN.md`. Agentic fournit méthode et revue, sans conventions
produit Seeklon. L’utilisateur demande réalisation autonome et visuels réguliers
en français. Les lots physique, frontend et revue sont terminés ; conserver leurs
preuves. Avant une nouvelle session, vérifier Git, l’état du service, la file de
calcul et les capacités réelles, sans rejouer les 96 simulations par défaut.
