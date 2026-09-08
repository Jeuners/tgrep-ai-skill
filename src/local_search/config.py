"""Persistent root registry; never writes into searchable directories."""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

MODEL = "qwen3.5:latest"
EXCLUDES = [
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".ollama",
    ".Trash",
    "Library",
    "Caches",
]


class SearchError(Exception):
    """An actionable user-facing error."""


def config_dir():
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "local-search"
    )


def data_dir():
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "local-search"
    )


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def load():
    path = config_dir() / "config.json"
    if not path.exists():
        return {
            "version": 1,
            "model": MODEL,
            "ollama_url": "http://127.0.0.1:11434",
            "roots": {},
        }
    try:
        value = json.loads(path.read_text())
        if value.get("version") != 1 or not isinstance(value.get("roots"), dict):
            raise ValueError("unsupported configuration")
        return value
    except (ValueError, AttributeError) as error:
        raise SearchError(f"Invalid configuration at {path}: {error}") from error


def save(value):
    atomic_json(config_dir() / "config.json", value)


def add_root(name, path, excludes=(), max_size="8M"):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise SearchError("Root names must contain 1–64 letters, digits, _ or -.")
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise SearchError(f"Not a readable directory: {path}")
    if not re.fullmatch(r"[1-9][0-9]*[KMG]?", max_size):
        raise SearchError("Use a positive size such as 8M.")
    for item in excludes:
        if not re.fullmatch(r"[\w. -]+", item) or item in (".", ".."):
            raise SearchError("Exclusions are directory names, not paths or globs.")
    with lock(config_dir() / "config.lock"):
        config = load()
        root = {
            "path": str(path),
            "exclude": sorted(set(EXCLUDES + list(excludes))),
            "max_filesize": max_size,
        }
        if name in config["roots"] and config["roots"][name] != root:
            raise SearchError(
                "Root already exists with different settings; remove it first."
            )
        for other, entry in config["roots"].items():
            if other != name and entry["path"] == str(path):
                raise SearchError(f"Directory already registered as {other}.")
        config["roots"][name] = root
        save(config)
    return root


def select_roots(config, names=None, all_roots=False):
    if all_roots:
        names = list(config["roots"])
    if not names:
        cwd = Path.cwd().resolve()
        candidates = [
            (name, root)
            for name, root in config["roots"].items()
            if cwd.is_relative_to(Path(root["path"]))
        ]
        if not candidates:
            raise SearchError(
                "Choose --root NAME or --all; no root contains the current directory."
            )
        names = [max(candidates, key=lambda pair: len(pair[1]["path"]))[0]]
    if not names:
        raise SearchError("No roots registered. Use local-search add NAME PATH.")
    result = []
    for name in dict.fromkeys(names):
        if name not in config["roots"]:
            raise SearchError(f"Unknown root: {name}")
        result.append((name, config["roots"][name]))
    return result


def index_dir(root):
    # A policy change gets a separate index, never reuses incompatible membership.
    digest = hashlib.sha256(json.dumps(root, sort_keys=True).encode()).hexdigest()[:24]
    return data_dir() / "indexes" / digest
