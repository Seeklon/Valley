"""Real Windows process tests. Only short-lived Python sleepers are created."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from ignis.windows_process import WindowsJob, spawn_in_job

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requires real Windows Job Objects")


def wait_file(path: Path, timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"Process did not create {path.name}")


def test_child_runs_with_requested_environment_and_streams():
    env = {**os.environ, "IGNIS_PROCESS_TEST": "owned"}
    process, job = spawn_in_job(
        [sys.executable, "-c", "import os; print(os.environ['IGNIS_PROCESS_TEST'])"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert stdout.strip() == "owned"
    finally:
        job.close()


def test_explicit_close_terminates_child(tmp_path):
    marker = tmp_path / "ready"
    process, job = spawn_in_job([
        sys.executable, "-c",
        "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('ready');time.sleep(120)",
        str(marker),
    ], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        wait_file(marker)
        assert process.poll() is None
        job.close()
        process.wait(timeout=10)  # Job close may use exit code 0; termination is the invariant.
        assert process.poll() is not None
        job.close()
    finally:
        job.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_containment_failure_never_executes_child(tmp_path, monkeypatch):
    marker = tmp_path / "must-not-exist"
    children = []

    def reject(self, process):
        children.append(process)
        raise OSError("Simulated containment refusal")

    monkeypatch.setattr(WindowsJob, "assign", reject)
    with pytest.raises(OSError, match="containment refusal"):
        spawn_in_job([
            sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).touch()", str(marker),
        ], creationflags=subprocess.CREATE_NO_WINDOW)
    assert not marker.exists()
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("during_assignment", [False, True],
                         ids=["running_descendants", "before_child_job_assignment"])
def test_parent_crash_terminates_descendants(tmp_path, during_assignment):
    """Kill a real owner without finally/atexit and wait on both native handles."""
    from ctypes import wintypes

    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import json,os,pathlib,subprocess,sys,time\n"
        "grandchild=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),grandchild.pid]))\n"
        "time.sleep(120)\n", encoding="utf-8",
    )
    marker = tmp_path / "members.json"
    owner_code = (
        "import json,pathlib,sys,time\n"
        "from ignis.windows_process import WindowsJob,spawn_in_job\n"
    )
    if during_assignment:
        owner_code += (
            "def pause_assignment(self,process):\n"
            "    pathlib.Path(sys.argv[2]).write_text(json.dumps([process.pid]))\n"
            "    time.sleep(120)\n"
            "WindowsJob.assign=pause_assignment\n"
        )
    owner_code += (
        "child,job=spawn_in_job([sys.executable,sys.argv[1],sys.argv[2]])\n"
        "time.sleep(120)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
    owner = subprocess.Popen(
        [sys.executable, "-c", owner_code, str(child_script), str(marker)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    try:
        wait_file(marker)
        member_pids = json.loads(marker.read_text())
        assert len(member_pids) == (1 if during_assignment else 2)
        for member_pid in member_pids:
            handle = kernel.OpenProcess(0x00100000, False, member_pid)  # SYNCHRONIZE
            assert handle, f"Cannot observe child {member_pid}: {ctypes.get_last_error()}"
            handles.append(handle)
            assert kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: alive
        owner.kill()  # Deliberately bypass owner cleanup.
        owner.wait(timeout=10)
        for handle in handles:
            assert kernel.WaitForSingleObject(handle, 10_000) == 0  # WAIT_OBJECT_0: dead
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)
        for handle in handles:
            kernel.CloseHandle(handle)
        if owner.stderr:
            owner.stderr.close()
