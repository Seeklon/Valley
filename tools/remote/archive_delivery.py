"""Archive the frozen Windows pilot and model weights, verifying every ZIP entry."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ignis.locking import ProcessLock


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    destination = Path(os.getenv("IGNIS_ARCHIVES", "G:/IGNIS-Valley-archives"))
    destination.mkdir(parents=True, exist_ok=True)
    with ProcessLock(root / "datasets/pilot-v2/generation.lock"), ProcessLock(root / "runtime/compute.lock"):
        files = []
        for source in (root / "datasets/pilot-v2", root / "runtime/models"):
            if not source.is_dir():
                raise FileNotFoundError(source)
            files.extend(path for path in sorted(source.rglob("*"))
                         if path.is_file() and not path.is_symlink() and path.suffix != ".lock")
        total = sum(path.stat().st_size for path in files)
        if not files or shutil.disk_usage(destination).free < total * 1.05 + 8 * 1024**3:
            raise RuntimeError("Missing inputs or insufficient archive disk space")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_path = destination / f"ignis-pilot-v2-models-{stamp}.zip"
        partial = archive_path.with_suffix(".partial")
        report = {"created_utc": stamp, "source_root": str(root), "archive": str(archive_path),
                  "file_count": len(files), "uncompressed_bytes": total, "files": {},
                  "scope": "96-run pilot and two trained models; installed software and credentials excluded"}
        try:
            with zipfile.ZipFile(partial, "x", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
                for index, path in enumerate(files):
                    relative = path.relative_to(root).as_posix()
                    report["files"][relative] = {"bytes": path.stat().st_size, "sha256": digest(path)}
                    archive.write(path, relative)
                    if (index + 1) % 500 == 0:
                        print("ARCHIVED", index + 1, "of", len(files), flush=True)
                archive.writestr("archive-manifest.json", json.dumps(report, ensure_ascii=False, indent=2))
            with zipfile.ZipFile(partial) as archive:
                for name, entry in report["files"].items():
                    with archive.open(name) as handle:
                        if hashlib.file_digest(handle, "sha256").hexdigest() != entry["sha256"]:
                            raise ValueError("Archive content mismatch: " + name)
            report.update(sha256=digest(partial), compressed_bytes=partial.stat().st_size,
                          all_entry_sha256_verified=True)
            partial.replace(archive_path)
            archive_path.with_suffix(".manifest.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            summary = {key: value for key, value in report.items() if key != "files"}
            (root / "runtime/archive-verification.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


if __name__ == "__main__":
    main()
