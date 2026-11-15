"""Train/validation isolation and loss/checkpoint contracts using tiny CPU tensors."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def fit(monkeypatch):
    pytest.importorskip("torch")
    scripts = Path(__file__).parents[1] / "tools/remote"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("hotspot_fit_test", scripts / "fit_hotspot_spatial.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fit_loads_only_train_validation_and_requires_correct_design(fit, monkeypatch):
    store = SimpleNamespace(
        snapshot={"dataset_id": "spatial-compact-v1"},
        shape=(12, 16, 8),
        by_split={"train": list(range(120)), "validation": list(range(40)), "test": list(range(40))},
    )
    seen = []

    def load_partition(_, split):
        assert split != "test"
        seen.append(split)
        return [{"record": {"split": split}}]

    monkeypatch.setattr(fit, "load_partition", load_partition)
    assert set(fit.fit_cases(store)) == {"train", "validation"}
    assert seen == ["train", "validation"]
    store.by_split["train"] = list(range(60))
    with pytest.raises(ValueError, match="120 train and 40 validation"):
        fit.fit_cases(store)


@pytest.mark.parametrize("split", ["train", "test"])
def test_checkpoint_selection_refuses_non_validation_cases(fit, monkeypatch, split):
    monkeypatch.setattr(fit, "assess", lambda *a: pytest.fail("Do not evaluate forbidden targets"))
    with pytest.raises(ValueError, match="validation cases only"):
        fit.validation_assessment(None, [{"record": {"split": split}}])


def test_selection_uses_historical_localization_metric_and_refuses_nan(fit):
    assert fit.selection_value({"localization_selection_error": 0.7, "selection_loss": 100}) == 0.7
    with pytest.raises(ValueError, match="Nonfinite"):
        fit.selection_value({"localization_selection_error": float("nan")})


def test_hot_peak_adds_amplitude_penalty_at_true_location(fit):
    torch = pytest.importorskip("torch")
    truth = torch.tensor([[[[0.0, 5.0]], [[0.0, 0.0]]]])
    prediction = torch.tensor([[[[5.0, 0.0]], [[0.0, 0.0]]]], requires_grad=True)
    observed = torch.ones_like(truth, dtype=torch.bool)
    globals_ = torch.zeros((1, 4))
    global_mask = torch.ones_like(globals_, dtype=torch.bool)
    values = (prediction, truth, observed, globals_, globals_, global_mask, truth > 0)
    ordinary = fit.objective_loss(*values, "hot")
    anchored = fit.objective_loss(*values, "hot_peak")
    assert anchored.item() > ordinary.item()
    (anchored - ordinary).backward()
    assert prediction.grad[0, 0, 0, 1] < 0
    assert prediction.grad[0, 0, 0, 0] == 0


def test_checkpoint_is_exclusive_and_cpu_reload_preserves_weights(fit, tmp_path):
    torch = pytest.importorskip("torch")
    state = {"fixture.weight": torch.tensor([[1.0, 2.0]])}
    destination = tmp_path / "weights.pt"
    fit.save_weights(destination, state, 16, "hot", 250)
    saved_bytes = destination.read_bytes()
    loaded = torch.load(destination, map_location="cpu", weights_only=True)
    assert torch.equal(loaded["state_dict"]["fixture.weight"], state["fixture.weight"])
    assert loaded["selected_step"] == 250
    with pytest.raises(FileExistsError):
        fit.save_weights(destination, state, 16, "hot", 500)
    assert destination.read_bytes() == saved_bytes


@pytest.mark.parametrize("extra", [["--seconds", "59"], ["--steps", "20001"], ["--recipe", "uniform"]])
def test_cli_rejects_unbounded_or_undiagnosed_settings(fit, extra):
    with pytest.raises(SystemExit):
        fit.parse_args(["--dataset", "dataset", "--output", "output", "--recipe", "hot", *extra])


def test_source_dataset_cannot_receive_fit_outputs(fit, tmp_path):
    pause = tmp_path / "datasets/spatial-corpus-v1/PAUSE"
    pause.parent.mkdir(parents=True)
    pause.write_text("preserved")
    dataset = tmp_path / "compact"
    dataset.mkdir()
    args = SimpleNamespace(home=tmp_path, dataset=dataset, output=dataset / "fit-output")
    with pytest.raises(ValueError, match="outside the immutable source"):
        fit.run_fit(args)
    assert not args.output.exists()
