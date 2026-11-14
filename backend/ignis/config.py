from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    runtime: Path
    fds_executable: Path | None
    omp_threads: int = 4
    max_runs: int = 2000
    disk_reserve_gb: float = 8.0

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.getenv("IGNIS_ROOT", str(Path(__file__).resolve().parents[2])))
        runtime = Path(os.getenv("IGNIS_RUNTIME", str(root / "runtime")))
        exe = os.getenv("IGNIS_FDS")
        return cls(root=root, runtime=runtime, fds_executable=Path(exe) if exe else None,
                   omp_threads=max(1, min(8, int(os.getenv("IGNIS_THREADS", "4")))))

    @property
    def catalog_path(self) -> Path:
        return self.root / "scenes/catalog.json"

    @property
    def models_dir(self) -> Path:
        return self.runtime / "models"
