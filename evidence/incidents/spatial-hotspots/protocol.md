# Essai ciblé sur les foyers — 14 novembre 2026

**Statut final : interrompu à la demande de Thomas pour recadrage produit.**
Le protocole ci-dessous décrit l'essai historique, pas une autorisation de
reprise. Diagnostic terminé, fit `hot` terminé ; ablation `hot_peak` arrêtée
après sauvegarde de la mise à jour 9 500. Aucun nouveau lot prospectif généré,
aucune évaluation sur ces 100 cas et aucun modèle activé dans l'interface.
`prospective-membership.json` ne contient que les appartenances prévues.

L'arrêt à 20:41:36 UTC a terminé uniquement les processus de l'ablation après
contrôle de son checkpoint ; le runner n'avait pas de STOP interne. La sortie
−1 n'est pas une finalisation normale. Le checkpoint a ensuite été rechargé
strictement sur CPU et ses tenseurs contrôlés finis, sans inférence ni CUDA.
Le générateur historique a traité STOP normalement, avec ses 64 résultats
conservés. Voir `user-stop.json`, `recadrage-runtime-state.json`,
`recadrage-artifact-check.json` et la
[proposition consolidée](../../../docs/RECADRAGE_PRODUIT.md).

Autorisation utilisateur : « go … utilise bien du compute à fond … travaille sur les points chauds ».
Budget annoncé : une nouvelle heure au maximum depuis le lancement Windows à
20:18:57 UTC (21:18:57 Paris), diagnostics, éventuelles références et entraînement inclus.
Fin limite : 21:18:57 UTC. Aucun redémarrage automatique de la campagne initiale.

## Question et séquence

Le réseau actuel peut-il reproduire une forte température au lieu et à l'instant
mesurés, sans transformer les volumes froids en fausses alertes ? Ce diagnostic
précède toute affirmation de généralisation ou augmentation du réseau.

1. Comparaison sur huit trajectoires d'entraînement : les trois incidents
   thermiques les plus chauds dans chaque gravité (surchauffe, feu déclaré,
   batterie), plus un contrôle sans observation active dans chaque gravité.
   Choix à partir des seules cibles TRAIN, jamais des prédictions ni du test.
2. `uniform` et `hot` : mêmes poids initiaux, réseau 834 486 paramètres,
   batch 32, AdamW, 3 000 mises à jour demandées par recette et perte historique.
   `hot` conserve 50 % de temps uniformes, plus 50 % des instants du quartile
   supérieur de température parmi les instants chauds ; masse égale par cas.
   La séquence de tirages change volontairement. Évaluation : trajectoires
   entières avec leurs instants d'origine, aucune repondération.
3. Si ce tirage ne récupère pas les pics, comparer une seule correction de
   perte : `hot_peak`, mêmes poids, tirages et nombre de mises à jour que
   `hot`, plus 0,5 × SmoothL1 au maximum observé de chaque champ actif, à sa
   vraie coordonnée. Les cibles globales FDS ne remplacent jamais les sondes.
4. Étendre au train compact/validation seulement si l'ajustement des foyers
   connus progresse sans nappe artificielle sur les contrôles. Apprentissage
   neuf, sélection par validation ; ancien test exclu du développement.
   Une nouvelle évaluation indépendante exige de nouvelles géométries gelées
   avant leurs résultats. À défaut, publier uniquement train/validation.

Les diagnostics ont une limite interne de 900 s ; une recette interrompue par
le budget sera identifiée par son nombre de mises à jour réel. Une comparaison
avec des nombres différents n'est pas une ablation à budget égal. Déterminisme
cuDNN activé ; certaines opérations backward CUDA restent non déterministes
(signalées par PyTorch). Un seul seed : pas de significativité statistique.

## Mesures et décision

Mesurer rappel ET précision au seuil ambiance + 5 °C, amplitude prédite à la
coordonnée/au temps du pic échantillonné, maximum prédit, distance du maximum
à la bonne position, décalage temporel et faux positifs des contrôles froids.
Rapporter par cas et par gravité ; les observations successives ne sont pas
indépendantes. Le pic du domaine FDS peut ne pas être mesuré par la grille
12 × 16 × 8 : les métriques ne démontrent rien dans les volumes non observés.

Porte d'ingénierie pour étendre : au moins les deux plus fortes trajectoires
microgravité doivent retrouver leur excès thermique à ±20 % et leur pic à
moins d'un pas de grille ; le taux de points faussement chauds des contrôles
doit rester inférieur à 0,1 %. Ces seuils exploratoires ne sont pas une norme
incendie. Sinon, garder le résultat en diagnostic et identifier ce qui bloque.

## Invariants

Données existantes et neuf sources du modèle précédent inchangées. CUDA sur
Windows uniquement ; plafond allocateur 5 GiB, données du petit lot en VRAM.
Sorties exclusives nouvelles, verrou de calcul partagé, campagne 20 000 cas
conservée en pause, aucune activation automatique dans l'interface. Tests de
contrats sur petits tenseurs CPU avant le calcul. Les résultats sont des
approximations de simulations FDS, pas des probabilités réelles de panne ni
une validation expérimentale NASA.

## Extension décidée avant le test — 20:36 UTC

Le fit `hot` terminé en 577,36 s choisit la mise à jour 7 250 sur 20 000.
Le rappel chaleur de validation monte de 6,57 % (ancien entraînement) à
35,81 %, mais les pics nouveaux restent très sous-estimés. Dans TRAIN, le
foyer échantillonné à 372,06 °C ne reçoit que 223,51 °C à son vrai pic.
La porte franchie sur huit cas ne suffit donc pas à l'échelle des 120 cas.

Une dernière ablation `hot_peak` est décidée sur ces seuls résultats
train/validation : mêmes 120/40 cas, poids initiaux, tirages, batch 32,
20 000 mises à jour demandées et budget 900 s ; seule la perte change avec
l'ancrage local des maxima observés des deux champs. Aucun test nouveau
n'est encore généré ni évalué. Le score de sélection de validation reste
`localization_selection_error`. La sélection du candidat de comparaison
sera figée avant la génération du lot prospectif. Aucun autre tuning après
lecture du test. Le budget commun finit toujours à 21:18:57 UTC.
