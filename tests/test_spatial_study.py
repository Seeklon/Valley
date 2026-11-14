"""The long job must not train on a stopped or partial campaign."""

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).parents[1] / "tools/remote/run_spatial_study.py"
spec = importlib.util.spec_from_file_location("spatial_study", path)
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


@pytest.mark.parametrize("change", [
    {"state": "stopped"}, {"state": "disk_reserve"}, {"state": "failed"},
    {"completed_runs": 19999}, {"failed_runs": 1}, {"completed_layouts": 999},
    {"dataset_id": "incidents-v1"}, {"total_runs": 60},
])
def test_only_complete_corpus_can_start_training(change):
    complete = {"dataset_id": "spatial-corpus-v1", "state": "completed", "total_runs": 20000,
                "completed_runs": 20000, "failed_runs": 0, "completed_layouts": 1000}
    assert study.ready_for_training(complete)
    assert not study.ready_for_training({**complete, **change})


def test_pause_during_last_solve_is_honored_before_gpu_training(tmp_path):
    complete = {"dataset_id": "spatial-corpus-v1", "state": "completed", "total_runs": 20000,
                "completed_runs": 20000, "failed_runs": 0, "completed_layouts": 1000}
    pause, stop = tmp_path / "PAUSE", tmp_path / "STOP"
    pause.touch()
    waited = []

    def resume(seconds):
        waited.append(seconds)
        pause.unlink()

    assert study.wait_for_training(tmp_path, complete, wait=resume)
    assert waited == [2]
    pause.touch()
    stop.touch()
    assert not study.wait_for_training(tmp_path, complete, wait=resume)
    assert waited == [2]
    pause.unlink()
    assert not study.wait_for_training(tmp_path, complete, wait=resume)
