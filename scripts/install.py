#!/usr/bin/env python3
"""Install a private runtime and shared skills without pip or root access."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv

SOURCE = Path(__file__).resolve().parents[1]
MARKER = "# Managed by tgrep-ai-skill installer"


def download_binary(entry, destination, cache=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "asset.tar.gz"
        cached = Path(cache) / entry["asset"] if cache else None
        if cached and cached.is_file():
            shutil.copyfile(cached, archive)
        else:
            print(f"Downloading {entry['url']}", flush=True)
            with (
                urllib.request.urlopen(entry["url"], timeout=60) as response,
                archive.open("wb") as out,
            ):
                total = 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > 100_000_000:
                        raise RuntimeError("Release archive exceeds 100 MB.")
                    out.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(
                f"SHA256 mismatch for {entry['asset']}; refusing installation."
            )
        with tarfile.open(archive, "r:gz") as bundle:
            candidates = [
                m for m in bundle if m.isfile() and Path(m.name).name == entry["binary"]
            ]
            if len(candidates) != 1 or candidates[0].size > 100_000_000:
                raise RuntimeError(
                    "Release does not contain exactly one expected binary."
                )
            # Extract only the regular binary, never archive paths or symlinks.
            with (
                bundle.extractfile(candidates[0]) as stream,
                destination.open("wb") as out,
            ):
                shutil.copyfileobj(stream, out)
        destination.chmod(0o700)
    subprocess.run([str(destination), "--version"], check=True, timeout=15)


def atomic_text(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chmod(temporary, 0o700 if executable else 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(args):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    sys.path.insert(0, str(SOURCE / "src"))
    from local_search.config import add_root, load

    # Validate existing settings before changing any installed files.
    load()
    architecture = {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86_64": "x86_64",
        "AMD64": "x86_64",
    }.get(platform.machine())
    system = {"Darwin": "apple-darwin", "Linux": "unknown-linux-musl"}.get(
        platform.system()
    )
    if not architecture or not system:
        raise RuntimeError(
            "Supported: macOS/Linux on arm64 or x86_64; use WSL on Windows."
        )
    target = f"{architecture}-{system}"
    base = Path(args.prefix).expanduser().resolve()
    home = Path(args.skill_home).expanduser().resolve()
    app = base / "share/tgrep-ai-skill"
    launcher = base / "bin/local-search"
    destinations = []
    if args.target in ("claude", "both"):
        destinations.append(home / ".claude/skills/local-search")
    if args.target in ("codex", "both"):
        destinations.append(home / ".agents/skills/local-search")
    manifest_path = app / "install.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if launcher.exists() and (
        not launcher.is_file() or MARKER not in launcher.read_text()
    ):
        raise RuntimeError(f"Refusing to overwrite unrelated launcher: {launcher}")
    for destination in destinations:
        if destination.exists():
            marker = destination / ".tgrep-ai-skill"
            if not marker.is_file() or marker.read_text().strip() != str(app):
                raise RuntimeError(
                    f"Refusing to overwrite unrelated skill: {destination}"
                )
    app.mkdir(parents=True, exist_ok=True)
    # Every install gets an immutable runtime. Existing servers keep their executable.
    runtime = Path(tempfile.mkdtemp(prefix="runtime-", dir=app))
    lock_data = json.loads((SOURCE / "dependencies.lock.json").read_text())
    for tool in ("tgrep", "rg"):
        download_binary(
            lock_data[tool][target], runtime / "bin" / tool, args.asset_cache
        )
    venv.EnvBuilder(with_pip=False).create(runtime / "venv")
    shutil.copytree(
        SOURCE / "src/local_search",
        runtime / "src/local_search",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    python = runtime / "venv/bin/python"
    entry = runtime / "entry.py"
    entry.write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent / 'src'))\n"
        "from local_search.cli import main\nmain()\n"
    )
    launch = (
        f"#!/bin/sh\n{MARKER}\n"
        f"export LOCAL_SEARCH_TGREP={shlex.quote(str(runtime / 'bin/tgrep'))}\n"
        f"export LOCAL_SEARCH_RG={shlex.quote(str(runtime / 'bin/rg'))}\n"
        f'exec {shlex.quote(str(python))} -I {shlex.quote(str(entry))} "$@"\n'
    )
    subprocess.run([str(python), "-I", str(entry), "--version"], check=True)
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        skill = (SOURCE / "skills/local-search/SKILL.md").read_text()
        skill += f"\nInstalled CLI (use when PATH lacks it): {launcher}\n"
        atomic_text(destination / "SKILL.md", skill)
        atomic_text(destination / ".tgrep-ai-skill", str(app) + "\n")
    atomic_text(launcher, launch, executable=True)
    manifest = {
        "launcher": str(launcher),
        "runtime": str(runtime),
        "skills": sorted(
            set(previous.get("skills", []) + [str(p) for p in destinations])
        ),
    }
    atomic_text(manifest_path, json.dumps(manifest, indent=2))
    # Preserve existing registry and model choices. Registration does not scan home.
    roots = load()["roots"]
    home_path = str(Path.home().resolve())
    if "home" not in roots and not any(
        root["path"] == home_path for root in roots.values()
    ):
        add_root("home", str(Path.home()))
    print(f"Installed: {launcher}\nSkills: {', '.join(map(str, destinations))}")
    print(
        f'Add to PATH if needed: export PATH={shlex.quote(str(base / "bin"))}:"$PATH"'
    )
    print(
        "Next: local-search doctor; local-search preview home; local-search index home"
    )
    doctor = subprocess.run([str(launcher), "doctor"], check=False)
    if doctor.returncode:
        print(
            "Search installed. Ollama/model setup may still be needed; see README.md."
        )


def uninstall(args):
    app = Path(args.prefix).expanduser().resolve() / "share/tgrep-ai-skill"
    manifest_path = app / "install.json"
    if not manifest_path.exists():
        raise RuntimeError(f"No installation manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    launcher = Path(manifest["launcher"])
    if launcher.is_file() and MARKER in launcher.read_text():
        launcher.unlink()
    for value in manifest["skills"]:
        destination = Path(value)
        marker = destination / ".tgrep-ai-skill"
        if marker.is_file() and marker.read_text().strip() == str(app):
            (destination / "SKILL.md").unlink(missing_ok=True)
            marker.unlink()
            if not any(destination.iterdir()):
                destination.rmdir()
    print("Launcher and managed skills removed. Stop servers before uninstalling.")
    print(
        f"Runtimes preserved at {app}; configuration and search indexes are preserved."
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["claude", "codex", "both"], default="both")
    parser.add_argument("--prefix", default=str(Path.home() / ".local"))
    parser.add_argument(
        "--skill-home",
        default=str(Path.home()),
        help="Alternate skill installation home",
    )
    parser.add_argument(
        "--asset-cache",
        help="Directory containing pinned release archives (offline install)",
    )
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(SOURCE / "src"))
    from local_search.config import SearchError, lock

    try:
        app = Path(args.prefix).expanduser().resolve() / "share/tgrep-ai-skill"
        with lock(app / "install.lock"):
            (uninstall if args.uninstall else install)(args)
    except (
        OSError,
        RuntimeError,
        ValueError,
        SearchError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Installer: {error}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
