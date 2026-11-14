#!/usr/bin/env python3
"""Small SSH controller. Private connection details stay in .remote-pc.json."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class Remote:
    def __init__(self, config: Path = ROOT / ".remote-pc.json"):
        self.config = json.loads(config.read_text())

    def options(self) -> list[str]:
        c = self.config
        return ["-i", c["key"], "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={c['known_hosts']}",
                "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10",
                "-o", "ServerAliveCountMax=3"]

    def ps(self, code: str, timeout: int = 45) -> str:
        prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        encoded = base64.b64encode((prefix + code).encode("utf-16le")).decode()
        c = self.config
        p = subprocess.run(["ssh", *self.options(), "-p", str(c["port"]), "-l", c["user"],
                            c["host"], "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded],
                           capture_output=True, timeout=timeout)
        if p.returncode:
            raise RuntimeError(p.stdout.decode("utf-8", errors="replace")[-3000:] + "\n" +
                               p.stderr.decode("utf-8", errors="replace")[-5000:])
        return p.stdout.decode("utf-8-sig", errors="replace").strip()

    def transfer(self, local: Path, remote: str, *, download: bool = False):
        c = self.config
        endpoint = f"{c['host']}:{remote}"
        files = [endpoint, str(local)] if download else [str(local), endpoint]
        subprocess.run(["scp", *self.options(), "-P", str(c["port"]), "-o", f"User={c['user']}",
                        *files], check=True, timeout=180, stdout=subprocess.DEVNULL)

    def sync(self) -> dict:
        """Transfer only source, never local secrets or generated campaigns."""
        names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                        cwd=ROOT).decode().split("\0")
        files = []
        for name in sorted(set(names)):
            p = ROOT / name
            if not name or not p.is_file() or p.is_symlink() or name.startswith("scenes/generated/"):
                continue
            if p.stat().st_size > 30 * 1024**2:
                raise ValueError(f"Unexpected large source file: {name}")
            files.append(p)
        bundle = ROOT / "runtime/source.zip"
        bundle.parent.mkdir(exist_ok=True)
        manifest = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, p.relative_to(ROOT))
            z.writestr("source-manifest.json", json.dumps(manifest, sort_keys=True))
        if bundle.stat().st_size > 40 * 1024**2:
            raise ValueError("Source bundle exceeds 40 MiB")
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        root = self.config["root"]
        dst = root + "/source.zip"
        self.transfer(bundle, dst)
        self.ps(f"if ((Get-FileHash -Algorithm SHA256 {quote(dst)}).Hash.ToLower() -ne '{digest}') "
                "{ throw 'Source checksum mismatch' }; "
                f"Expand-Archive -Force -LiteralPath {quote(dst)} -DestinationPath {quote(root + '/app')}", timeout=90)
        return {"sha256": digest, "files": len(files), "bytes": bundle.stat().st_size, "remote_app": root + "/app"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync")
    ps = sub.add_parser("ps")
    ps.add_argument("file", type=Path)
    up = sub.add_parser("upload")
    up.add_argument("local", type=Path)
    up.add_argument("remote")
    get = sub.add_parser("download")
    get.add_argument("remote")
    get.add_argument("local", type=Path)
    args = parser.parse_args()
    remote = Remote()
    if args.command == "sync":
        print(json.dumps(remote.sync()))
    elif args.command == "ps":
        print(remote.ps(args.file.read_text(), timeout=120))
    else:
        remote.transfer(args.local, args.remote, download=args.command == "download")


if __name__ == "__main__":
    main()
