# Champ de vitesse et retouches des poids

Le réseau reçoit les conditions aux évents, les équipements et les matériaux,
pas un champ de vitesse intérieur complet. Il peut apprendre une dépendance
implicite à l'écoulement ; cette capacité doit être mesurée. Atténuer certains
canaux ou connexions ne lui fournit pas une nouvelle observation physique.
Ces interventions sont des expériences d'ablation, pas des corrections
physiques démontrées par l'analyse des seuls poids.

Le premier benchmark externe de retouches a été consulté en lecture seule ;
les preuves sont dans `evidence/incidents/iss-poc-vent/external-ablation-readonly/`.
Il a choisi une atténuation uniforme de 25 % des poids d'entrée de ventilation.
Sur l'ancien test v2, après recalibration identique des seuils, le rappel chaleur
passe de 0,524 à 0,516 et le rappel fumée de 0,627 à 0,621. Les intervalles
bootstrap des deux variations de F1 incluent zéro. Cette variante n'a pas été
déployée. Ce résultat ne teste pas les nouvelles ablations ciblées proposées
par Thomas et ne change pas le protocole de sélection fixé ci-dessus.

Une future entrée de vitesse devra être disponible à l'inférence : par exemple
un écoulement sans incendie calculé à partir de la scène et des bouches. Fournir
le champ FDS pendant l'incendie introduirait une information indisponible avant
le phénomène à prédire. Aucun tel canal n'a été ajouté à cette adaptation.
