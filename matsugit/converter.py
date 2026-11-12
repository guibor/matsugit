"""Discover a span-aware Pandoc, or explicitly provision an isolated verified copy."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

from .core import Error
from .compat import env, existing

MINIMUM = (3, 7, 0, 2)
# Reviewed release pins, not checksums fetched alongside a runtime download.
# Provenance and the update procedure are in docs/converter-downloads.md.
PINNED_VERSION = "3.13"
PINNED_ASSETS = {
    ("Linux", "amd64"): ("pandoc-3.13-linux-amd64.tar.gz", "38aa33b325a2bc96a4c39409631212db55702f564250bcdbead180b3bf646389"),
    ("Linux", "arm64"): ("pandoc-3.13-linux-arm64.tar.gz", "21e1d4ba09bd0b334590d204580fd4f6629b21be4ab6a32b26cc98982e9e0c68"),
    ("Darwin", "amd64"): ("pandoc-3.13-x86_64-macOS.zip", "1823278715aa405aaf21b59cde5dc789346aa8d4fc307467f9a9ee84162bedc5"),
    ("Darwin", "arm64"): ("pandoc-3.13-arm64-macOS.zip", "f436d18bebbfb3ddd326597686dacab9fac5dc23bd060495020f35a28a43a7c3"),
    ("Windows", "amd64"): ("pandoc-3.13-windows-x86_64.zip", "23e1f2e978a3df80db8bf65c9c59534f41a23140480cfb4f783a882ab7dc6a4e"),
}


def tools_dir():
    return Path(env("MATSUGIT_TOOLS_DIR", existing(
        "~/.local/share/matsugit/tools", "~/.local/share/folioforge/tools"))).expanduser()


def convert(command, text, reader, writer, *flags):
    try:
        result = subprocess.run([*command, "-f", reader, "-t", writer, *flags], input=text,
                                capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        return result.stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise Error(f"Table conversion failed: {getattr(exc, 'stderr', None) or exc}") from exc


def converter():
    candidates = []
    if env("MATSUGIT_PANDOC"):
        candidates.append([env("MATSUGIT_PANDOC")])
    candidates.append([str(tools_dir() / ('pandoc.exe' if os.name == 'nt' else 'pandoc'))])
    if os.environ.get("QUARTO") or shutil.which("quarto"):
        candidates.append([os.environ.get("QUARTO") or "quarto", "pandoc"])
    candidates.append(["pandoc"])
    for command in candidates:
        try:
            result = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=10)
            match = re.search(r"pandoc (\d+(?:\.\d+)+)", result.stdout)
            if result.returncode == 0 and match:
                version = tuple(int(n) for n in match[1].split("."))
                if version + (0,) * (4 - len(version)) >= MINIMUM:
                    return command
        except (OSError, subprocess.SubprocessError):
            pass
    raise Error("The table editor needs Pandoc >=3.7.0.2 to preserve merged cells. Run matsugit setup-editor (or spacemacs-sync).")


def install_converter():
    try:
        command = converter()
        print("Table editor ready: " + " ".join(command))
        return
    except Error:
        pass
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    system = platform.system()
    if (system, arch) not in PINNED_ASSETS:
        raise Error("Install Pandoc >=3.7.0.2 for this platform, then rerun matsugit setup-editor")
    name, digest = PINNED_ASSETS[system, arch]
    url = f"https://github.com/jgm/pandoc/releases/download/{PINNED_VERSION}/{name}"
    member = (f"pandoc-{PINNED_VERSION}/pandoc.exe" if system == 'Windows' else
              f"pandoc-{PINNED_VERSION}-{'x86_64' if arch == 'amd64' else arch}/bin/pandoc"
              if system == 'Darwin' else f"pandoc-{PINNED_VERSION}/bin/pandoc")
    root = tools_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    executable = 'pandoc.exe' if system == 'Windows' else 'pandoc'
    target = root / executable
    if target.exists() and not (root / "pandoc-install.json").is_file():
        raise Error(f"Refusing to replace unmanaged converter: {target}")
    print(f"Installing isolated {name} (checking packaged SHA-256 pin)", flush=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="install-") as temp:
        archive = Path(temp) / name
        sha = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(url, timeout=30) as response, archive.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 300 * 1024 * 1024:
                    raise Error("Converter download exceeded the size limit")
                sha.update(chunk)
                stream.write(chunk)
        if sha.hexdigest() != digest:
            raise Error("Pandoc checksum mismatch; nothing installed")
        binary = Path(temp) / executable
        if system == "Linux":
            with tarfile.open(archive) as bundle:
                members = [m for m in bundle.getmembers() if m.name == member and m.isfile()]
                if len(members) != 1:
                    raise Error("Unexpected archive layout")
                with bundle.extractfile(members[0]) as src, binary.open("wb") as dest:
                    shutil.copyfileobj(src, dest)
        else:
            with zipfile.ZipFile(archive) as bundle:
                names = [n for n in bundle.namelist() if n == member]
                if len(names) != 1:
                    raise Error("Unexpected archive layout")
                with bundle.open(names[0]) as src, binary.open("wb") as dest:
                    shutil.copyfileobj(src, dest)
        binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        result = subprocess.run([str(binary), "--version"], check=True, capture_output=True,
                                text=True, encoding="utf-8", timeout=10)
        if result.stdout.splitlines()[:1] != [f"pandoc {PINNED_VERSION}"]:
            raise Error("Pandoc version differs from the packaged pin; nothing installed")
        os.replace(binary, target)
        (root / "pandoc-install.json").write_text(json.dumps({"version": PINNED_VERSION,
            "asset": name, "digest": "sha256:" + digest}) + "\n")
    print("Table editor ready: " + " ".join(converter()))
