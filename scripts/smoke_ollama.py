#!/usr/bin/env python3
"""Opt-in local Qwen smoke test with synthetic source code only."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_search import cli, config  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="tgrep-qwen-smoke-") as temporary:
        base = Path(temporary)
        with patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(base / "config"),
                "XDG_DATA_HOME": str(base / "data"),
            },
        ):
            project = base / "example"
            project.mkdir()
            (project / "auth.py").write_text(
                "def authenticate_login(username, password):\n"
                "    # Login authentication checks the password before issuing a session.\n"
                "    return verify_password(username, password)\n"
            )
            config.add_root("example", project)
            args = cli.parser().parse_args(
                [
                    "ask",
                    "Wo wird die Anmeldung (login) geprüft?",
                    "--root",
                    "example",
                    "--fresh",
                ]
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.run(args)
            result = json.loads(output.getvalue())
            if code or not result.get("sources") or not result.get("answer"):
                raise RuntimeError(
                    "Qwen did not produce an answer with source excerpts."
                )
            print(
                json.dumps(
                    {
                        "queries": result["queries"],
                        "answer": result["answer"],
                        "sources": len(result["sources"]),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
