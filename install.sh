#!/bin/sh
# Run from a reviewed checkout; no administrator privileges needed.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Python 3.10+ is required. Install it, then rerun ./install.sh.' >&2
    exit 2
fi
exec python3 "$SCRIPT_DIR/scripts/install.py" "$@"
