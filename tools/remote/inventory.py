"""Run a small CUDA calculation and record only project-relevant machine facts."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import torch

root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
report = {"created_at": datetime.now(timezone.utc).isoformat(), "system": platform.platform(),
          "python": platform.python_version(), "logical_cpus": os.cpu_count(),
          "disk_free_gb": {drive: round(shutil.disk_usage(drive + ":/").free / 1024**3, 2)
                           for drive in ["C", "E", "G"]},
          "fds_executables": [str(p) for p in (root / "tools").rglob("fds*.exe")],
          "blender": str(root / "tools/blender-4.5.9-windows-x64/blender.exe")}
report["torch"] = torch.__version__
report["cuda_available"] = torch.cuda.is_available()
if torch.cuda.is_available():
    report["gpu"] = torch.cuda.get_device_name(0)
    report["vram_bytes"] = torch.cuda.get_device_properties(0).total_memory
    data = torch.ones((64, 64), device="cuda")
    report["cuda_matmul_mean"] = float((data @ data).mean())
report["blender_version"] = subprocess.check_output([report["blender"], "--version"], text=True).splitlines()[0]
(root / "runtime/inventory.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
