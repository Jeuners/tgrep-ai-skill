"""tgrep lifecycle and bounded machine-readable searches."""

import base64
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import socket
import subprocess
import tempfile
import time

from .config import SearchError, atomic_json, index_dir, lock

_CHILDREN = {}


def reap(pid):
    child = _CHILDREN.get(pid)
    if child is not None and child.poll() is not None:
        child.wait()
        del _CHILDREN[pid]


def binary(name):
    value = os.environ.get("LOCAL_SEARCH_" + name.upper()) or shutil.which(name)
    if not value:
        raise SearchError(f"{name} is missing. Run the installer or put it on PATH.")
    return str(Path(value).resolve())


def filters(root, indexed=False):
    args = ["--no-require-git", "--max-filesize", root["max_filesize"]]
    for name in root["exclude"]:
        if indexed:
            args.extend(["--exclude", name])
        else:
            args.extend(["-g", f"!**/{name}/**"])
    return args


def rpc_status(directory):
    try:
        info = json.loads((directory / "serve.json").read_text())
        port = int(info["port"])
        if not 1 <= port <= 65535:
            return None
        with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
            conn.sendall(b'{"jsonrpc":"2.0","method":"status","id":1}\n')
            with conn.makefile("rb") as stream:
                response = json.loads(stream.readline(65536))
        status = response["result"]
        if not isinstance(status, dict) or "num_files" not in status:
            return None
        return {**status, "pid": info["pid"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def status(root):
    directory = index_dir(root)
    return {
        "path": root["path"],
        "available": Path(root["path"]).is_dir(),
        "index_path": str(directory),
        "indexed": (directory / "meta.json").exists(),
        "server": rpc_status(directory),
    }


def stop(root):
    directory = index_dir(root)
    with lock(directory / "manager.lock"):
        _stop(directory)


def owned_pid(directory):
    owner = directory / "owner.json"
    if not owner.exists():
        return None
    record = json.loads(owner.read_text())
    pid = int(record["pid"])
    if pid <= 1:
        raise SearchError("Invalid server PID.")
    reap(pid)
    # Check the process identity, not just an old PID which the OS may reuse.
    check = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        timeout=5,
    )
    command = check.stdout.strip()
    if check.returncode != 0:
        owner.unlink(missing_ok=True)
        return None
    if (
        record["binary"] not in command
        or str(directory) not in command
        or "serve" not in command
    ):
        raise SearchError(
            "PID identity changed; refusing to signal an unrelated process."
        )
    return pid


def _stop(directory):
    owner = directory / "owner.json"
    pid = owned_pid(directory)
    if pid is None:
        if rpc_status(directory):
            raise SearchError("Server is not owned by local-search; stop it manually.")
        return
    os.kill(pid, signal.SIGINT)
    for _ in range(100):
        if rpc_status(directory) is None:
            # Wait for exit, not merely the server discovery file disappearing.
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                reap(pid)
                owner.unlink(missing_ok=True)
                return
            probe = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode != 0 or probe.stdout.strip().startswith("Z"):
                reap(pid)
                owner.unlink(missing_ok=True)
                return
        time.sleep(0.1)
    raise SearchError(
        "Server did not stop within 10 seconds; no forced kill was issued."
    )


def start(root, rebuild=False):
    if not Path(root["path"]).is_dir():
        raise SearchError(f"Root unavailable: {root['path']}")
    directory = index_dir(root)
    with lock(directory / "manager.lock"):
        running = rpc_status(directory)
        if running and not rebuild:
            return running
        if not running and not rebuild and owned_pid(directory) is not None:
            # A cold start can spend minutes reconciling before publishing RPC.
            # Preserve it; searches can use ripgrep while it finishes.
            raise SearchError(
                "Owned server is still starting; check status and server.log."
            )
        if rebuild:
            _stop(directory)
            result = subprocess.run(
                [
                    binary("tgrep"),
                    "index",
                    root["path"],
                    "--index-path",
                    str(directory),
                    *filters(root, True),
                ],
                check=False,
            )
            if result.returncode:
                raise SearchError("Index build failed; inspect the errors above.")
        executable = binary("tgrep")
        with (directory / "server.log").open("w") as log:
            child = subprocess.Popen(
                [
                    executable,
                    "serve",
                    root["path"],
                    "--index-path",
                    str(directory),
                    "--max-memory",
                    "512",
                    "--max-cpu",
                    "25",
                    *filters(root, True),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        _CHILDREN[child.pid] = child
        atomic_json(directory / "owner.json", {"pid": child.pid, "binary": executable})
        for _ in range(100):
            if child.poll() is not None:
                reap(child.pid)
                (directory / "owner.json").unlink(missing_ok=True)
                raise SearchError(f"Server exited; see {directory / 'server.log'}")
            running = rpc_status(directory)
            if running:
                return running
            time.sleep(0.1)
        raise SearchError(
            f"Server still starting; use status. Log: {directory / 'server.log'}"
        )


def collect(command, timeout=30, byte_limit=4_000_000):
    """Bound subprocess output and execution time before loading it in memory."""
    output = bytearray()
    truncated = False
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise SearchError(f"Search timed out after {timeout}s.")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = byte_limit - len(output)
                        output.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            truncated = True
                            process.terminate()
                            selector.unregister(key.fileobj)
                            break
                try:
                    code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as error:
                    raise SearchError("Search process did not exit in time.") from error
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
        errors.seek(0)
        diagnostic = errors.read(8192).decode("utf-8", errors="replace")
    if code not in (0, 1) and not truncated:
        raise SearchError(diagnostic.strip() or f"Search exited with {code}.")
    return bytes(output), truncated, diagnostic


def preview(root):
    if not Path(root["path"]).is_dir():
        raise SearchError(f"Root unavailable: {root['path']}")
    data, truncated, warnings = collect(
        [binary("rg"), "--files", "--null", *filters(root), root["path"]], timeout=120
    )
    paths = data.split(b"\0")[:-1]
    return {
        "path": root["path"],
        "files": len(paths),
        "count_is_lower_bound": truncated,
        "max_filesize": root["max_filesize"],
        "exclude": root["exclude"],
        "hidden": False,
        "warnings": warnings,
        "sample": [os.fsdecode(path) for path in paths[:10]],
        "note": "File-list estimate; binary detection and tgrep membership can differ.",
    }


def decode_field(field):
    if "text" in field:
        return field["text"]
    return os.fsdecode(base64.b64decode(field["bytes"]))


def search(root, pattern, regex=False, limit=100, fresh=False):
    warnings = []
    backend = "rg"
    server = None
    if not Path(root["path"]).is_dir():
        raise SearchError(f"Root unavailable: {root['path']}")
    if not fresh:
        try:
            server = start(root)
            if (
                server.get("indexing", True)
                or server.get("reconcile_running")
                or server.get("reconcile_pending")
                or server.get("reconcile_overdue")
                or server.get("last_reconcile_error")
            ):
                warnings.append(
                    "Index updating or refresh unhealthy; using a fresh ripgrep scan."
                )
            else:
                backend = "tgrep"
        except (SearchError, OSError) as error:
            warnings.append(f"tgrep unavailable: {error}; using ripgrep.")
    args = ["--json", "-n", "--color", "never", "--no-config", *filters(root)]
    if not regex:
        args.append("-F")
    args.extend(["-e", pattern])
    command = [binary(backend), *args]
    if backend == "tgrep":
        command.extend(["--index-path", str(index_dir(root))])
    command.append(root["path"])
    try:
        data, truncated, diagnostic = collect(command)
    except SearchError as error:
        if backend == "rg":
            raise
        warnings.append(f"tgrep failed: {error}; using ripgrep.")
        backend = "rg"
        data, truncated, diagnostic = collect([binary("rg"), *args, root["path"]])
    if diagnostic:
        warnings.append(diagnostic.strip())
    matches = []
    for line in data.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            if truncated and line == data.splitlines()[-1]:
                break
            raise SearchError("Search returned malformed JSON.")
        if event.get("type") != "match":
            continue
        item = event["data"]
        path = Path(decode_field(item["path"])).resolve()
        if not path.is_relative_to(Path(root["path"])):
            raise SearchError("Search result escaped its registered root.")
        text = decode_field(item["lines"]).rstrip("\r\n")
        matches.append(
            {
                "path": str(path),
                "line": item["line_number"],
                "text": text[:2000],
                "text_truncated": len(text) > 2000,
            }
        )
        if len(matches) > limit:
            matches.pop()
            truncated = True
            break
    return {
        "backend": backend,
        "matches": matches,
        "truncated": truncated,
        "warnings": warnings,
        "server": server,
        "freshness": "filesystem scan"
        if backend == "rg"
        else "eventually consistent index",
    }
