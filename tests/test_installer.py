import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "installer", Path(__file__).resolve().parents[1] / "scripts/install.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_checksum_failure_never_executes_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "archive.tar.gz").write_bytes(b"untrusted")
            entry = {"asset": "archive.tar.gz", "sha256": "0" * 64, "binary": "tgrep"}
            with patch.object(installer.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "SHA256"):
                    installer.download_binary(entry, directory / "bin/tgrep", directory)
                run.assert_not_called()

    def test_archive_paths_are_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            archive = directory / "archive.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                malicious = tarfile.TarInfo("../../escape")
                malicious.size = 4
                bundle.addfile(malicious, io.BytesIO(b"oops"))
                binary = tarfile.TarInfo("package/tgrep")
                binary.size = 4
                bundle.addfile(binary, io.BytesIO(b"tool"))
            entry = {
                "asset": archive.name,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "binary": "tgrep",
            }
            with patch.object(installer.subprocess, "run"):
                installer.download_binary(entry, directory / "bin/tgrep", directory)
            self.assertEqual((directory / "bin/tgrep").read_bytes(), b"tool")
            self.assertEqual(
                sorted(p.name for p in directory.iterdir()), ["archive.tar.gz", "bin"]
            )
