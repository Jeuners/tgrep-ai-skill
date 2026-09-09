import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from local_search import cli, config, engine, llm


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.env = patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.base / "config"),
                "XDG_DATA_HOME": str(self.base / "data"),
            },
        )
        self.env.start()
        self.root_path = self.base / "Project space ä"
        self.root_path.mkdir()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()


class RegistryTests(IsolatedTest):
    def test_registration_is_idempotent_and_policy_conflicts_fail(self):
        first = config.add_root("demo", self.root_path)
        self.assertEqual(first, config.add_root("demo", self.root_path))
        with self.assertRaises(config.SearchError):
            config.add_root("demo", self.root_path, max_size="16M")
        with self.assertRaises(config.SearchError):
            config.add_root("alias", self.root_path)
        self.assertFalse(config.index_dir(first).exists())

    def test_most_specific_root_and_explicit_all(self):
        inner = self.root_path / "inner"
        inner.mkdir()
        config.add_root("outer", self.root_path)
        config.add_root("inner", inner)
        with patch("pathlib.Path.cwd", return_value=inner):
            self.assertEqual(config.select_roots(config.load())[0][0], "inner")
        self.assertEqual(len(config.select_roots(config.load(), all_roots=True)), 2)

    def test_exclusion_injection_rejected_and_policy_changes_index(self):
        for bad in ("../outside", "*", "foo\nbar"):
            with self.assertRaises(config.SearchError):
                config.add_root("bad", self.root_path, [bad])
        root = config.add_root("demo", self.root_path)
        self.assertNotEqual(
            config.index_dir(root), config.index_dir({**root, "max_filesize": "16M"})
        )

    def test_corrupt_config_does_not_reset_it(self):
        path = config.config_dir() / "config.json"
        path.parent.mkdir(parents=True)
        path.write_text("broken")
        with self.assertRaises(config.SearchError):
            config.load()
        self.assertEqual(path.read_text(), "broken")


class LLMTests(unittest.TestCase):
    def test_cloud_model_is_rejected_before_chat(self):
        for metadata in (
            {"remote_model": "cloud-model", "model_info": {}},
            {"remote_host": "https://ollama.com", "model_info": {}},
            {"model_info": {}},
        ):
            with patch.object(llm, "request", return_value=metadata) as request:
                with self.assertRaises(config.SearchError):
                    llm.chat({"model": "alias"}, "system", "private content")
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.args[1], "/api/show")

    def test_remote_urls_and_credentials_rejected(self):
        for url in (
            "https://example.com",
            "http://localhost:11434",
            "http://user@127.0.0.1:11434",
            "http://127.0.0.1:11434/api",
        ):
            with self.assertRaises(config.SearchError):
                llm.endpoint({"ollama_url": url}, "/api/chat")

    def test_query_validation_and_deduplication(self):
        with patch.object(llm, "chat", return_value='{"queries":["auth","auth"]}'):
            self.assertEqual(llm.plan_queries({}, "login?"), ["auth"])
        for answer in (
            '{"queries":[]}',
            '{"queries":[null]}',
            '{"queries":["a","b","c","d"]}',
            "not json",
        ):
            with patch.object(llm, "chat", return_value=answer):
                with self.assertRaises(config.SearchError):
                    llm.plan_queries({}, "login?")

    def test_answer_sources_are_bounded_and_empty_skips_model(self):
        with patch.object(llm, "chat", return_value="Answer [1]") as chat:
            matches = [{"path": "/a", "line": i, "text": "x" * 2000} for i in range(40)]
            answer, sources = llm.answer({}, "question", matches)
            self.assertLess(len(sources), 10)
            self.assertEqual(answer, "Answer [1]")
            self.assertLess(len(chat.call_args.args[2]), 12500)
        with patch.object(llm, "chat") as chat:
            llm.answer({}, "question", [])
            chat.assert_not_called()


class ProcessTests(unittest.TestCase):
    def test_large_output_is_bounded(self):
        data, truncated, _ = engine.collect(
            [sys.executable, "-c", "print('x' * 100000)"], byte_limit=1024
        )
        self.assertEqual(len(data), 1024)
        self.assertTrue(truncated)

    def test_timeout_terminates_child(self):
        with self.assertRaises(config.SearchError):
            engine.collect(
                [sys.executable, "-c", "import time; time.sleep(3)"], timeout=0.1
            )

    def test_errors_are_not_empty_results(self):
        with self.assertRaisesRegex(config.SearchError, "broken"):
            engine.collect(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('broken',file=sys.stderr); sys.exit(2)",
                ]
            )


class RoutingTests(IsolatedTest):
    def test_counts_preserve_root_dropped_by_global_limit(self):
        first = {"path": "/a/first.py", "line": 1, "text": "needle"}
        last = {"path": "/z/last.py", "line": 1, "text": "needle"}
        with patch.object(
            engine,
            "search",
            side_effect=[
                {"matches": [first], "truncated": False},
                {"matches": [last], "truncated": True},
            ],
        ):
            result = cli.query_roots(
                [("first", {}), ("last", {})], ["needle"], False, 1, True
            )
        self.assertEqual(result["matches"], [first])
        self.assertTrue(result["truncated"])
        self.assertEqual(
            [(r["root"], r["match_count"]) for r in result["reports"]],
            [("first", 1), ("last", 1)],
        )
        self.assertTrue(result["reports"][1]["truncated"])

    def test_per_root_counts_survive_deduplication(self):
        match = {"path": "/shared/file.py", "line": 1, "text": "needle"}
        with patch.object(
            engine,
            "search",
            side_effect=[
                {"matches": [match], "truncated": False},
                {"matches": [match], "truncated": False},
            ],
        ):
            result = cli.query_roots(
                [("parent", {}), ("child", {})], ["needle"], False, 1, True
            )
        self.assertEqual(result["matches"], [match])
        self.assertEqual([r["match_count"] for r in result["reports"]], [1, 1])
        self.assertFalse(result["truncated"])

    def test_pid_conflict_reports_recovery_without_signaling(self):
        root = config.add_root("demo", self.root_path)
        directory = config.index_dir(root)
        config.atomic_json(
            directory / "owner.json", {"pid": 1234, "binary": "/bin/tgrep"}
        )
        with (
            patch.object(
                engine.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, "/bin/unrelated\n"),
            ),
            patch.object(engine.os, "kill") as kill,
        ):
            with self.assertRaises(config.SearchError) as error:
                engine.stop(root)
            self.assertIn("1234", str(error.exception))
            self.assertIn(str(directory / "owner.json"), str(error.exception))
            kill.assert_not_called()
        self.assertTrue((directory / "owner.json").exists())

    def test_slow_start_is_preserved(self):
        root = config.add_root("demo", self.root_path)
        with (
            patch.object(engine, "rpc_status", return_value=None),
            patch.object(engine, "owned_pid", return_value=1234),
            patch.object(engine, "_stop") as stop,
            patch.object(engine.subprocess, "Popen") as spawn,
        ):
            with self.assertRaisesRegex(config.SearchError, "still starting"):
                engine.start(root)
            stop.assert_not_called()
            spawn.assert_not_called()

    def test_partial_index_uses_fresh_scan(self):
        root = config.add_root("demo", self.root_path)
        with (
            patch.object(engine, "start", return_value={"indexing": True}),
            patch.object(engine, "binary", side_effect=lambda name: name),
            patch.object(engine, "collect", return_value=(b"", False, "")) as collect,
        ):
            result = engine.search(root, "anything")
            self.assertEqual(result["backend"], "rg")
            self.assertEqual(collect.call_args.args[0][0], "rg")
            self.assertTrue(result["warnings"])

    def test_paths_only_does_not_generate_answer_or_return_excerpts(self):
        config.add_root("demo", self.root_path)
        args = cli.parser().parse_args(
            ["ask", "question", "--root", "demo", "--paths-only"]
        )
        with (
            patch.object(llm, "plan_queries", return_value=["auth"]),
            patch.object(llm, "answer") as answer,
            patch.object(
                cli,
                "query_roots",
                return_value={
                    "matches": [{"path": "/a", "line": 1, "text": "private excerpt"}],
                    "reports": [],
                    "truncated": False,
                },
            ),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.run(args), 0)
            answer.assert_not_called()
            self.assertNotIn("private excerpt", output.getvalue())


@unittest.skipUnless(
    os.environ.get("LOCAL_SEARCH_INTEGRATION") == "1", "real binaries opt-in"
)
class IntegrationTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.root = config.add_root("demo", self.root_path, ["vendor"])
        (self.root_path / "auth.py").write_text(
            "def login():\n    return 'session_token'\n"
        )
        (self.root_path / "vendor").mkdir()
        (self.root_path / "vendor/ignored.py").write_text("session_token\n")
        (self.root_path / ".env").write_text("session_token\n")
        (self.root_path / ".gitignore").write_text("ignored.txt\n")
        (self.root_path / "ignored.txt").write_text("session_token\n")

    def tearDown(self):
        try:
            engine.stop(self.root)
        finally:
            super().tearDown()

    def ready(self):
        engine.start(self.root)
        for _ in range(100):
            server = engine.rpc_status(config.index_dir(self.root))
            if (
                server
                and not server.get("indexing", True)
                and not server.get("reconcile_running")
            ):
                return
            time.sleep(0.1)
        self.fail("server did not become ready")

    def test_index_matches_fresh_and_updates_and_restarts(self):
        self.ready()
        indexed = engine.search(self.root, "session_token")
        fresh = engine.search(self.root, "session_token", fresh=True)
        self.assertEqual(indexed["backend"], "tgrep")
        self.assertEqual(indexed["matches"], fresh["matches"])
        self.assertEqual(len(indexed["matches"]), 1)
        (self.root_path / "new ä.txt").write_text("unique_marker\n")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = engine.search(self.root, "unique_marker")
            if result["matches"]:
                break
            time.sleep(0.2)
        self.assertEqual(len(result["matches"]), 1)
        (self.root_path / "new ä.txt").rename(self.root_path / "renamed.txt")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = engine.search(self.root, "unique_marker")
            if result["matches"] and result["matches"][0]["path"].endswith(
                "renamed.txt"
            ):
                break
            time.sleep(0.2)
        self.assertTrue(result["matches"][0]["path"].endswith("renamed.txt"))
        engine.stop(self.root)
        self.ready()
        self.assertEqual(len(engine.search(self.root, "session_token")["matches"]), 1)

    def test_overlap_dedup_regex_no_matches_and_literal_option(self):
        self.ready()
        result = cli.query_roots(
            [("a", self.root), ("b", self.root)], ["login|session"], True, 20, False
        )
        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual(engine.search(self.root, "--option")["matches"], [])
        self.assertEqual(engine.search(self.root, "absent", fresh=True)["matches"], [])
        self.assertGreater(engine.preview(self.root)["files"], 0)

    def test_rebuild_and_stop(self):
        engine.start(self.root, rebuild=True)
        self.ready()
        self.assertEqual(len(engine.search(self.root, "session_token")["matches"]), 1)
        engine.stop(self.root)
        self.assertIsNone(engine.rpc_status(config.index_dir(self.root)))


if __name__ == "__main__":
    unittest.main()
