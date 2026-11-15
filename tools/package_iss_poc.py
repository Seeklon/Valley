"""Package verified spatial predictions, a standalone viewer and CPU inference.

No simulation, training, publishing or remote mutation is performed here.
The output directory must be new; each included file is listed by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(args):
    report = json.loads(args.verification.read_bytes())
    index_path = args.export / "index.json"
    index = json.loads(index_path.read_bytes())
    if not all(report.get(k) for k in ("verified", "fds_observations_verified", "model_files_verified")):
        raise ValueError("Require independent export, FDS and model-file verification")
    if sha(index_path) != report["index_sha256"]:
        raise ValueError("The verified index changed")
    if sha(args.model_dir / "weights.pt") != index["model"]["weights_sha256"]:
        raise ValueError("Weights differ from the displayed predictions")
    model_report = json.loads((args.model_dir / "report.json").read_bytes())
    if model_report["model"]["weights_sha256"] != index["model"]["weights_sha256"]:
        raise ValueError("Inference report points to different weights")
    sources = json.loads((args.model_dir / "sources.json").read_bytes())
    for name, expected in sources.items():
        if name.startswith("backend/") or name == "tools/remote/iss_poc_model.py":
            if sha(ROOT / name) != expected:
                raise ValueError("Inference source changed since fitting: " + name)
    verified = {r["id"]: r for r in report["cases"]}
    if len(verified) != len(index["cases"]) or set(verified) != {e["id"] for e in index["cases"]}:
        raise ValueError("Export population differs from the verification")
    cases = []
    for entry in index["cases"]:
        relative = entry["url"].removeprefix("/poc/iss/")
        path = (args.export / relative).resolve()
        if not path.is_relative_to(args.export.resolve()) or sha(path) != verified[entry["id"]]["sha256"]:
            raise ValueError("Replay changed after verification: " + entry["id"])
        cases.append((path, relative))

    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)

    def copy(source, relative):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def write(relative, value):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    for name in ("package-lock.json", "tsconfig.json", "index.html"):
        copy(ROOT / "web" / name, "frontend/" + name)
    package = json.loads((ROOT / "web/package.json").read_bytes())
    package["scripts"] = {
        key: value for key, value in package["scripts"].items()
        if key in ("dev", "build", "preview", "test", "format", "format:check")
    }
    package["scripts"]["test:browser"] = "node tools/iss-poc-check.mjs"
    write("frontend/package.json", json.dumps(package, indent=2) + "\n")
    copy(ROOT / "web/public/favicon.svg", "frontend/public/favicon.svg")
    source_files = [
        "components/IssPocView.tsx", "iss-poc.ts", "iss-poc.test.ts", "iss-poc.css",
        "data.ts", "types.ts", "hotspot-poc.ts",
    ]
    source_files += [p.name for p in (ROOT / "web/src").glob("iss-station*") if p.is_file()]
    for name in source_files:
        copy(ROOT / "web/src" / name, "frontend/src/" + name)
    copy(ROOT / "web/tools/iss-poc-check.mjs", "frontend/tools/iss-poc-check.mjs")
    write("frontend/vite.config.ts", "import { defineConfig } from 'vite';\n"
          "import react from '@vitejs/plugin-react';\nexport default defineConfig({ plugins: [react()] });\n")
    write("frontend/src/main.tsx", "import React from 'react';\n"
          "import ReactDOM from 'react-dom/client';\n"
          "import IssPocView from './components/IssPocView';\n"
          "import '@fontsource/dm-sans/latin-400.css';\n"
          "import '@fontsource/dm-sans/latin-500.css';\n"
          "import '@fontsource/dm-sans/latin-600.css';\n"
          "import './standalone.css';\n"
          "ReactDOM.createRoot(document.getElementById('root')!).render(\n"
          "  <React.StrictMode><IssPocView /></React.StrictMode>,\n);\n")
    write("frontend/src/standalone.css", "* { box-sizing: border-box; }\n"
          "body { margin: 0; background: #0b121c; font-family: 'DM Sans', sans-serif; }\n"
          "button, input, select { font: inherit; }\n")
    copy(index_path, "frontend/public/poc/iss/index.json")
    for source, relative in cases:
        copy(source, "frontend/public/poc/iss/" + relative)

    modules = ["__init__.py", "provenance.py", "ml/__init__.py", "ml/incidents.py", "ml/spatial_network.py"]
    modules += ["physics/" + name for name in ("__init__.py", "compiler.py", "incidents.py", "materials.py", "parser.py")]
    for name in modules:
        copy(ROOT / "backend/ignis" / name, "model/backend/ignis/" + name)
    copy(ROOT / "tools/remote/iss_poc_model.py", "model/iss_poc_model.py")
    for name in ("weights.pt", "frozen-selection.json", "report.json", "sources.json", "inference-benchmark.json"):
        copy(args.model_dir / name, "model/" + name)
    for name in ("scene.json", "config.json", "provenance.json"):
        copy(args.example / name, "model/example/" + name)
    write("model/requirements.txt", "numpy==2.2.5\ntorch==2.7.0\n")
    write("model/predict.py", '''"""Run actual CPU inference from scene and conditions; never launches FDS."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "backend"))
from iss_poc_model import ISSPredictor

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--scene", type=Path, default=root / "example/scene.json")
parser.add_argument("--config", type=Path, default=root / "example/config.json")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise FileExistsError("Choose a new output file")
torch.set_num_threads(4)
metadata = json.loads((root / "report.json").read_bytes())["model"]
model = ISSPredictor(root / "weights.pt", expected_sha256=metadata["weights_sha256"])
scene = json.loads(args.scene.read_bytes())
config = json.loads(args.config.read_bytes())
result = model.predict_scene(scene, config, times=[0, 5, 10, 20, 30])
args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("xb") as stream:
    np.savez_compressed(stream, **{k: result[k] for k in
        ("time_s", "sample_positions_m", "scores", "predicted_mask", "valid_mask")})
print(json.dumps({"weights_sha256": model.weights_sha256,
                  "shape": list(result["scores"].shape),
                  "outputs": result["output_channels"],
                  "semantics": result["score_semantics"],
                  "output": str(args.output)}, indent=2))
''')
    for name in ("ISS_POC.md", "ISS_POC_DATA.md", "ISS_POC_MODEL.md", "ISS_POC_INTEGRATION.md",
                 "RECADRAGE_SOURCES_NASA.md", "NASA.md"):
        copy(ROOT / "docs" / name, "docs/" + name)
    for path in sorted((ROOT / "docs").glob("*POC*V2*.md")):
        copy(path, "docs/" + path.name)
    for path in sorted((ROOT / "docs").glob("ISS_POC_VENT*.md")):
        copy(path, "docs/" + path.name)
    copy(args.verification, "evidence/export-verification.json")
    write("README.md", '''# IGNIS — kit d'intégration du POC spatial

Ce kit contient les poids sélectionnés, une fonction d'inférence Python et une
vue React/Three autonome avec les prédictions enregistrées et leurs références
FDS. Les géométries et champs partagent le même repère physique en mètres.

## Lancer la vue autonome

Prérequis : Node.js 22.13 ou plus récent dans la branche 22, ou Node.js 24.
Dans `frontend/`, exécuter `npm ci`, puis `npm run dev -- --host 127.0.0.1`.
Le build se fait avec `npm run build`. Servir le dossier `dist` via HTTP ;
ne pas ouvrir index.html en file://. Aucune API de calcul n'est requise pour
la relecture. Les polices et données sont locales après installation.

## Brancher la maquette

Copier les composants et leurs imports, puis `public/poc/iss/`. Monter
`IssPocView` lors de l'entrée dans un module, ou réutiliser `createIssPocOverlay`
dans une scène Three existante. Voir `docs/ISS_POC_INTEGRATION.md`.
La correspondance géométrie/matériaux/ventilation est contrôlée : ne pas étirer
ces champs sur un GLB ressemblant mais physiquement différent.

## Exécuter réellement le réseau

Python 3.11 ou 3.12, depuis `model/` : installer `requirements.txt` dans un
environnement dédié, puis `python predict.py --output prediction.npz`.
Sur le PC de Thomas, le Python PyTorch existant peut être réutilisé.
Cet exemple réalise une nouvelle inférence CPU, sans lancer FDS ni apprendre.
Le navigateur, lui, lit les inférences enregistrées. L'exemple de géométrie
provient de la première campagne, comme l'indique son fichier de provenance.

Les scores classent chaleur et présence de suie ; ils ne sont ni des
températures, ni des densités, ni des probabilités de départ de feu. La source
électrique est imposée. Données synthétiques et géométries simplifiées ; aucune
validation expérimentale NASA ou certification de sécurité revendiquée.

`artifact.json` contient l'empreinte de chaque fichier et identifie les poids
et données de la livraison. Le ZIP peut être décompressé dans un dossier neuf.
''')
    files = {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob("*")) if p.is_file()}
    metadata = {"model_id": index["model"]["id"], "weights_sha256": index["model"]["weights_sha256"],
                "index_sha256": report["index_sha256"], "case_count": len(cases), "files": files}
    write("artifact.json", json.dumps(metadata, indent=2) + "\n")
    if not args.no_zip:
        archive = destination.with_suffix(".zip")
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
            for path in sorted(destination.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(destination))
        metadata = {k: v for k, v in metadata.items() if k != "files"}
        metadata.update(archive=str(archive), archive_sha256=sha(archive), archive_bytes=archive.stat().st_size)
        archive.with_suffix(".manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({k: v for k, v in metadata.items() if k != "files"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=ROOT / "web/public/poc/iss")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--example", type=Path, default=ROOT / "evidence/incidents/iss-poc/inference-example")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-zip", action="store_true")
    build(parser.parse_args())
