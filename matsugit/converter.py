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
    candidates.append([str(tools_dir() / "pandoc")])
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
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    system = platform.system()
    if not arch or system not in {"Linux", "Darwin"}:
        raise Error("Install Pandoc >=3.7.0.2 for this platform, then rerun spacemacs-sync")
    request = urllib.request.Request("https://api.github.com/repos/jgm/pandoc/releases/latest",
                                     headers={"User-Agent": "matsugit", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    suffix = f"linux-{arch}.tar.gz" if system == "Linux" else f"{'x86_64' if arch == 'amd64' else arch}-macOS.zip"
    assets = [a for a in release["assets"] if a["name"].endswith(suffix)]
    if len(assets) != 1:
        raise Error("No unambiguous official Pandoc binary found for this machine")
    asset = assets[0]
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest or ""):
        raise Error("Official release lacks a SHA-256 digest; refusing an unverified install")
    url = asset["browser_download_url"]
    if not url.startswith("https://github.com/jgm/pandoc/releases/download/"):
        raise Error("Unexpected download location")
    root = tools_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / "pandoc"
    if target.exists() and not (root / "pandoc-install.json").is_file():
        raise Error(f"Refusing to replace unmanaged converter: {target}")
    print(f"Installing isolated {asset['name']} (SHA-256 verified)", flush=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="install-") as temp:
        archive = Path(temp) / asset["name"]
        sha = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(url, timeout=30) as response, archive.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 300 * 1024 * 1024:
                    raise Error("Converter download exceeded the size limit")
                sha.update(chunk)
                stream.write(chunk)
        if "sha256:" + sha.hexdigest() != digest:
            raise Error("Pandoc checksum mismatch; nothing installed")
        binary = Path(temp) / "pandoc"
        if system == "Linux":
            with tarfile.open(archive) as bundle:
                members = [m for m in bundle.getmembers() if m.name.endswith("/bin/pandoc") and m.isfile()]
                if len(members) != 1:
                    raise Error("Unexpected archive layout")
                with bundle.extractfile(members[0]) as src, binary.open("wb") as dest:
                    shutil.copyfileobj(src, dest)
        else:
            with zipfile.ZipFile(archive) as bundle:
                names = [n for n in bundle.namelist() if n.endswith("/bin/pandoc")]
                if len(names) != 1:
                    raise Error("Unexpected archive layout")
                with bundle.open(names[0]) as src, binary.open("wb") as dest:
                    shutil.copyfileobj(src, dest)
        binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        subprocess.run([str(binary), "--version"], check=True, capture_output=True, timeout=10)
        os.replace(binary, target)
        (root / "pandoc-install.json").write_text(json.dumps({"asset": asset["name"], "digest": digest}) + "\n")
    print("Table editor ready: " + " ".join(converter()))
