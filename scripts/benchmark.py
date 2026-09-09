#!/usr/bin/env python3
"""Measure full CLI indexed/fresh latency on deterministic synthetic corpora."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "src"))
from local_search import config, engine  # noqa: E402

QUERIES = [
    ("rare_literal", "unique_benchmark_needle", False),
    ("distributed_literal", "batch_benchmark_marker", False),
    ("absent_literal", "absent_benchmark_xyz987", False),
    ("selective_regex", "unique_benchmark_[a-z]+", True),
    ("short_absent_literal", "ZQ", False),
]


def run(command: list[str], env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        command, capture_output=True, text=True, env=env, timeout=120, check=True
    ).stdout.strip()


def corpus(path: Path, count: int) -> dict[str, Any]:
    """Create roughly 4 KiB per file, with known sparse and distributed matches."""
    path.mkdir()
    digest = hashlib.sha256()
    total = 0
    for number in range(count):
        folder = path / f"package_{number // 100:05d}"
        folder.mkdir(exist_ok=True)
        lines = [f"# synthetic module {number}\n"]
        if number == count // 2:
            lines.append("# unique_benchmark_needle\n")
        if number % 100 == 0:
            lines.append("# batch_benchmark_marker\n")
        for item in range(64):
            lines.append(
                f"def function_{number}_{item}(value): "
                f"return value + {number * 64 + item}\n"
            )
        data = "".join(lines).encode()
        (folder / f"module_{number:06d}.py").write_bytes(data)
        digest.update(data)
        total += len(data)
    return {"files": count, "bytes": total, "content_sha256": digest.hexdigest()}


def measure(
    env: dict[str, str], pattern: str, regex: bool, fresh: bool,
) -> tuple[float, list[tuple[str, int, str]]]:
    command = [
        sys.executable, "-m", "local_search.cli", "search", pattern,
        "--root", "benchmark", "--limit", "1000",
    ]
    if regex:
        command.append("--regex")
    if fresh:
        command.append("--fresh")
    started = time.perf_counter()
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=120
    )
    elapsed = (time.perf_counter() - started) * 1000
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Search failed: {result.stderr} {result.stdout}")
    response = json.loads(result.stdout)
    if response.get("truncated"):
        raise RuntimeError("Truncated output cannot establish exact match parity")
    reports = response["reports"]
    expected = "rg" if fresh else "tgrep"
    for report in reports:
        if report["backend"] != expected or report["warnings"]:
            raise RuntimeError(f"Unexpected backend or warning: {report}")
    matches = sorted(
        (item["path"], item["line"], item["text"])
        for item in response["matches"]
    )
    return elapsed, matches


def summarize(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "samples_ms": samples,
        "median_ms": statistics.median(samples),
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def benchmark(
    count: int, rounds: int, warmups: int, binaries: dict[str, str],
) -> dict[str, Any]:
    base = Path(tempfile.mkdtemp(prefix="local-search-benchmark-"))
    safe_to_remove = True
    try:
        metadata = corpus(base / "corpus", count)
        env = {
            **os.environ,
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_DATA_HOME": str(base / "data"),
            "PYTHONPATH": str(SOURCE / "src"),
            **binaries,
        }
        previous = os.environ.copy()
        os.environ.update(env)
        root = None
        try:
            root = config.add_root("benchmark", base / "corpus")
            started = time.perf_counter()
            server = engine.start(root, rebuild=True)
            deadline = time.monotonic() + 120
            while (
                server.get("indexing", True)
                or server.get("reconcile_running")
                or server.get("reconcile_pending")
            ):
                if time.monotonic() > deadline:
                    raise RuntimeError("Index did not become ready")
                time.sleep(0.1)
                server = engine.rpc_status(config.index_dir(root)) or {}
            build_seconds = time.perf_counter() - started
            if server["num_files"] != count:
                raise RuntimeError("Unexpected indexed file count")
            results = []
            rng = random.Random(20260909)
            for name, pattern, regex in QUERIES:
                timings = {False: [], True: []}
                reference = None
                for iteration in range(warmups + rounds):
                    order = [False, True]
                    rng.shuffle(order)
                    for fresh in order:
                        elapsed, matches = measure(env, pattern, regex, fresh)
                        if reference is None:
                            reference = matches
                        if reference != matches:
                            raise RuntimeError(f"Match mismatch for {name}")
                        if iteration >= warmups:
                            timings[fresh].append(elapsed)
                expected_count = (
                    1 if name in ("rare_literal", "selective_regex")
                    else (count + 99) // 100 if name == "distributed_literal"
                    else 0
                )
                if len(reference) != expected_count:
                    raise RuntimeError(f"Unexpected match count for {name}")
                indexed = summarize(timings[False])
                fresh = summarize(timings[True])
                saving = (fresh["median_ms"] - indexed["median_ms"]) / 1000
                results.append({
                    "query": name, "pattern": pattern, "regex": regex,
                    "matches": len(reference), "exact_match_parity": True,
                    "indexed": indexed, "fresh": fresh,
                    "speedup": fresh["median_ms"] / indexed["median_ms"],
                    "build_break_even_queries": (
                        math.ceil(build_seconds / saving) if saving > 0 else None
                    ),
                })
                print(
                    f"{count} files / {name}: "
                    f"{indexed['median_ms']:.1f} vs {fresh['median_ms']:.1f} ms",
                    file=sys.stderr, flush=True,
                )
            directory = config.index_dir(root)
            index_bytes = sum(p.stat().st_size for p in directory.rglob("*")
                              if p.is_file())
            rss_kib = int(run(["ps", "-p", str(server["pid"]), "-o", "rss="]))
            return {
                **metadata, "build_and_start_seconds": build_seconds,
                "index_directory_bytes": index_bytes,
                "server_rss_kib_after_queries": rss_kib, "queries": results,
            }
        finally:
            try:
                if root is not None:
                    safe_to_remove = False
                    try:
                        engine.stop(root)
                    except BaseException:
                        print(f"Stop failed; preserving diagnostics: {base}",
                              file=sys.stderr)
                        raise
                    safe_to_remove = True
            finally:
                os.environ.clear()
                os.environ.update(previous)
    finally:
        if safe_to_remove:
            shutil.rmtree(base)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tgrep", required=True, type=Path)
    parser.add_argument("--rg", required=True, type=Path)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 20000])
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (args.rounds < 3 or args.warmups < 1
            or any(n < 1 or n > 100000 for n in args.sizes)):
        parser.error("Use rounds >= 3, warmups >= 1 and sizes in 1..100000")
    binaries = {
        "LOCAL_SEARCH_TGREP": str(args.tgrep.resolve(strict=True)),
        "LOCAL_SEARCH_RG": str(args.rg.resolve(strict=True)),
    }
    report = {
        "schema": 1, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(), "logical_cpus": os.cpu_count(),
        "cpu_model": run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if sys.platform == "darwin" else platform.processor(),
        "memory_bytes": int(run(["sysctl", "-n", "hw.memsize"]))
        if sys.platform == "darwin" else None,
        "source_commit": run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"]),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "tgrep_version": run([binaries["LOCAL_SEARCH_TGREP"], "--version"]),
        "rg_version": run([binaries["LOCAL_SEARCH_RG"], "--version"]),
        "rounds": args.rounds, "warmups": args.warmups,
        "method": "Full CLI wall time; paired randomized order; warm OS caches; "
                  "synthetic Python; identical filters; exact uncapped match parity; "
                  "no LLM; RSS is a point sample, not a peak; index build is one run",
        "corpora": [],
    }
    for count in args.sizes:
        report["corpora"].append(
            benchmark(count, args.rounds, args.warmups, binaries)
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
