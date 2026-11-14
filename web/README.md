# IGNIS 3D — interface web

Application React / TypeScript strict / Three.js. Les polices sont embarquées ;
aucune CDN n'est nécessaire pour lancer l'application. Les fichiers GLB et les
résultats sont servis par l'API de même origine.

```bash
npm ci
npm run dev
npm run build
npm test
npx playwright install chromium
npm run test:browser
npm run test:prediction
node tools/prevention-check.mjs
```

Le serveur de développement utilise le port 5173 et transmet `/api` et
`/assets/scenes` à `http://127.0.0.1:8765`. Un fichier `.env.local` peut définir
`IGNIS_API_TARGET` pour un tunnel de développement. En livraison, FastAPI sert
`web/dist` et les assets sur le port 8765. Ne pas exposer le serveur Vite en production.

## Fonctionnalités

- Accueil **Prévention**, distinct du Laboratoire : géométrie sans foyer,
  composants hypothétiques sélectionnables dans la scène et la liste, analyse
  d'échauffement avant feu, conclusions expérimentales classées et export ZIP.
- Scènes issues de `/api/scenes`, GLB interactif, sélection par `object_id`,
  contrôle des éléments `userData.cutaway`, capteurs et point d'allumage.
- Physique et prédiction via `POST /api/runs`, suivi non bloquant, annulation et
  récupération du dernier essai après rechargement. Une interruption réseau ne
  relance jamais automatiquement un calcul.
- Paramètres atmosphère, ventilation, matériau, source, gravité, puissance,
  durée et seed. Le chauffage résistif I²R utilise exclusivement la combustion
  couplée ; les arcs et batteries ne sont pas couverts.
- Champs réels de température, oxygène, fumée et vitesse, lecture temporelle,
  courbes, référence conservée, écarts et export du serveur.
- Bibliothèques de scènes, modèles effectivement chargés et sources NASA.
- Interprétation NASA via l'API : question, synthèse, faits cités, classement
  documentaire explicable, limites et méthode de génération réellement utilisée.
- Campagnes de 2 à 100 essais, choix des scènes, plages physiques, suivi,
  annulation et export des résultats disponibles, y compris après échec ou
  annulation, lorsque le serveur annonce cette capacité.
- États d'indisponibilité, erreur GLB avec proxy géométrique explicite, absence
  de mesure et contrôle de domaine sans faux résultats.

## Contrats attendus

Voir `../docs/CONTRACTS.md` et `../docs/PREVENTION_API.md`. Contrats opérationnels utilisés :

- `/api/health`: `{status, worker_available, capabilities:{physics,prediction,source_models}}`.
- `/api/scenes`: `{schema_version,materials,scenes}`. Catalogue dynamique, incluant
  `habitat`, `cargo`, `crossflow` et `soyuz` dès leur disponibilité. `asset_url`
  doit être une URL de même origine.
- `/api/models`: `{models:[{id,name,status,loaded,domain,metrics,...}]}`. Un modèle
  est utilisable seulement si `loaded === true`. Le domaine peut contenir des
  listes de catégories, des intervalles numériques `[min,max]` ou `{min,max}`.
  Le format du registre `scene_ids`, `materials`, `gravity_values`, `source_model`
  et `ranges` est aussi pris en charge. `gravity_values` désigne une liste de
  gravités discrètes ; aucune gravité intermédiaire n'est implicitement admise.
  Un identifiant de modèle devenu indisponible bloque l'envoi jusqu'à sélection
  d'un modèle chargé. `kind="spatial_mlp"` distingue les prédictions de champs
  3D de `kind="scalar_forest"`, qui fournit uniquement des métriques.
  Le serveur conserve l'autorité sur le contrôle du domaine.
- `/api/sources`: `{sources:[{id,name|title,url,description,doi,observations,...}]}`.
- `/api/runs`: le contrat de `RunConfig` et les champs `ignition_kind`,
  `current_a`, `resistance_ohm`, `model_id` facultatif. Le champ `progress` des
  jobs est normalisé sur `[0,1]`.
- `result.frames`: `shape:[nx,ny,nz]`, `bounds_m:[x,y,z]`, champs aplatis avec z
  variant le plus vite. Les scalaires acceptent `null`. `valid_mask:boolean[]`
  exclut les cellules solides ; `sample_positions_m:Vec3[]` précise la position
  physique réelle d'observation si elle diffère du centre du voxel. Les
  vitesses ont trois composantes physiques par cellule. Conversion graphique :
  `(x,y,z)` physique → `(x,z,-y)` Three.js.
- `/api/campaigns`: `POST` avec `{count,seed,scene_ids,base_config,ranges}`,
  `base_config.mode="physics"`. Les plages autorisées sont `airflow_m_s`,
  `oxygen_percent`, `ignition_power_w`, `gravity_g`; chacune est `[min,max]`.
  La puissance est fixe en résistif, déterminée par I²R. `GET /{id}` fournit
  `status,progress,completed_runs,failed_runs,cancelled_runs,total_runs,run_ids,message`.
  `POST /{id}/cancel` annule et `GET /{id}/export` télécharge les résultats.
- `/api/insights`: `POST {config,question}` puis
  `{summary,method,model,sources:[{id,name,url,score,reasons}],facts:[{text,source_id}],limits}`.
  La requête est annulable côté navigateur et dispose de 120 secondes. Les
  scores documentaires ne sont jamais présentés comme des scores de sécurité.

## Interprétation visuelle

Les champs sont les observations spatiales conservées dans chaque frame. La
lecture sélectionne la frame la plus proche et affiche son temps réel, sans
interpolation présentée comme une mesure. Les courbes conservent les observations
absentes comme discontinuités. Les cartes indiquent l'instant de la mesure.

La vue température affiche les cellules ≥ 26 °C avec une échelle 26–800 °C
(saturation au-delà). La fumée utilise l'échelle relative à son maximum dans la
frame et masque les concentrations < 2,5 % de ce maximum ou < 1e-10 kg/m³. Les
vecteurs sont sous-échantillonnés pour la lisibilité, sans fabrication d'un
écoulement supplémentaire. Le bouton « Coupe X centrale » filtre une tranche
centrée dans la direction X. Les repères de capteur sont des annotations de
géométrie, pas des mesures.

Les scènes de la bibliothèque affichent le rendu Blender fourni par `preview_url`.
En son absence, un schéma illustratif est explicitement identifié. Le laboratoire
utilise le GLB réel ; un échec de chargement affiche les boîtes du proxy du catalogue
avec une bannière explicite.

La comparaison des métriques est limitée à l'intervalle temporel commun. Les
instants des observations conservées restent visibles. Le changement de
paramètres conserve les résultats de l'essai précédent avec un avertissement ;
le changement de scène réinitialise les résultats affichés.

Les tests couvrent le repère physique, l'aplatissement des voxels, les valeurs
absentes, les masques de solides, la continuité des courbes et la sélection du
domaine d'un modèle chargé. La vérification navigateur sur le backend réel
reste nécessaire pour prouver le parcours complet.

`npm run test:browser` vérifie le catalogue réel, les GLB, la sélection d'objets,
la navigation, le registre réel des modèles, les observations NASA filtrées,
la réponse d'interprétation si disponible, les capacités des campagnes et la vue mobile. Il n'utilise aucun mock réseau
et n'exécute pas de calcul physique. Les captures et le rapport sont écrits dans
`artifacts/` (ignoré par Git). `IGNIS_BROWSER_URL` change l'URL cible et
`IGNIS_BROWSER_PATH` permet un exécutable Chromium existant.
`IGNIS_EXPECT_INSIGHT_METHOD=codex_grounded_in_nasa_evidence` exige la réponse
Codex sans accepter silencieusement une autre méthode.

`npm run test:prediction` exige deux modèles réellement chargés : réseau spatial
et forêt scalaire. Il lance leurs prédictions sur Soyouz, vérifie la lecture des
champs, la comparaison, un téléchargement ZIP, le refus hors domaine côté
interface et API, la restauration après rechargement, les tableaux d'évaluation
et l'affichage mobile. Il n'exécute aucune simulation CFD et n'appelle aucun
modèle de langage. `IGNIS_BROWSER_SCENE` remplace Soyouz par une autre scène du
domaine autorisé. Le rapport complet `artifacts/prediction-verification.json`
conserve les configurations, identifiants et provenances de chaque essai réel.

Le réseau spatial est présenté comme une prévisualisation exploratoire dans le
laboratoire et la bibliothèque : il ne contraint pas la cohérence entre moyenne,
maximum et valeurs du champ. Les décomptes d'incohérences de test sont affichés
lorsqu'ils sont publiés dans `metrics.test.consistency` ; les valeurs prédites
ne sont pas corrigées dans le navigateur.

Le rendu 3D est actualisé à la demande ; un tableau de bord immobile ne relance
pas en continu des centaines de draw calls. Les textures et géométries sont
libérées lors du changement de scène ou de vue.

## Prévention avant allumage

Les bornes, valeurs initiales et composants viennent de `/api/prevention/catalog`.
« Analyser le scénario » transmet la configuration à `/api/prevention/analyze` ;
le navigateur ne fabrique aucun résultat. Les paramètres de prévention sont
indépendants du dernier essai du Laboratoire. La session de prévention, ses
résultats et sa référence sont conservés pendant la navigation entre onglets.
Le rechargement de la page revient à une scène non évaluée, sans restaurer un
foyer du Laboratoire. Annuler l'attente coupe la requête côté navigateur ; cela
ne prétend pas arrêter le calcul déjà engagé sur Windows.

La couleur concerne uniquement les marqueurs de composants : délai estimé dans
l'horizon, au-delà, instant estimé atteint, ou inconnu gris. Aucun risque n'est
interpolé dans la cabine. Le gris couvre notamment les mécanismes non pris en
charge et les conditions hors protocole. Un délai au-delà de l'horizon n'est
jamais appelé « faible risque ». Un instant estimé atteint n'est pas une détection.
Les emplacements et composants sont des hypothèses d'étude, pas un câblage
qualifié de Soyouz.

Le délai d'allumage depuis la mise sous courant est un résultat appris sur un
protocole expérimental précis ; il reste distinct des courbes thermiques locales.
L'interface ne convertit ni un délai, ni une fraction pyrolysée en probabilité de
feu. `interval=null` affiche « Non quantifiée ». L'historique simulé utilise
uniquement les points `time_s <= observation_cutoff_s` ; projection physique et
prévision ML sont tracées séparément après cet instant. Les séries s'arrêtent
à leur dernier point réel, sans prolongement lorsque le modèle thermique sort
de son domaine. Aucun capteur réel n'est connecté.

Le mode « Relecture simulée » permet de choisir l'instant observé ; une nouvelle
analyse explicite est nécessaire pour recalculer le scénario. La somme de
l'instant et de l'horizon ne peut pas dépasser la durée. Une référence est un
résultat du serveur conservé, jamais une courbe factice. Un écart de délai n'est
calculé que pour un même composant, scène, instant, horizon, critère et modèle
dans le même domaine. Une modification des paramètres garde un avertissement
sur la provenance des résultats encore affichés.

Le panneau `/api/prevention/evidence` conserve l'ordre documentaire du serveur,
les conclusions, motifs d'applicabilité, conditions, qualité des preuves,
localisateurs et limites. Ce rang ne classe pas le danger des composants.
Une analyse conserve son instantané de preuves par composant ; l'interface
affiche ces preuves figées avec les résultats correspondants, même lorsqu'un
changement de paramètres reste en attente de recalcul. Le classement d'un fil
NiCr/LDPE n'est donc jamais substitué à celui d'une batterie ou d'un autre matériau.
L'explication `/api/prevention/interpret` est associée à une analyse et un
composant précis ; la méthode réelle, Codex ou synthèse extractive, est affichée.

`node tools/prevention-check.mjs` exige les deux modèles de prévention chargés
sur le vrai backend. Le parcours vérifie l'accueil, les bornes serveur, la
sélection 3D par projection des coordonnées physiques, les délais réels, la
frontière temporelle des courbes, l'absence d'extrapolation, les conclusions et
l'explication réelles, la comparaison, un export ZIP, le hors domaine, la
batterie inconnue, la navigation indépendante du Laboratoire et le mobile.
Il exécute de courts calculs thermiques via l'API Windows, jamais de CFD ni
d'entraînement. `IGNIS_EXPECT_PREVENTION_METHOD` peut exiger une méthode exacte.
Rapport et captures dans `artifacts/prevention-verification.json` et `artifacts/`.
