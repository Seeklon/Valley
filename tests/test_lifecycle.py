import pytest
from ignis.locking import ProcessLock
from ignis.store import RunStore


def test_live_runtime_cannot_be_owned_by_two_servers(tmp_path):
    with ProcessLock(tmp_path / "service.lock"):
        with pytest.raises(RuntimeError, match="autre instance"):
            ProcessLock(tmp_path / "service.lock").acquire()
    with ProcessLock(tmp_path / "service.lock"):
        pass


def test_queue_limit_is_checked_inside_transaction(tmp_path):
    store = RunStore(tmp_path)
    for i in range(8):
        store.create(str(i), {"scene_id": "soyuz"})
    with pytest.raises(ValueError, match="huit"):
        store.create("overflow", {"scene_id": "soyuz"})
    assert store.get("overflow") is None
    store.cancel("0")
    store.create("replacement", {"scene_id": "soyuz"})
