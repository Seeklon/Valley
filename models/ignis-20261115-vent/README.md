# Modèle IGNIS chaleur/fumée — version ventilation

[Télécharger le kit Python autonome](ignis-model-20261115-vent.zip) : 1 798 192
octets. Ce fichier est identique au paquet livré le 15 novembre 2026. Il contient
les poids PyTorch, le code d'inférence, un exemple de scène et les rapports.

Depuis ce dossier, avec Python 3.11 ou 3.12 et un environnement virtuel dédié :

```bash
python -m zipfile -e ignis-model-20261115-vent.zip ignis-model
cd ignis-model/model
python -m pip install -r requirements.txt
python predict.py --output prediction.npz
```

L'exemple exécute réellement le réseau sur CPU, sans FDS ni entraînement. Il
produit cinq instants × 1 536 positions × deux scores chaleur/fumée. Le fichier
de sortie doit être nouveau. Les poids décompressés sont également conservés
dans [`evidence/incidents/iss-poc-vent/model/fit1/weights.pt`](../../evidence/incidents/iss-poc-vent/model/fit1/weights.pt).

- Réseau U-Net 3D : 379 046 paramètres, dont 376 834 entraînables.
- SHA256 du ZIP : `b7e1da6b6e97f2f4bc4c74fe092acbc5eca19fd27f878a227fb146ea1fb892e7`.
- SHA256 des poids : `ce0ffc80e51d9be2da94fc50f098fc4ac3c223203d09c8908ea8bbd6f4eff292`.
- [Entraînement et résultats](../../docs/ISS_POC_VENT_MODEL.md).
- [Vérification CPU réelle du kit livré](../../evidence/incidents/iss-poc-vent/model-kit-verification.json).

La source électrique est imposée. Les scores sont des classes approximant
FDS, pas des températures, concentrations ou probabilités d'allumage. Aucune
validation expérimentale NASA n'est revendiquée. La démo web utilise les
216 inférences enregistrées et vérifiées du même modèle, fournies séparément
dans [`data/predictions/ignis-20261115-vent/`](../../data/predictions/ignis-20261115-vent/).
