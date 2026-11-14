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
```

Le serveur de développement utilise le port 5173 et transmet `/api` et
`/assets/scenes` à `http://127.0.0.1:8765`. Un fichier `.env.local` peut définir
`IGNIS_API_TARGET` pour un tunnel de développement. En livraison, FastAPI sert
`web/dist` et les assets sur le port 8765. Ne pas exposer le serveur Vite en production.

## Fonctionnalités

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

Voir `../docs/CONTRACTS.md`. Contrats opérationnels utilisés :

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
