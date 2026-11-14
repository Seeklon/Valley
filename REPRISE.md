# Reprise compacte — IGNIS 3D / Valley

Mis à jour : 14 novembre 2026. Goal actif ; aucun livrable final encore validé.

## À lire d'abord

1. PLAN.md : objectif et critères figés, ne pas réduire le périmètre.
2. État Git et preuves d'exécution réelles.
3. Ce fichier pour localiser le travail ; il ne remplace pas les vérifications.

## Demande persistante

Application web utilisable, modèles réellement entraînés et préchargés, simulation
prédictive avec variables et scènes différentes, scène Blender détaillée,
visuels fréquents et communication détaillée en français. Windows calcule ; VPS
coordonne et conserve le plan. Utiliser git@github.com:Seeklon/Valley.git.

## État actuel

- Clone : /home/platform-admin/projects/Valley.
- Branche : codex/ignis-3d-lab ; point de départ 11d1d76 (seul .gitignore).
- Plan écrit ; implémentation à démarrer.
- Ancien démonstrateur : /home/platform-admin/projects/ignis-lab, moteur 2D non
  calibré ; ne pas présenter ses sorties comme données NASA.
- Méthode lue dans /home/platform-admin/repositories/Agentic : AGENTS.md,
  .agents/core.md, task-router.md, policies/collaboration.md et
  skills/software-change/SKILL.md. Délégation des lots complexes autorisée par
  ces instructions. Aucun besoin de modifier Agentic.
- Sites : workflow local uniquement, dépôt et hébergement Windows imposés.
  Référence de preview local lue. Pas de nouvelle publication Sites prévue.

## Calcul Windows (localisateurs, sans secrets)

Le poste DESKTOP-M4HKR86 est visible sur Tailscale et Ollama répond en HTTPS.
Le canal SSH existe déjà ; sa configuration privée est localisée dans
/home/platform-admin/repositories/weight-surgeon/.remote-pc.json et sa méthode
dans docs/REMOTE_COMPUTE.md de ce dépôt. Lire les paramètres sans les commiter.
Réutiliser la confiance SSH existante ; créer un dossier Valley distinct.
Ne pas modifier Weight Surgeon, ses environnements, modèles ou jobs.
Référence historique : RTX 4070 Ti 12 Go, Python 3.11 ; revérifier l'état réel.

## Sources déjà récupérées

/tmp/ignis-challenge-details.html et /tmp/ignis-challenge-resources.html contiennent
le contenu officiel extrait des données Next.js de la page (l'outil web échouait).
/tmp/ignis-PSI-{25,26,62,98}.json : métadonnées PSI.
/tmp/ignis-PSI-{25,26,98}-table.csv : tableaux récupérés via l'API publique.
Les URLs et DOI à citer sont dans PLAN.md. Pas de modèles entraînés sur ces données
ni de validation expérimentale réalisés à ce stade.

## Prochaines actions

Inventorier Windows en lecture seule, créer le dossier de travail séparé, préparer
les contrats d'interface puis déléguer Blender et frontend dans des fichiers
distincts. Vérifier/installer les outils nécessaires sur Windows. Conserver les
commandes, rapports et premières images. Continuer vers tous les jalons du plan.
