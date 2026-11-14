"""Resume the Windows corpus, then train CUDA only after all FDS cases finish.

Run detached on Windows for a long study. STOP, PAUSE and the disk reserve are
handled by the generator; an incomplete campaign never starts training.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ignis.locking import ProcessLock

DATASET_ID = "spatial-corpus-v1"


def ready_for_training(progress: dict) -> bool:
    return (
        progress.get("dataset_id") == DATASET_ID
        and progress.get("state") == "completed"
        and progress.get("total_runs") == 20000
        and progress.get("completed_runs") == 20000
        and progress.get("failed_runs") == 0
        and progress.get("completed_layouts") == 1000
    )


def wait_for_training(dataset: Path, progress: dict, *, wait=time.sleep) -> bool:
    if not ready_for_training(progress):
        return False
    if (dataset / "PAUSE").exists():
        print(json.dumps({"stage": "paused_before_training"}), flush=True)
    while (dataset / "PAUSE").exists():
        if (dataset / "STOP").exists():
            return False
        wait(2)
    return not (dataset / "STOP").exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument(
        "--fds", type=Path,
        default=Path("E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"),
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This study must run on the authorized Windows CUDA workstation.")
    home = args.home.resolve()
    dataset = home / "datasets" / DATASET_ID
    model = home / "runtime/models" / DATASET_ID
    scripts = Path(__file__).resolve().parent
    # This lock protects only the orchestration. Each child owns its own compute
    # lock; wrapping generation in compute.lock would prevent FDS from starting.
    with ProcessLock(home / "runtime/spatial-study.lock"):
        if model.exists():
            raise FileExistsError("The corpus model already exists and is preserved.")
        subprocess.run(
            [sys.executable, "-u", str(scripts / "generate_spatial_corpus.py"),
             "--home", str(home), "--fds", str(args.fds)],
            check=True, stdout=sys.stdout, stderr=sys.stderr,
        )
        progress = json.loads((dataset / "progress.json").read_text(encoding="utf-8"))
        if not wait_for_training(dataset, progress):
            print(json.dumps({"stage": "training_deferred", "campaign_state": progress.get("state")}),
                  flush=True)
            return
        # train_spatial independently verifies the frozen index, all labels,
        # geometry separation and CUDA before the first optimizer step.
        subprocess.run(
            [sys.executable, "-u", str(scripts / "train_spatial.py"),
             "--home", str(home), "--dataset", str(dataset),
             "--model-id", DATASET_ID, "--epochs", "20", "--batch-size", "4"],
            check=True, stdout=sys.stdout, stderr=sys.stderr,
        )


if __name__ == "__main__":
    main()
