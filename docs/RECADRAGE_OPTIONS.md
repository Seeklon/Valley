# Options pour une cartographie de criticité conditionnelle

Proposition du 14 novembre 2026, après lecture du recadrage utilisateur. Aucun nouveau calcul lancé pour ce document. Estimations de développement en jours de travail d'une personne, distinctes du calcul machine ; elles excluent la reconstruction d'un modèle Blender mal annoté.

## Décision proposée

**Livrer d'abord une analyse automatisée de plusieurs départs avec FDS, un cache et un classement explicable, puis le scénario 3D sélectionné.** Une géométrie nouvelle ne nécessite pas d'entraînement FDS. La première analyse prend du temps ; le cache rend ensuite l'exploration rapide. Un indicateur géométrique immédiat peut aider à explorer la scène, mais ne remplace pas les résultats physiques.

Le ML reste une option d'accélération à comparer à cette référence. Il ne doit pas conditionner la livraison du parcours. Cette recommandation découle des résultats et du coût mesuré, pas de l'existence du code actuel.

## Ce qui est utile et ce qui manque

- Réutilisable : scènes annotées, compilateur FDS, cinq profils d'incident, worker et annulation, résultats avec provenance, mesures d'exposition, vue POV/orbite, fumée/chaleur temporelles et passage « carte → composant → simulation ». `IncidentService.predict_map` parcourt déjà tous les composants ; son moteur actif est Extra Trees, pas le nouveau réseau spatial.
- À construire : orchestration déterministe FDS pour tous les composants, cache par entrées physiques et versions, classement accompagné de ses raisons, carte agrégée explicitement distincte d'un incendie unique, couverture/inconnus visibles et validation du classement.
- Déviation constatée : augmenter les scènes et réduire une erreur de champs n'a pas démontré qu'on retrouve les départs les plus conséquents. Le compact contient 200 cas sur 100 géométries, deux gravités par géométrie ; il ne balaie pas systématiquement tous les composants de chaque géométrie avec les mêmes conditions. Il ne suffit donc pas à valider leur classement relatif.
- Le fit `hot` terminé prend 577,36 s pour 20 000 mises à jour, checkpoint retenu à 7 250, sur 120 train / 40 validation. Sur validation : rappel chaleur 35,81 %, précision 28,66 % au seuil ambiance + 5 °C. Aux vrais pics de deux cas microgravité, 456,73 et 297,20 °C deviennent 21,62 et 24,17 °C. Ce sont des observations de validation, pas un nouveau test indépendant ni des scores de classement produit. Elles empêchent de considérer une zone froide prédite comme rassurante.

## Trois architectures réalistes

| Option | Livraison concrète, données et environnement nouveau | Réponse et calcul | Développement restant, limites |
| --- | --- | --- | --- |
| **FDS multi-départ + cache** | Un scénario par composant/profil/conditions ; classement par conséquences et champs temporels 3D. Géométrie physique, matériaux documentés, bouches, sources et conditions ; aucune base d'apprentissage requise. | Première carte calculée progressivement sur CPU Windows ; ordre de grandeur mesuré du corpus compact : ~39 s/cas, quatre workers. Résultats déjà calculés : chargement interactif à mesurer. | **2–4 jours estimés** pour orchestration, cache, explications, branchement et contrôles, hors import. La nouvelle géométrie doit être compilable ; maillage, physique et matériaux restent à vérifier. Pas d'assurance de temps constant sur une cabine plus complexe. |
| **Géométrie + physique simplifiée** | Graphe composants/obstacles/matériaux/passages ; proximité, visibilité et chemins d'air donnent un indice explicable d'exposition. Un transport advection-diffusion simplifié pourrait produire ensuite une prévisualisation temporelle. | Cible projetée : indice pour ≤10 composants en <2 s sur CPU ; non mesurée. Pas d'entraînement. Champs simplifiés plus coûteux et non disponibles aujourd'hui. | **2–5 jours estimés** pour un indicateur et son benchmark ; **5–10 jours** si l'on ajoute des champs dynamiques vérifiés. Le sens des bouches ne donne pas les recirculations internes. Un cône de fumée ou une distance inverse seuls ignorent obstacles et extinction ; ni température précise ni allumage voisin démontrés. |
| **ML spatial hybride + référence FDS** | Géométrie et conditions encodées, source parcourue pour chaque composant ; champs température/suie et conséquences dérivées. FDS vérifie les situations importantes ou hors domaine. | L'inférence GPU peut être rapide ; le replay existant de 60 cas connus a pris 2,58 s pour l'ensemble de son script, pas un benchmark HTTP de carte complète. Préparation, transfert et rendu restent à mesurer. Générer les références coûte encore du CPU. | **4–8 jours estimés** pour intégration, benchmark et contrôle du domaine avec les poids existants ; aucun délai honnête garanti pour obtenir une généralisation satisfaisante. Données nouvelles nécessaires pour comparer tous les départs d'une scène. Les faux négatifs actuels imposent de laisser ce moteur expérimental. |

Ces coûts sont des alternatives qui se recouvrent ; ne pas les additionner comme s'ils étaient tous nécessaires. La physique simplifiée est une référence concurrente à tester, pas une étape imposée avant FDS.

## Calcul de la carte et scénario choisi

1. Valider le paquet Blender, ses unités, proxies et annotations ; montrer les propriétés inconnues. Les textures ne fournissent pas la conductivité, l'inflammabilité ou la production de suie. L'audit d'import est traité séparément.
2. Fixer une famille d'incident, une puissance/rampe/durée et les conditions communes, puis énumérer **chaque composant électrique**. Une source potentielle n'est pas une probabilité de panne. Ne comparer des sources de puissances différentes que si leurs profils sont explicitement justifiés.
3. Créer ou retrouver chaque scénario avec une clé incluant géométrie, matériaux, composant et position appliquée, ventilation, gravité, ambiance, profil, horizon, maillage et versions. La carte indique « 3/8 calculés » ; le reste est inconnu, jamais sûr. Le cache n'ajoute aucun scénario simultané.
4. Extraire un vecteur de conséquences par source : équipements critiques exposés, passages exposés, autres équipements exposés, première exposition, volumes chauds/enfumés et pics. Classement par critère choisi ; un défaut possible est équipements critiques, puis délai d'exposition, puis autres équipements, avec ordre affiché. Aucun pourcentage de feu ni somme pondérée opaque.
5. Pour une carte globale de volume, montrer séparément l'enveloppe maximale de chaleur ou fumée des scénarios étudiés et mémoriser le scénario responsable de chaque zone. **Une enveloppe de possibilités n'est pas une simulation où tous les départs ont lieu ensemble.** Cliquer une zone retrouve son scénario ; cliquer un composant ouvre sa trajectoire seule avec chronologie, hypothèses et provenance.
6. Autoriser ensuite des profils/conditions supplémentaires. Un maximum parmi eux reste le pire des cas étudiés, pas une espérance de risque. Aucune fréquence implicite égale entre surchauffe, arc et batterie ; les profils équivalents actuels doivent rester visibles.

Les seuils existants de 60 °C gazeux et 10 mg/m³ de suie sont des comparateurs exploratoires, pas des seuils d'allumage ou de survie. Une sonde proche d'un objet mesure son exposition gazeuse, pas sa combustion. Les points non couverts restent inconnus ; ajouter des sondes ciblées est préférable à rendre une interpolation plus spectaculaire.

## Si le ML est repris plus tard

Entrées : occupation/proxies 3D, propriétés physiques et épaisseurs, bouches et débit imposé, gravité, oxygène, ambiance, position/aire/profil de la source et temps. L'air aux bouches n'est pas un champ de vitesse intérieur connu. Les identifiants de scène ne sont pas des variables prédictives.

Sorties : température et concentration de suie sur les coordonnées/instants observés, puis le même vecteur d'exposition que FDS. Cibles : observations FDS masquées, arrivées et équipements exposés calculés de manière identique ; jamais des températures globales recopiées sur des voxels. Une tête de classement n'est justifiée qu'avec des comparaisons de composants d'une même scène à conditions comparables.

Évaluer tous les composants signifie parcourir les sources et grouper leurs requêtes, en réutilisant les caractéristiques de géométrie communes. Ce n'est pas demander un score de pièce au réseau avec un seul foyer. Le champ détaillé peut être demandé uniquement pour la source sélectionnée. La réduction de coût doit être mesurée pour ce parcours complet.

Pas de reinforcement learning à ce stade : les références supervisées existent déjà. Une meilleure pondération, des cas difficiles ou une cible de classement peuvent être testés ensuite, avec contrôles négatifs et validation par scène ; ils ne corrigent pas automatiquement un simulateur ou une représentation inadéquats.

## Démonstration courte et validation utile

Périmètre proposé : une scène annotée avec 5–10 composants, une famille de départ à la fois, horizon 30 s, microgravité, puis une variante de ventilation ; Soyouz conservé pour montrer le parcours immersif. Les cinq profils restent sélectionnables, mais la validation d'un profil ne valide pas les quatre autres. Les modifications de géométrie/conditions invalident les résultats correspondants.

Avant toute nouvelle campagne, figer un petit benchmark : trois environnements absents des ajustements, cinq sources chacun, deux conditions de ventilation, soit **30 références par profil et gravité**. Les futurs ajustements utilisent d'autres environnements ; ne jamais séparer aléatoirement des instants d'une même scène. Commencer avec une famille, puis étendre si le produit apporte une information utile. Aucun de ces calculs n'est lancé ici.

| Critère | Mesure et preuve attendue |
| --- | --- |
| Classement | Recouvrement des top-3 avec FDS et présence du départ le plus conséquent dans les trois premiers, par scène. Fixer le critère de conséquence avant les résultats ; publier cas d'échec, ex æquo et dénominateurs. |
| Départs dangereux | Rappel des sources exposant au moins un équipement critique ou passage, au seuil/horizon annoncés ; faux positifs FP/(FP+TN), précision et part de sources sans conclusion. Une méthode qui refuse tout ou alerte partout ne passe pas. |
| Propagation | Précision/rappel des équipements exposés ; IoU des régions chaudes, erreur au vrai lieu/instant du pic et distance du pic. Ne pas inférer l'allumage d'un équipement depuis la seule température du gaz. |
| Fumée | IoU au seuil choisi, pics locaux et délai d'arrivée aux passages ; arrivées manquées séparées de l'erreur de temps. Une absence d'arrivée avant 30 s est censurée, pas un délai nul. |
| Utilité de la ventilation | Deux dispositions ou ventilations comparées à source identique ; vérifier que la recommandation de changement repose sur la variation des conséquences, avec source expérimentale pertinente et limites. |
| Réactivité | Temps complet jusqu'à première carte et jusqu'à tous les composants, p50/p95 à froid et cache chaud ; temps de sélection/rejeu, RAM/VRAM et fluidité 3D. Objectif proposé : carte cachée <2 s, sélection <1 s, sans bloquer l'interface. |

Portes exploratoires proposées pour une méthode rapide, à fixer avant benchmark : retrouver le pire départ dans le top-3 dans chaque scène, rappel des sources dangereuses ≥90 %, faux positifs ≤20 %, et temps de carte <2 s pour ≤10 sources. Ce sont des objectifs d'ingénierie, pas des scores acquis ni des normes. Trois scènes sont une démonstration limitée : publier aussi les comptes bruts, les métriques par gravité/famille et les cas hors domaine.

Comparer géométrie simplifiée et ML à FDS permet de mesurer un gain d'approximation, pas la fidélité au feu réel. FDS comparé à ses propres sorties donne une identité tautologique : contrôler sa résolution sur quelques cas sensibles, sa conservation et les observables expérimentales réellement comparables. Un classement qui change avec un raffinement raisonnable doit être présenté comme instable.

## Temps et étapes, séparés

- **Mesuré, CPU** : 192 nouvelles simulations compactes et 8 réemplois obtenus en deux phases totalisant 2 091,23 s ; la seconde phase produit 100 nouveaux cas en 1 110,5 s avec quatre workers d'un thread. Les ~39 s/cas sont une durée individuelle moyenne, pas un p95 ni un délai garanti. Le débit de cette phase est ~5,4 nouveaux cas/minute, préparation et archivage inclus.
- **Projection, calcul** : à géométrie/horizon/résolution comparables, 5–10 sources d'un profil prennent environ 1–3 minutes ; 30 références environ 6–10 minutes avec marge. Cinq profils multiplient les cas par cinq. Une géométrie plus fine, un horizon plus long ou un système ventilé complexe invalident cette extrapolation ; mesurer un premier cas avant de réserver un budget. FDS est sur CPU Windows ; la RTX sert au ML, pas à accélérer ce FDS.
- Cette projection suppose de réutiliser le pool à quatre workers déjà mesuré hors ligne. La file API actuelle traite les calculs en série : au même ordre de grandeur de 39 s/cas, compter plutôt 3–7 minutes pour 5–10 départs, avant surcoûts. La concurrence et la mémoire doivent être vérifiées dans le parcours produit.
- **Mesuré, GPU** : diagnostic A/B 143,31 s ; entraînement `hot` complet 577,36 s avec évaluations. Ces minutes ne quantifient pas la qualité acquise. L'ablation interrompue ne fournit pas de résultat final comparable.
- **Projection, développement du MVP FDS** : 0,5–1 jour pour la file multi-source et le cache ; 1–2 jours pour classement/enveloppe/scénario/explications ; 0,5–1 jour pour tests et parcours complet. Puis 1–2 jours d'analyse/validation du petit benchmark et de rattachement NASA, distincts du temps machine. Pas de génération massive ni d'entraînement requis pour cette première tranche.

## Retour au challenge NASA et sources de cette proposition

La carte doit relier chaque conséquence ou recommandation à des observations NASA classées par matériau, oxygène, ventilation, gravité et type d'essai ; elle peut comparer leur applicabilité et exposer les contradictions. Le catalogue sourcé existant est réutilisable. Une belle simulation seule ne répond pas au challenge. La calibration du ventilateur BASS-II documente une vitesse locale instrumentale, pas la validité de la combustion en cabine ; les ressources et comparaisons précises font l'objet du lot documentaire séparé.

Faits techniques vérifiés dans `backend/ignis/incidents.py`, `backend/ignis/ml/spatial_network.py`, `backend/ignis/campaigns.py`, `docs/INCIDENTS.md`, `docs/INCIDENT_PHYSICS.md`, `docs/NASA.md`. Mesures : `evidence/incidents/spatial-recovery/compute-ledger.json`, `generation-200-progress.json`, `replay-report.json` et `evidence/incidents/spatial-hotspots/fit/report.json`. Les capacités générales de FDS ne doivent pas être confondues avec notre compilation limitée aux proxies, couches supérieures et sources équivalentes ; aucune validation expérimentale de cabine n'a été démontrée.
