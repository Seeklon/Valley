# Vérifier la réponse à la ventilation

Protocole fixé le 15 novembre 2026 avant le nouveau fit et l'ouverture des
observations de test. La version v2 reste disponible sur dev pendant l'essai.

La campagne ventilation contient 24 nouvelles dispositions, six familles et
216 calculs FDS. Les partitions réservent des dispositions entières : 108 cas
d'entraînement, 54 de validation et 54 de test. Un quartet conserve les
équipements, matériaux, foyer, puissance, durée, ambiance et graine du solveur.
Il varie le débit : 0, 0,12, 0,36 m/s, puis 0,36 m/s en sens inverse. Chaque
disposition a aussi un témoin sans puissance. Ces valeurs sont des conditions
aux évents ; elles ne constituent pas un champ intérieur uniforme.

Le nouveau fit garde l'architecture et les 54 canaux du réseau v2. Les
augmentations par réflexion horizontale doivent transformer les coordonnées,
la source, les vecteurs de ventilation, les masques et les cibles ensemble.
Elles utilisent des symétries des scènes existantes ; ce ne sont pas de
nouvelles solutions CFD. FDS reste exécuté sur CPU, l'apprentissage sur GPU.

## Choix du checkpoint

La référence est le réseau v2 recalibré sur les mêmes 102 cas de validation
(48 anciens et 54 nouveaux). Le réseau v2 aux seuils déjà livrés reste aussi
une comparaison descriptive. Les seuils du candidat utilisent la même
méthode de F1 moyen par famille et par canal que la référence recalibrée.

La sélection utilise 75 % de F1 moyen par famille chaleur/fumée sur la
validation combinée et 25 % de F1 des changements signés sur les quartets de
validation. Les conditions supplémentaires sont :

- F1 moyen sur l'ancienne validation v2 au moins égal à la référence moins 0,02.
- Précision de chaque canal en microgravité sur la validation combinée au
  moins égale à la référence moins 0,03.
- Rappel de chaque canal sur cette même population au moins égal à la référence.
- Aucun faux positif sur les témoins de puissance nulle des deux validations.
- Gain sur le score composite et sur le score de changements de ventilation.

Les poids initiaux sont le candidat de repli. Les observations du nouveau test
ne sont ouvertes qu'après écriture de la sélection figée. Le test ne sert pas
à essayer d'autres seuils ou checkpoints. Les familles restent communes aux
partitions : il s'agit d'un test sur de nouvelles dispositions de ces familles.

## Mesure appariée indépendante

`tools/remote/evaluate_iss_ventilation.py` compare trois interventions dans
chaque quartet : sans débit → lent, sans débit → rapide, rapide → inversé.
Les métriques absolues chaleur/fumée restent calculées aux vrais temps FDS.

Le pas adaptatif de FDS donne des temps légèrement différents selon les cas.
Pour la comparaison appariée, les horizons demandés sont 5, 10, 15, 20, 25 et
30 secondes. Le script interpole linéairement température et suie **avant**
seuillage, et les scores du réseau séparément. Cette mesure est une
approximation temporelle, identique pour la référence et le candidat.

Aucune extrapolation n'est permise. Les deux observations encadrantes doivent
être valides et espacées de 2,5 secondes au plus ; un temps exactement observé
utilise son seul masque. Chaque rapport indique les horizons hors domaine,
les intervalles refusés et le nombre de valeurs observées utilisables. Un
quartet doit conserver ses coordonnées, objets, matériaux, source, ouvertures
et conditions autres que la ventilation.

Pour chaque sonde, le changement est −1, 0 ou +1 selon la disparition,
l'absence de changement ou l'apparition de la classe affectée. Une prédiction
dans le mauvais sens compte comme un faux positif et un faux négatif, même
si elle détecte qu'une variation existe. Les rapports donnent précision,
rappel et F1 de ces changements, globalement et par famille.

Le déplacement du centre de la région affectée fournit une seconde mesure
en mètres. Elle n'est calculée que si les deux régions FDS et les deux régions
prédites sont non vides. La couverture et les prédictions manquantes sont
toujours rapportées : supprimer une fumée prédite ne doit pas améliorer
silencieusement l'erreur de position.

Les scripts vérifient les empreintes des observations FDS et des scores
archivés. Ils ne relancent pas l'inférence. Ces contrôles mesurent la fidélité
au corpus synthétique ; ils ne valident pas la sécurité d'un habitat réel.
