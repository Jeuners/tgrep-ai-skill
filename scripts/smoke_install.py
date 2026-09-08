#!/usr/bin/env python3
"""Exercise installation/reinstallation/uninstallation in an isolated user prefix."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="tgrep-skill-smoke-") as temporary:
        base = Path(temporary)
        env = {
            **os.environ,
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_DATA_HOME": str(base / "data"),
        }
        command = [
            sys.executable,
            str(SOURCE / "scripts/install.py"),
            "--prefix",
            str(base / "prefix with space"),
            "--skill-home",
            str(base / "skills"),
        ]
        if os.environ.get("LOCAL_SEARCH_ASSET_CACHE"):
            command.extend(["--asset-cache", os.environ["LOCAL_SEARCH_ASSET_CACHE"]])
        subprocess.run(command, check=True, env=env)
        configuration = base / "config/local-search/config.json"
        original = json.loads(configuration.read_text())
        original["model"] = "preserve-this-choice"
        original["roots"]["personal_home"] = original["roots"].pop("home")
        configuration.write_text(json.dumps(original))
        subprocess.run(command, check=True, env=env)
        assert json.loads(configuration.read_text()) == original, (
            "Installer changed user settings"
        )
        for parent in (".claude", ".agents"):
            assert (base / "skills" / parent / "skills/local-search/SKILL.md").is_file()
        app = base / "prefix with space/share/tgrep-ai-skill"
        manifest = json.loads((app / "install.json").read_text())
        runtime = Path(manifest["runtime"])
        fixture = base / "fixture"
        fixture.mkdir()
        (fixture / "sample.txt").write_text("installed_launcher_marker\n")
        subprocess.run(
            [manifest["launcher"], "add", "fixture", str(fixture)], check=True, env=env
        )
        search = subprocess.run(
            [
                manifest["launcher"],
                "search",
                "installed_launcher_marker",
                "--root",
                "fixture",
                "--fresh",
            ],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        assert len(json.loads(search.stdout)["matches"]) == 1
        tests_env = {
            **env,
            "PYTHONPATH": str(SOURCE / "src"),
            "LOCAL_SEARCH_INTEGRATION": "1",
            "LOCAL_SEARCH_TGREP": str(runtime / "bin/tgrep"),
            "LOCAL_SEARCH_RG": str(runtime / "bin/rg"),
        }
        subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(SOURCE / "tests"),
                "-v",
            ],
            check=True,
            env=tests_env,
            cwd=SOURCE,
        )
        subprocess.run(command + ["--uninstall"], check=True, env=env)
        assert not Path(manifest["launcher"]).exists()
        assert configuration.exists()
        print("Install, reinstall, real search and uninstall passed.")


if __name__ == "__main__":
    main()
