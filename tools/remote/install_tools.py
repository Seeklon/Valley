"""Run on Windows: download verified official portable tools into this project."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("IGNIS_HOME", "E:/IGNIS-Valley"))
PACKAGES = [
    {"name": "Blender", "version": "4.5.9", "file": "blender-4.5.9-windows-x64.zip",
     "url": "https://download.blender.org/release/Blender4.5/blender-4.5.9-windows-x64.zip",
     "sha256": "41da973b9bf95bb312cbeff4d1982feb13259b43c821686b9bafea4dfe5477cf"},
    {"name": "FDS", "version": "6.11.1", "file": "FDS-6.11.1_SMV-6.11.2_win.exe",
     "url": "https://github.com/firemodels/fds/releases/download/FDS-6.11.1/FDS-6.11.1_SMV-6.11.2_win.exe",
     "sha256": "302ec837caaea8cb990cece085bee2284a0338d64fac0b77d46749a92ab12dfc"},
]


def main():
    (ROOT / "downloads").mkdir(parents=True, exist_ok=True)
    (ROOT / "tools").mkdir(parents=True, exist_ok=True)
    evidence = []
    for package in PACKAGES:
        target = ROOT / "downloads" / package["file"]
        if not target.exists():
            partial = target.with_suffix(target.suffix + ".part")
            print("Downloading", package["name"], flush=True)
            with urllib.request.urlopen(package["url"], timeout=120) as r, partial.open("wb") as f:
                while block := r.read(1024**2):
                    f.write(block)
            partial.replace(target)
        digest = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
        if digest != package["sha256"]:
            raise RuntimeError("Checksum mismatch: " + package["name"])
        print("Verified", package["name"], digest, flush=True)
        if target.suffix == ".zip":
            with zipfile.ZipFile(target) as archive:
                archive.extractall(ROOT / "tools")
        else:
            # Extraction is separate from vendor setup: no PATH/service changes.
            dest = ROOT / "tools" / "fds-6.11.1"
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["tar", "-xf", str(target), "-C", str(dest)], check=True)
        evidence.append({**package, "verified_at_unix": time.time(), "bytes": target.stat().st_size})
        (ROOT / "tools" / "installed.json").write_text(json.dumps(evidence, indent=2))
    print("Tools extracted", flush=True)


if __name__ == "__main__":
    main()
