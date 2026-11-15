"""Archive the completed isolated fit and its hash-matched training sources."""

import hashlib
import json
import zipfile
from pathlib import Path

APP = Path("E:/IGNIS-Valley-dev/app")
BASE = Path("E:/IGNIS-Valley-dev/runtime/iss-poc/20261115")
FIT = BASE / "fit1-retry"
ARCHIVE = BASE / "fit1-retry.zip"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


exit_record = json.loads((BASE / "fit1-retry-exited.json").read_text(encoding="utf-8"))
assert exit_record["exit_code"] == 0, "Cannot publish an incomplete ISS fit"
report = json.loads((FIT / "report.json").read_text(encoding="utf-8"))
assert sha(FIT / "weights.pt") == report["model"]["weights_sha256"]
sources = json.loads((FIT / "sources.json").read_text(encoding="utf-8"))
for relative, digest in sources.items():
    assert sha(APP / relative) == digest, "Training source changed: " + relative
files = sorted(path for path in FIT.rglob("*") if path.is_file())
assert not any(path.is_symlink() for path in files)
with zipfile.ZipFile(ARCHIVE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for path in files:
        output.write(path, "fit1-retry/" + path.relative_to(FIT).as_posix())
    for relative in sources:
        output.write(APP / relative, "source/" + relative)
    for name in ("fit1-retry.stdout.log", "fit1-retry.stderr.log", "fit1-retry-exited.json", "launch-fit1-retry.py"):
        output.write(BASE / name, "execution/" + name)
manifest = {
    "archive": str(ARCHIVE), "sha256": sha(ARCHIVE), "bytes": ARCHIVE.stat().st_size,
    "fit_file_count": len(files), "uncompressed_fit_bytes": sum(path.stat().st_size for path in files),
    "model_sha256": report["model"]["weights_sha256"],
    "dataset_sha256": report["model"]["dataset_sha256"], "source_count": len(sources),
}
(BASE / "fit1-retry-archive.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest), flush=True)
