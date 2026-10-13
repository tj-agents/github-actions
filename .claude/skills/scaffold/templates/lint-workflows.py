from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile


ACTIONLINT_VERSION = "1.7.11"
ZIZMOR_VERSION = "1.23.1"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "workflow-lint", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workflow-lint-") as temporary:
        root = Path(temporary)
        actionlint = shutil.which("actionlint")
        if not actionlint:
            system = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}[platform.system()]
            machine = {"x86_64": "amd64", "AMD64": "amd64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine()]
            suffix = "zip" if system == "windows" else "tar.gz"
            archive_name = f"actionlint_{ACTIONLINT_VERSION}_{system}_{machine}.{suffix}"
            release = json.loads(download(f"https://api.github.com/repos/rhysd/actionlint/releases/tags/v{ACTIONLINT_VERSION}"))
            matches = [item for item in release["assets"] if item["name"] == archive_name]
            if len(matches) != 1:
                raise RuntimeError("actionlint release asset not found")
            expected = matches[0].get("digest", "")
            if not expected.startswith("sha256:"):
                raise RuntimeError("actionlint release asset has no SHA-256 digest")
            payload = download(matches[0]["browser_download_url"])
            if hashlib.sha256(payload).hexdigest() != expected.partition(":")[2]:
                raise RuntimeError("actionlint release digest does not match")
            archive = root / archive_name
            archive.write_bytes(payload)
            executable = "actionlint.exe" if system == "windows" else "actionlint"
            target = root / executable
            if system == "windows":
                with zipfile.ZipFile(archive) as source:
                    target.write_bytes(source.read(executable))
            else:
                with tarfile.open(archive) as source:
                    member = source.getmember(executable)
                    if not member.isfile():
                        raise RuntimeError("actionlint asset is not a file")
                    with source.extractfile(member) as stream:
                        target.write_bytes(stream.read())
            target.chmod(0o755)
            actionlint = str(target)
        zizmor = shutil.which("zizmor")
        if not zizmor:
            subprocess.run([sys.executable, "-m", "venv", str(root / "venv")], check=True)
            scripts = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
            python = scripts / ("python.exe" if os.name == "nt" else "python")
            subprocess.run([str(python), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", f"zizmor=={ZIZMOR_VERSION}"], check=True)
            zizmor = str(scripts / ("zizmor.exe" if os.name == "nt" else "zizmor"))
        workflows = sorted(str(path) for path in Path(".github/workflows").glob("*.yml"))
        subprocess.run([actionlint, *workflows], check=True)
        subprocess.run([zizmor, "--offline", ".github/workflows", ".github/actions"] if Path(".github/actions").is_dir() else [zizmor, "--offline", ".github/workflows"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
