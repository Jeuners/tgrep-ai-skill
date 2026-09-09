# Local performance measurements

These measurements compare the complete skill CLI using a running tgrep index
with the same CLI using ripgrep through `--fresh`. They include Python startup,
backend selection, subprocess execution, JSON handling, and output capture.
They are not direct tgrep-versus-ripgrep binary timings.

## Environment and method

- Apple M4, 10 logical CPUs, 16 GiB RAM; macOS 26.5.2, Python 3.10.5.
- tgrep 1.0.5 and ripgrep 15.2.0 from the installer's pinned releases.
- Deterministic synthetic Python files in temporary directories, on local storage.
  Files contain generated functions and known search markers. Their vocabulary is
  deliberately simple and repetitive, which favors a compact trigram index.
- Two warmup searches per backend and query, then nine measured searches each.
  Each pair runs sequentially in a seeded randomized backend order.
- Warm filesystem caches: neither OS caches nor storage caches are flushed.
  The index build also reads the corpus. This measures repeated interactive search,
  not cold disk performance. The machine is not a dedicated benchmark host.
- Identical root policy and literal/regex flags; maximum 1,000 returned matches.
  Every query is checked against its known match count and exact sorted
  `(path, line, text)` equality across both backends and every repetition.
  Truncation, warnings, or fallback from tgrep abort the benchmark.
- No Ollama or Qwen requests. These numbers measure retrieval, not AI answer latency.

Raw timings, corpus hashes, tool versions, source commit, and benchmark script hash
are recorded in [the JSON report](macos-arm64-2026-09-09.json).

## Results

Median wall time in milliseconds. Speedup is fresh / indexed; below 1× means
indexed search was slower. Every row passed exact match parity.

| Files | Query | Indexed ms | Fresh ms | Speedup |
|---:|---|---:|---:|---:|
| 1,000 | Rare literal (1 match) | 44.0 | 49.7 | 1.13× |
| 1,000 | Distributed literal (1% of files) | 44.4 | 49.0 | 1.10× |
| 1,000 | Absent long literal | 44.2 | 50.0 | 1.13× |
| 1,000 | Selective regex (1 match) | 44.0 | 49.9 | 1.13× |
| 1,000 | Absent two-character literal | 45.0 | 50.1 | 1.11× |
| 20,000 | Rare literal (1 match) | 45.5 | 250.5 | 5.51× |
| 20,000 | Distributed literal (1% of files) | 53.2 | 262.7 | 4.94× |
| 20,000 | Absent long literal | 46.0 | 254.3 | 5.53× |
| 20,000 | Selective regex (1 match) | 45.9 | 236.6 | 5.15× |
| 20,000 | Absent two-character literal | 62.8 | 239.2 | 3.81× |
| 100,000 | Rare literal (1 match) | 51.9 | 1262.8 | 24.32× |
| 100,000 | Distributed literal (1% of files) | 89.7 | 1284.6 | 14.32× |
| 100,000 | Absent long literal | 51.5 | 1253.9 | 24.33× |
| 100,000 | Selective regex (1 match) | 51.8 | 1252.2 | 24.17× |
| 100,000 | Absent two-character literal | 3637.9 | 1262.0 | 0.35× |

| Files | Source MiB | Build + start (s) | Index directory MiB | Server RSS MiB |
|---:|---:|---:|---:|---:|
| 1,000 | 3.0 | 0.136 | 2.4 | 24.0 |
| 20,000 | 63.2 | 0.685 | 47.4 | 108.9 |
| 100,000 | 323.2 | 4.245 | 237.8 | 504.2 |

For the rare-literal query, estimated build break-even is 24 queries at 1,000
files and 4 queries at both larger sizes. The two-character query at 100,000 files
has no break-even in this run: indexed search was about 2.88× slower than fresh.
For such queries, `--fresh` is worth comparing rather than assuming the index wins.

The report contains 270 timed CLI invocations and 60 warmup invocations.
A preliminary run showed noticeably different timings, including better indexed
performance on the two-character query. The complete final run is reported here,
not a selection of the best samples across runs. Run-to-run variability has not
been quantified; the results do not establish its cause.

## Interpretation and limits

The median is the primary statistic. The JSON also records every sample and a
nearest-rank p95; with only nine measured samples, that p95 equals the maximum.
It is not a reliable estimate of production tail latency.

Index build plus server startup is timed once per corpus, excluding generation
of the test files. Index directory size is logical file bytes, including metadata
and logs, not allocated disk blocks. Server RSS is sampled after the queries;
it is not peak memory, total system memory, or a process memory limit.

The break-even estimate divides build-and-start time by the median per-query time
saving. It assumes repetition of that query, an unchanged corpus, and no further
index maintenance. It does not account for background CPU, power, storage costs,
or a changing working tree.

Do not present these numbers as Chromium/gecko-dev results or a universal speedup.
Real repositories have richer trigram vocabularies, varying file sizes, ignores,
binary content, and update activity. This suite also does not cover broad queries
whose output exceeds the limit, filesystem watcher latency, cold server restarts,
or answer quality. A real-repository benchmark and a separate Qwen latency and
answer-quality evaluation are still needed for those claims.

## Reproduce

Install the project first, then pass the installed binaries explicitly. Their
runtime directory is recorded in `~/.local/share/tgrep-ai-skill/install.json`.
Run from the repository checkout:

~~~sh
python3 scripts/benchmark.py \
  --tgrep /path/to/runtime/bin/tgrep \
  --rg /path/to/runtime/bin/rg \
  --sizes 1000 20000 100000 \
  --rounds 9 --warmups 2 \
  --output benchmark-results.json
~~~

Python 3.10+ and local loopback/process access are required. No extra Python
packages or model downloads are needed. The largest corpus contains roughly
323 MiB of source text, plus its index and temporary build files. Each corpus
is removed before the next starts. User configuration and existing indexes are
not changed. If a server cannot be stopped, its directory is preserved and
reported for diagnosis.
