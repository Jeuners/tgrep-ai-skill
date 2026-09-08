"""Shared CLI entry point for humans, Claude Code and Codex."""

import argparse
import json
import os
import sys

from . import __version__, engine, llm
from .config import (
    SearchError,
    add_root,
    config_dir,
    index_dir,
    load,
    lock,
    save,
    select_roots,
)


def emit(value):
    print(json.dumps(value, ensure_ascii=True, indent=2))


def positive(value):
    number = int(value)
    if not 1 <= number <= 1000:
        raise argparse.ArgumentTypeError("Choose a number between 1 and 1000.")
    return number


def parser():
    cli = argparse.ArgumentParser(
        description="Indexed local search for Claude Code and Codex"
    )
    cli.add_argument("--version", action="version", version=__version__)
    sub = cli.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="Register a directory without indexing it")
    add.add_argument("name")
    add.add_argument("path")
    add.add_argument("--exclude", action="append", default=[], metavar="DIRECTORY_NAME")
    add.add_argument("--max-filesize", default="8M")
    for name in ("preview", "index", "start", "stop", "remove"):
        command = sub.add_parser(name)
        command.add_argument("name")
    sub.add_parser("status", help="Show all registered roots and index status")
    sub.add_parser("doctor", help="Check binaries, Ollama and the configured model")
    model = sub.add_parser("model", help="Select an already installed Ollama model")
    model.add_argument("name")
    for name in ("search", "ask"):
        query = sub.add_parser(name)
        query.add_argument("query")
        roots = query.add_mutually_exclusive_group()
        roots.add_argument("--root", action="append")
        roots.add_argument("--all", action="store_true")
        query.add_argument("--limit", type=positive, default=40)
        query.add_argument(
            "--fresh", action="store_true", help="Use a fresh ripgrep scan"
        )
        query.add_argument(
            "--paths-only", action="store_true", help="Return no excerpts or answer"
        )
        if name == "search":
            query.add_argument("--regex", action="store_true")
    return cli


def query_roots(roots, queries, regex, limit, fresh):
    matches = {}
    reports = []
    for name, root in roots:
        for query in queries:
            result = engine.search(root, query, regex=regex, limit=limit, fresh=fresh)
            for match in result.pop("matches"):
                matches[(match["path"], match["line"])] = match
            reports.append({"root": name, "query": query, **result})
    ordered = sorted(matches.values(), key=lambda m: (m["path"], m["line"]))
    return {
        "matches": ordered[:limit],
        "reports": reports,
        "truncated": len(ordered) > limit or any(r["truncated"] for r in reports),
    }


def run(args):
    if args.command == "add":
        emit(add_root(args.name, args.path, args.exclude, args.max_filesize))
        return 0
    config = load()
    if args.command == "status":
        emit({name: engine.status(root) for name, root in config["roots"].items()})
        return 0
    if args.command == "doctor":
        report = {
            "version": __version__,
            "config": str(config_dir() / "config.json"),
            "model": config["model"],
        }
        healthy = True
        for tool in ("tgrep", "rg"):
            try:
                report[tool] = engine.binary(tool)
            except SearchError as error:
                report[tool] = str(error)
                healthy = False
        try:
            models = llm.request(config, "/api/tags").get("models", [])
            report["model_installed"] = any(
                m.get("name") == config["model"] for m in models
            )
            if report["model_installed"]:
                llm.require_local_model(config)
                report["model_local"] = True
            healthy = healthy and report["model_installed"]
        except SearchError as error:
            report["ollama"] = str(error)
            healthy = False
        emit(report)
        return 0 if healthy else 2
    if args.command == "model":
        models = llm.request(config, "/api/tags").get("models", [])
        if not any(m.get("name") == args.name for m in models):
            raise SearchError(
                "Model is not installed; use ollama list / ollama pull first."
            )
        llm.require_local_model({**config, "model": args.name})
        with lock(config_dir() / "config.lock"):
            config = load()
            config["model"] = args.name
            save(config)
        emit({"model": args.name})
        return 0
    if args.command in ("preview", "index", "start", "stop", "remove"):
        _, root = select_roots(config, [args.name])[0]
        if args.command == "preview":
            emit(engine.preview(root))
        elif args.command in ("index", "start"):
            emit(engine.start(root, rebuild=args.command == "index"))
        elif args.command == "stop":
            engine.stop(root)
            emit({"stopped": args.name})
        else:
            engine.stop(root)
            with lock(config_dir() / "config.lock"):
                config = load()
                del config["roots"][args.name]
                save(config)
            emit({"removed": args.name, "index_preserved": str(index_dir(root))})
        return 0
    if not args.query.strip() or len(args.query) > 4000:
        raise SearchError("Query must contain between 1 and 4000 characters.")
    roots = select_roots(config, args.root, args.all)
    queries = (
        llm.plan_queries(config, args.query) if args.command == "ask" else [args.query]
    )
    result = query_roots(
        roots, queries, getattr(args, "regex", False), args.limit, args.fresh
    )
    result["queries"] = queries
    if args.command == "ask" and not args.paths_only:
        result["answer"], result["sources"] = llm.answer(
            config, args.query, result["matches"]
        )
    if args.paths_only:
        result["matches"] = [
            {"path": m["path"], "line": m["line"]} for m in result["matches"]
        ]
    emit(result)
    return 0 if result["matches"] else 1


def main():
    os.umask(0o077)
    args = parser().parse_args()
    try:
        code = run(args)
    except (SearchError, OSError, ValueError, KeyError) as error:
        print(f"local-search: {error}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
