# Contrelecture de la livraison ventilation — 15 novembre 2026

Revue indépendante par `iss_dataset`, transmise au coordinateur après extraction
de l'archive finale. Lecture seule des preuves et du code ; aucun nouvel
entraînement, calcul Windows ou ajustement à partir du test.

**Conclusion : aucun blocage de promotion ML pour le POC.** La publication sur
dev reste conditionnée au build et au contrôle de la livraison effective.

- Les neuf conditions de sélection ont été recalculées depuis `report.json`
  et `validation-step-005000.json`. Elles passent ; l'étape 5 000 maximise le
  composite parmi les checkpoints admissibles. Poids, index audité et sources
  concordent avec les empreintes archivées.
- Protocole figé à 14:49 UTC ; sélection figée à 15:08:55 UTC, puis ouverture
  du nouveau test. L'ancien test V2 n'est pas chargé par ce trainer.
- Ancien F1 macro validation : 0,5002 → 0,6039 ; composite : 0,3230 → 0,4325 ;
  réponse ventilation macro : 0,1153 → 0,2675. Les douze contrôles de validation
  et les six contrôles de test à 0 W ne produisent aucun faux positif.
- Test réservé : F1 chaleur 0,388 → 0,553, fumée 0,393 → 0,579, face au V2
  recalibré selon la même procédure de validation.
- Les faux positifs chaleur augmentent de 3 841 à 4 971, malgré un rappel
  passant de 0,347 à 0,601 et une précision de 0,439 à 0,511. Pour la fumée,
  précision et rappel progressent, les faux positifs diminuent de 9 898 à 9 662.
  Ces décomptes portent sur des observations de sondes au cours du temps,
  pas sur des incendies indépendants.
- Le gain n'est pas uniforme : chaleur sur racks centraux, F1 test
  0,519 → 0,512 et précision 0,474 → 0,418. Sa réponse appariée reste faible
  (F1 chaleur/fumée 0,154/0,207), et la couverture du déplacement du centroïde
  chaleur baisse de 30/35 à 29/35. Les conditions agrégées restent satisfaites.
- Le benchmark réel du modèle candidat est présent. La démonstration concerne
  de nouvelles dispositions de six familles connues, sous source imposée :
  aucune preuve de généralisation à une station arbitraire, de probabilité de
  départ de feu ou de validation expérimentale NASA.

Le coordinateur a également vérifié les 216 replays et les comparaisons
absolues/appariées contre les observations FDS, puis inspecté les captures 3D
du quartet réel et les preuves des bascules de ventilation. Aucun de ces
contrôles ne modifie les poids ou seuils après lecture du test.

Preuves : `export-verification.json`, `model/fit1/report.json`,
`model/fit1/frozen-selection.json`, `browser-train-quartet/browser-report.json`
et `browser-v2-compat/browser-report.json` dans ce dossier.
