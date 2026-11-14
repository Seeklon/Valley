Revue indépendante finale — 14 novembre 2026

Périmètre : gestion des processus Windows (`backend/ignis/windows_process.py`), lanceurs `start-ignis.ps1` et `stop-ignis.ps1`, tests associés, et intégration Codex dans `backend/ignis/knowledge.py` : isolation, arrêt des descendants, traitement des documents comme données, citations et synthèse de secours. Aucun nouveau constat P1/P2 ne reste ouvert dans ce périmètre.

Les trois constats relevés ont été corrigés :

- **Fermeture du Job Codex** : un `finally` imbriqué garantit sa fermeture même si `kill()` ou `wait()` échoue.
- **Validation des citations** : références inconnues ou malformées, chiffres hors citations et paragraphes sans citation sont rejetés. Les séparateurs de paragraphes LF, CRLF et contenant des espaces sont couverts.
- **Démarrages concurrents** : le bootstrap acquiert un verrou Windows exclusif, non héritable et conservé jusqu’à la sortie du processus, avant l’identité, l’archivage et les publications d’état. Un second bootstrap ne peut plus écraser l’identité du propriétaire.

Preuves examinées et résultats transmis :

- **7 tests réels Windows réussis**, sans échec ni test ignoré : concurrence avant/après publication, récupération après crash, arrêt des enfants et descendants, crash avant affectation au Job enfant, chemins avec espaces, idempotence et refus d’une identité altérée. Rapport : [windows-lifecycle-tests.xml](windows-lifecycle-tests.xml). L’exécution a été réalisée par l’agent frontend ; son XML a été relu indépendamment.
- **12 tests knowledge réussis**, résultat communiqué par l’agent principal, dans `tests/test_knowledge.py`. En complément, sept vérifications locales du seul validateur, avec réponses simulées en mémoire, ont confirmé les rejets attendus et une voie valide, sans appel modèle.
- La [capture Codex finale](codex-verification.json) utilise `gpt-6.1-sol` et respecte le contrat de citations sans chiffres hors identifiants. Aucun appel Ollama n’a été relevé dans le backend ou le lanceur examinés.

Limites : le contrôle des citations est **syntaxique** ; il ne démontre ni l’exactitude scientifique de chaque affirmation, ni son adéquation sémantique à la source citée. Cette limite est explicitement affichée avec la synthèse, et les faits archivés restent séparés. La capture Codex est une preuve de réponse réussie, pas une trace adversariale exhaustive des outils. Cette contrelecture n’a effectué aucune action Windows ni modification de code ; seul ce rapport a été ajouté.
