"""Preserve prevention sources, training data, weights and analysis evidence."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ignis.engine import write_json
from ignis.locking import ProcessLock


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    destination = Path(os.getenv("IGNIS_ARCHIVES", "G:/IGNIS-Valley-archives"))
    destination.mkdir(parents=True, exist_ok=True)
    with ProcessLock(root / "runtime/compute.lock"):
        files = []
        for source in [root / "app/data/prevention", root / "runtime/prevention"]:
            if not source.is_dir():
                raise FileNotFoundError(source)
            files.extend(p for p in sorted(source.rglob("*"))
                         if p.is_file() and not p.is_symlink() and p.suffix not in {".lock", ".tmp"})
        for name in ["prevention-step1.zip", "prevention-thermal-source.zip"]:
            if not (root / name).is_file():
                raise FileNotFoundError(name)
            files.append(root / name)
        total = sum(p.stat().st_size for p in files)
        if shutil.disk_usage(destination).free < total*1.1+8*1024**3:
            raise RuntimeError("Archive disk reserve would not be preserved")
        # The code used to train is preserved separately from the final application.
        # The only post-transfer training-module change was learning.py; its exact
        # recorded bytes are still present and checked, rather than reconstructed.
        thermal_meta = json.loads((root / "runtime/prevention/models/thermal-history-forest-v1/metadata.json").read_text(encoding="utf-8"))
        training_code = {}
        with zipfile.ZipFile(root / "prevention-thermal-source.zip") as original:
            for name, expected in thermal_meta["dataset"]["source_hashes"].items():
                normalized = name.replace("\\", "/")
                data = original.read(normalized)
                if hashlib.sha256(data).hexdigest() != expected:
                    data = (root / "app" / normalized).read_bytes()
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError("Exact training source missing: "+normalized)
                training_code["training-code/thermal/"+normalized] = data
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = destination / f"ignis-prevention-v1-{stamp}.zip"
        partial = target.with_suffix(".partial")
        report = {"created_utc": stamp, "archive": str(target), "files": {},
                  "scope": "NASA and complementary sources, both prevention models, thermal campaigns, exact thermal training code and saved analyses; no credentials"}
        try:
            with zipfile.ZipFile(partial, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for p in files:
                    name = p.relative_to(root).as_posix()
                    report["files"][name] = {"bytes": p.stat().st_size, "sha256": digest(p)}
                    archive.write(p, name)
                for name, data in training_code.items():
                    report["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    archive.writestr(name, data)
                archive.writestr("archive-manifest.json", json.dumps(report, ensure_ascii=False, indent=2))
            with zipfile.ZipFile(partial) as archive:
                for name, info in report["files"].items():
                    with archive.open(name) as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                            raise ValueError("Archive verification failed: "+name)
            report.update(sha256=digest(partial), compressed_bytes=partial.stat().st_size,
                          file_count=len(report["files"]), all_entry_sha256_verified=True)
            partial.replace(target)
            write_json(target.with_suffix(".manifest.json"), report)
            summary = {key: value for key, value in report.items() if key != "files"}
            write_json(root / "runtime/prevention-archive-verification.json", summary)
            print(json.dumps(summary), flush=True)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


if __name__ == "__main__":
    main()
