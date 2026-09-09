# tgrep AI Skill

**English** | [Deutsch](README.de.md)

Local, indexed search for **Claude Code and Codex**, with directories of your
choice and optional answers from **Qwen through Ollama**.

One shared skill, one CLI, shared indexes. tgrep searches text and code;
Qwen turns questions into search terms and answers them using matching excerpts.
It does not replace the main models used by Claude and Codex.

Measured performance: see the [local benchmark report](docs/benchmarks/README.md)
for reproducible CLI timings, index costs, and the limits of the synthetic tests.

## Installation

Requirements: macOS or Linux (ARM64/x86_64), Git, Python **3.10+** with venv.
On Windows, install inside WSL. No sudo, pip, or Python package downloads are
required. The installer downloads tgrep **1.0.5** and ripgrep **15.2.0** from
official releases, with SHA256 hashes pinned in
[dependencies.lock.json](dependencies.lock.json).

~~~sh
git clone https://github.com/Jeuners/tgrep-ai-skill.git
cd tgrep-ai-skill
./install.sh
export PATH="$HOME/.local/bin:$PATH"
local-search doctor
~~~

The installer sets up both skills:

- Claude Code: ~/.claude/skills/local-search/
- Codex: ~/.agents/skills/local-search/

It installs a standalone runtime directory under
~/.local/share/tgrep-ai-skill/. You can move the checkout afterward.
Existing configuration and model choices are preserved; unrelated launchers or
skills with the same name are not overwritten. Your home directory is registered
as a search root, but is not indexed yet. Start a new agent session if the skill
does not appear.

To install for just one agent:

~~~sh
./install.sh --target claude
./install.sh --target codex
~~~

**Let an agent install it:** Give Claude Code or Codex this instruction:

> Install https://github.com/Jeuners/tgrep-ai-skill for Claude Code and Codex.
> Read the README first, run the installer, and check local-search doctor.
> Use my existing Ollama model. Do not start indexing my home directory yet.

## Ollama and Qwen

Direct search works without an LLM. To use **ask**, install and start
[Ollama](https://ollama.com/download) separately:

~~~sh
ollama serve
~~~

If the Ollama app is already running, you do not need a second server.
In another terminal:

~~~sh
ollama list
# Only if the model is missing: approximately 6.6 GB download
ollama pull qwen3.5:latest
local-search doctor
~~~

This model from the official Ollama library is the default. To select another
installed model, such as a smaller variant:

~~~sh
local-search model qwen3.5:4b
~~~

The model and loopback URL are stored in ~/.config/local-search/config.json.
Ollama metadata is checked before every model request: cloud models, remote
aliases, and models without identifiable local weights are rejected.
The installer does not download Ollama or model weights without being asked.
Model weights are not part of this MIT project; their own license terms apply.
The default tag points to the latest version and can change. A tag such as
qwen3.5:4b specifies the model size, but is also mutable and does not guarantee
unchanged model weights.

## Home and other directories

~~~sh
local-search preview home
local-search index home

local-search add projekte "/Volumes/Projekte"
local-search preview projekte
local-search index projekte

local-search add backend "$HOME/Desktop/backend" --exclude vendor --max-filesize 16M
local-search status
~~~

**preview** shows a file count, examples, and exclusions. The count is an estimate
before content and binary checks; if output is truncated, it is a lower bound.
**index** builds the index synchronously, then starts a background server.
There is no automatic startup at login; a later search starts the server if needed.

Default exclusions: .git, node_modules, .venv, venv, target, dist, build,
__pycache__, .ssh, .gnupg, .aws, .azure, .ollama, .Trash, Library, Caches.
Exclusions match **directory names at every level**.
The default file size limit is **8 MiB**. Standard ignore rules also apply outside
Git repositories. Symlinks are not followed.

Hidden descendants are not indexed: tgrep 1.0.5 does not support serve --hidden.
If needed, register a hidden project directory as a separate root.
PDFs, Office documents, images, archives, and semantic embedding search are not
supported. Exclusions do not provide general secret detection.

## Searching

~~~sh
local-search search "WebSocket" --root projekte
local-search search 'auth|login' --regex --root backend
local-search ask "Wo wird die Anmeldung geprüft?" --root backend
local-search search "TODO" --root backend --root projekte
local-search search "Rechnungsnummer" --all --paths-only
local-search search "removed_function" --root backend --fresh
~~~

Without --root, search uses the most specific registered root containing the
current working directory. --all searches every registered root.
Overlapping matches are deduplicated by canonical file path and line number;
overlapping indexes can still use extra storage and search work.

Output is JSON with matches, sources, backend, freshness, warnings, and
truncated. The default limit is 40 matches. --limit 100 increases the limit.
Each report also includes match_count: the matches returned per root and search
request before the global merge. This count is already capped by the individual
search limit; when report.truncated is set, additional uncounted matches may
exist. Because of deduplication, the sum can exceed the length of the merged
match list. If the global result is truncated, search the selected roots
individually or increase --limit.
Line text is capped at 2,000 characters; ask receives at most approximately
12,000 JSON characters of source context and runs no more than three search
terms per root.

A running index is **eventually consistent**. During index building or a detected
update problem, search falls back to a fresh ripgrep scan. --fresh forces this
behavior, including when it is important to confirm that no matches exist.
A filesystem that changes during a search is not an atomic snapshot.
ripgrep and tgrep can differ in edge cases involving ignore rules and binary
file handling.

Exit codes: **0** success/matches, **1** no matches, **2** error,
**130** interrupted. An Ollama outage is an error for ask; search remains usable.

In Claude Code: /local-search. In Codex: $local-search.
If a higher-priority instruction explicitly says “always use rg first,” that
instruction must allow an exception; the skill does not override it.

**Data boundary:** tgrep and Qwen run locally. Output read by a Claude or Codex
agent still enters that agent's context. --paths-only suppresses excerpts and
generated answers, but not filenames. With ask --paths-only, only the question
is sent to Ollama for local search planning.

## Maintenance

~~~sh
local-search stop home
local-search index home      # rebuild completely, then start the server
local-search remove backend # remove registration, keep the index
~~~

Configuration: ~/.config/local-search/config.json.
Indexes, status, and server logs: ~/.local/share/local-search/indexes/.
XDG_CONFIG_HOME and XDG_DATA_HOME are supported.
Changing a root's configuration gives it a new index path. Stop the server
before editing configuration manually, then rebuild the index.

To update from the checkout:

~~~sh
git pull --ff-only
./install.sh
~~~

For a reproducible installation, check out a release tag first. Updates create
a new runtime directory; old ones remain available for running servers.
Stop and restart servers so they use the new binary.

To uninstall:

~~~sh
local-search stop home
# Stop any other running roots as well.
./install.sh --uninstall
~~~

This removes the managed launcher and skills. Configuration, indexes, and old
runtime directories are deliberately retained; you can review and remove them
manually.

## Troubleshooting and development

- command not found: set PATH or run ~/.local/bin/local-search.
- Missing Python/venv: install Python 3.10+; on Debian/Ubuntu, you may also need
  the matching python3-venv package.
- Model unavailable: check ollama list and the running app or ollama serve.
- macOS access denied: your terminal may need permission to access the affected
  directories. Unreadable paths are reported as errors.
- Stuck index: check local-search status and server.log in the reported index path.
- "PID identity changed": the recorded process ID no longer matches the saved
  search server identity, so no signal is sent. Inspect the reported PID with ps.
  Remove the reported owner.json only after confirming that the record is stale
  and no search server still uses that index. Do not terminate an unrelated
  process to resolve this; then try starting the server again.
- Large directories: start with selected project roots. Indexing home can use
  substantial disk space, depending on its contents. The server starts with a
  512 MiB index-building budget and a 25 % CPU budget; this is not a hard limit
  on total process RAM.
- Offline installation: download the release archives in advance and use
  ./install.sh --asset-cache /pfad/zu/archiven. Missing archives are still
  requested online. Dependencies are always verified using SHA256.

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
~~~

Integration tests with real binaries:

~~~sh
LOCAL_SEARCH_INTEGRATION=1 \
LOCAL_SEARCH_TGREP=/pfad/zu/tgrep \
LOCAL_SEARCH_RG=/pfad/zu/rg \
PYTHONPATH=src python3 -m unittest discover -s tests -v
~~~

Full isolated installation, including update and uninstallation:
python3 scripts/smoke_install.py. Optional test of an existing local model,
using only synthetic source code: python3 scripts/smoke_ollama.py.

## Credits and license

MIT; see [LICENSE](LICENSE). This is an independent integration project,
not an official Microsoft, Anthropic, or OpenAI product.

Authorship: implementation written with OpenAI Astra. Review and revisions
by Claude from Anthropic.
AI Operator: [H.G.O.D.](https://github.com/Jeuners).

- [Microsoft tgrep](https://github.com/microsoft/tgrep), MIT
- [ripgrep](https://github.com/BurntSushi/ripgrep), MIT or Unlicense
- [Ollama API](https://docs.ollama.com/api/chat)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)

Installer downloads contain official binaries; dependency source code and
license texts are available in their linked repositories.
