# Contrelecture indépendante — Mission immersive

Date : 14 novembre 2026. Base Git : `a3efd10`. Revue du diff local avant
déploiement de la nouvelle interface sur Windows.

## Conclusion

Aucun écart bloquant ou important confirmé après correction des constats de
revue. La livraison de cette interface exploratoire peut poursuivre son
déploiement statique. Ce document ne certifie ni les modèles physiques ni le
déploiement, qui reste une étape distincte.

## Périmètre et corrections vérifiées

Lecture de `MissionView.tsx`, `MissionViewport.tsx`, `mission-state.ts`,
`mission-rendering.ts`, `mission.css`, de leurs tests et de l’intégration dans
`App.tsx` et `api.ts`.

- Les résultats sans champs spatiaux sont écartés après chargement. Le parcours
  cargo sélectionne désormais `499740fc16e64587aae359ceacf8b193`, qui contient
  des frames, plutôt que le modèle tabulaire sans champ 3D.
- Les réponses tardives de chargement et d’analyse respectent le mode courant.
  Les contrôleurs sont annulés lors des changements concernés. L’absence de
  replay remet explicitement l’état de chargement à zéro.
- La session de prévention conserve paramètres, résultat applicable et
  composant entre les deux vues. Les dépendances de synchronisation gardent des
  références stables ; aucune boucle de mises à jour n’a été identifiée.
- Le passage au laboratoire transmet la configuration et le résultat affichés
  lorsque le laboratoire n’a pas de calcul actif.
- Les libellés distinguent source imposée et combustion couplée. La puissance
  d’une source résistive utilise `I²R`. Les sources NASA affichent leur
  pertinence ; Guo reste identifié séparément comme source du délai, hors NASA.
- La lecture utilise le temps écoulé réel ; un changement de visibilité remet
  l’horloge à zéro pour éviter le rattrapage d’une période en arrière-plan.

## Fidélité des champs

Le replay Soyouz retenu a été consulté sur l’API Windows :
`52687f69460643ada9ff8d8a7573dbca`, FDS 6.11.1, 61 instants de 0 à 60 s,
grille de sortie 8 × 10 × 4 dont 208 points gazeux. Les positions et masques
restent constants, mais les temps et l’axe spatial Y ne sont pas uniformes.

Le rendu conserve les positions exportées et la conversion `(x, z, -y)` du GLB.
L’interpolation temporelle exige deux valeurs valides sur une grille compatible.
Les cellules solides, valeurs absentes et vecteurs incomplets sont exclus ; le
masque 3D tient compte des axes réels. Les bornes de couleur sont calculées sur
la séquence entière, indépendamment de l’instant affiché. Le maximum global FDS
est explicitement distingué du champ spatial échantillonné.

Le mode avant allumage ne crée aucune fumée. Il colore des repères de composants
avec l’historique thermique simulé ou la prévision apprise disponible. Les
repères inconnus restent gris ; les saturations de la palette sont signalées
par `≤ 20` et `≥ 300 °C`, sans transformation de couleur par tone mapping.
La probabilité réelle d’incendie reste non quantifiée dans l’interface.

## Preuves examinées

Le rapport [`verification.json`](verification.json), démarré le
14 novembre 2026 à 14:21:45 UTC, contient **12 contrôles réussis**, sans erreur
JavaScript. Il utilise Vite local avec les véritables données et modèles du
service Windows. Les contrôles couvrent notamment le POV, les trois caméras,
les couches de champ, la variation temporelle avec échelle constante,
lecture/pause, transfert au laboratoire, ML avant allumage, batterie non
couverte, retour des paramètres avancés et disposition mobile.

Les captures POV, prévention et mobile ont aussi été inspectées visuellement.
Les premiers essais échoués sur la cadence de lecture puis sur un sélecteur de
test ne servent pas de preuve finale ; ils sont remplacés par ce rapport passé.

Les gardes contre les réponses tardives et la remise à zéro d’une scène sans
replay ont été revues statiquement : le rapport navigateur ne contient pas
d’injection de course réseau. Les tests unitaires, la compilation et le
formatage n’ont pas été réexécutés par ce reviewer afin de ne pas dupliquer les
contrôles du producteur.

## Limites conservées

Le lissage graphique n’ajoute pas de résolution au solveur et l’opacité n’est
pas un modèle de visibilité optique calibré. La capsule est une représentation
artistique avec un proxy de calcul approximatif. Les composants de prévention
restent hypothétiques et leur modèle thermique n’est pas couplé au champ CFD.
La revue n’ajoute aucune validation expérimentale à ces modèles.

Seul ce rapport a été écrit par le reviewer ; aucun code, service Windows ou
jeu de données n’a été modifié, et aucune écriture Git n’a été effectuée.
