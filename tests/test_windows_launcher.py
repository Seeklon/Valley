"""Smoke-only tests: WMI detachment, idempotency and stop ownership checks."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell and WMI")
ROOT = Path(__file__).resolve().parents[1]


def invoke(script: str, runtime: Path, *extra: str):
    args = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(ROOT / "tools/windows" / script), "-Runtime", str(runtime), "-SmokeTest",
    ]
    return subprocess.run([*args, *extra], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=35)


def test_detached_launch_is_idempotent_and_stop_checks_identity(tmp_path):
    runtime = tmp_path / "runtime with spaces"
    state_path = runtime / "service/smoke-process.json"
    start_args = ["-Root", str(ROOT), "-Python", sys.executable, "-SmokeSeconds", "90"]
    result = invoke("start-ignis.ps1", runtime, *start_args)
    assert result.returncode == 0, result.stderr
    started = json.loads(result.stdout)
    assert started["status"] == "started"
    original = state_path.read_text(encoding="utf-8")
    state = json.loads(original)
    assert state["kind"] == "smoke" and state["pid"] == started["pid"]
    try:
        heartbeat = Path(state["heartbeat"])
        first = json.loads(heartbeat.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            second = json.loads(heartbeat.read_text(encoding="utf-8"))
            if second["utc"] != first["utc"]:
                break
            time.sleep(0.1)
        assert second["utc"] != first["utc"], "Child stopped when invoking PowerShell exited"
        duplicate = invoke("start-ignis.ps1", runtime, *start_args)
        assert duplicate.returncode == 0, duplicate.stderr
        assert json.loads(duplicate.stdout)["pid"] == started["pid"]
        assert json.loads(duplicate.stdout)["status"] == "already_running"

        # Simulate a stale/reused PID record, without touching a foreign process.
        state["creation_utc"] = "2000-01-01T00:00:00.0000000Z"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        refused = invoke("stop-ignis.ps1", runtime)
        assert refused.returncode != 0
        assert "identity changed" in refused.stderr
        assert not Path(state["stop_file"]).exists()
    finally:
        state_path.write_text(original, encoding="utf-8")
        stopped = invoke("stop-ignis.ps1", runtime)
        assert stopped.returncode == 0, stopped.stderr
        status = json.loads(stopped.stdout)
        assert status["status"] == "stopped" and status["forced"] is False

    again = invoke("stop-ignis.ps1", runtime)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["status"] == "already_stopped"


def test_concurrent_bootstrap_cannot_replace_pending_or_live_owner(tmp_path):
    """Reproduce SSH loss before state publication without timing-dependent sleeps.

    Execute the actual embedded bootstrap. Pause the first after it acquired its
    lifetime lock but before publishing identity, then run the second bootstrap
    that an immediate relaunch could create. No API or CFD is started.
    """
    script = (ROOT / "tools/windows/start-ignis.ps1").read_text(encoding="utf-8")
    bootstrap = script.split("$bootstrap = @'\n", 1)[1].split("\n'@", 1)[0]
    runtime = tmp_path / "concurrent runtime"
    service = runtime / "service"
    service.mkdir(parents=True)
    state_path = service / "smoke-process.json"
    entered = service / "before-publication"
    release = service / "publish-now"
    processes = []
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}

    def start(token, *, paused=False):
        directory = service / token
        directory.mkdir()
        config = {
            "root": str(ROOT), "runtime": str(runtime), "token": token, "kind": "smoke",
            "state": str(state_path), "smoke_seconds": 30, "environment": {},
            **{key: str(directory / filename) for key, filename in {
                "log": "service.log", "ready": "started.json", "stop": "stop.request",
                "heartbeat": "heartbeat.json",
            }.items()},
        }
        code = bootstrap.replace("__CONFIG_BASE64__", base64.b64encode(
            json.dumps(config).encode("utf-8")).decode("ascii"))
        prefix = ""
        if paused:
            prefix = (
                "from pathlib import Path\n"
                "import time\n"
                "import ignis.windows_process as wp\n"
                "original_identity = wp.current_process_identity\n"
                "def paused_identity():\n"
                f"    Path({str(entered)!r}).touch()\n"
                "    deadline = time.monotonic() + 20\n"
                f"    while not Path({str(release)!r}).exists():\n"
                "        if time.monotonic() > deadline: raise TimeoutError('Test barrier')\n"
                "        time.sleep(0.025)\n"
                "    return original_identity()\n"
                "wp.current_process_identity = paused_identity\n"
            )
        process = subprocess.Popen(
            # A Windows venv redirector has its own PID; this stdlib-only smoke
            # uses the base interpreter so Popen owns the tested process itself.
            [getattr(sys, "_base_executable", sys.executable), "-c", prefix + code], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        processes.append((process, config))
        return process, config

    def wait_for(path):
        deadline = time.monotonic() + 10
        while not Path(path).exists():
            assert time.monotonic() < deadline, f"Missing test marker: {path}"
            time.sleep(0.025)

    try:
        owner, first = start("first", paused=True)
        wait_for(entered)
        assert owner.poll() is None and not state_path.exists()
        rejected, second = start("second")
        assert rejected.wait(timeout=10) != 0
        assert not state_path.exists(), "Concurrent bootstrap replaced unpublished ownership"
        assert not Path(second["ready"]).exists()
        assert "no identity was published" in Path(second["log"]).read_text(encoding="utf-8")

        release.touch()
        wait_for(first["ready"])
        identity = state_path.read_bytes()
        assert json.loads(identity)["pid"] == owner.pid
        late, third = start("third")
        assert late.wait(timeout=10) != 0
        assert state_path.read_bytes() == identity, "Live owner's identity was overwritten"
        assert not Path(third["ready"]).exists()

        # A crash also releases the OS handle; no stale lock blocks recovery.
        owner.kill()
        owner.wait(timeout=10)
        replacement, fourth = start("fourth")
        wait_for(fourth["ready"])
        assert replacement.poll() is None
        assert json.loads(state_path.read_bytes())["pid"] == replacement.pid
        assert (service / "smoke-process.json.stale.fourth.json").read_bytes() == identity
        Path(fourth["stop"]).touch()
        assert replacement.wait(timeout=10) == 0
    finally:
        release.touch()
        for process, config in processes:
            Path(config["stop"]).touch()
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
