import argparse
import time
from pathlib import Path

from learning_agent import db
from learning_agent.config import DOCS_PATH
from learning_agent.core import indexing


def index_docs(docs_dir: Path, tags: list[str]) -> None:
    indexed = indexing.index_docs_dir(docs_dir, extra_tags=tags or None)
    if not indexed:
        print(f"No indexable files found in {docs_dir}")
        return
    for doc_id in indexed:
        print(f"Indexed: {doc_id}")
    print(f"Done. Indexed {len(indexed)} file(s).")


def index_single_file(path: Path, tags: list[str]) -> None:
    db.init_db()
    doc_id = indexing.index_file(path, tags or indexing.infer_tags(path))
    if doc_id:
        print(f"Indexed: {path.name} -> {doc_id}")
    else:
        print(f"Skipped: {path}")


def watch_docs(docs_dir: Path, interval: int) -> None:
    print(f"Watching {docs_dir} for changes (every {interval}s). Ctrl+C to stop.")
    mtimes: dict[str, float] = {}

    while True:
        for path in docs_dir.glob("**/*"):
            if not path.is_file():
                continue
            key = str(path)
            mtime = path.stat().st_mtime
            prev = mtimes.get(key)
            if prev is None:
                mtimes[key] = mtime
                doc_id = indexing.index_file(path)
                if doc_id:
                    print(f"[new] {path.name} -> {doc_id}")
            elif mtime > prev:
                mtimes[key] = mtime
                doc_id = indexing.index_file(path)
                if doc_id:
                    print(f"[updated] {path.name} -> {doc_id}")
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Learning Agent CLI")
    sub = parser.add_subparsers(dest="command")

    index_parser = sub.add_parser("index-docs", help="Index all docs in a folder")
    index_parser.add_argument("--dir", type=Path, default=DOCS_PATH)
    index_parser.add_argument("--tags", default="", help="Comma-separated tags")

    file_parser = sub.add_parser("index-file", help="Index a single file")
    file_parser.add_argument("path", type=Path)
    file_parser.add_argument("--tags", default="", help="Comma-separated tags")

    watch_parser = sub.add_parser("watch-docs", help="Watch docs folder and auto-index on change")
    watch_parser.add_argument("--dir", type=Path, default=DOCS_PATH)
    watch_parser.add_argument("--interval", type=int, default=5)

    sub.add_parser("init-db", help="Initialize the local database")

    sub.add_parser("bootstrap-curriculum", help="Complete all curriculum topics automatically")

    fetch_parser = sub.add_parser("fetch-learn", help="Fetch URL and index into knowledge base")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--title", default="")
    fetch_parser.add_argument("--tags", default="web,pesquisa")

    search_parser = sub.add_parser("search-web", help="Search the web via DuckDuckGo")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=5)

    learn_parser = sub.add_parser("search-learn", help="Search web and index top results")
    learn_parser.add_argument("query")
    learn_parser.add_argument("--limit", type=int, default=3)
    learn_parser.add_argument("--tags", default="web,pesquisa")

    sub.add_parser("run-proofs", help="Run full proof suite (real verification)")

    sub.add_parser(
        "supervise-ide-tests",
        help="Run full IDE test battery with agent supervision (pytest + vitest + e2e)",
    )

    distill_parser = sub.add_parser("distill", help="Knowledge Distillation: teacher -> student")
    distill_parser.add_argument("topic")
    distill_parser.add_argument("--context", default="")
    distill_parser.add_argument("--tags", default="distillation")

    sub.add_parser("distill-status", help="Show distillation configuration status")

    index_code_parser = sub.add_parser("index-codebase", help="Index source code with smart chunking")
    index_code_parser.add_argument("--dirs", default="learning_agent")

    ctx_parser = sub.add_parser("get-context", help="Aggregate context for a task")
    ctx_parser.add_argument("task")
    ctx_parser.add_argument("--limit", type=int, default=5)

    sub.add_parser("suggest-learning", help="Suggest topics for active learning")
    active_parser = sub.add_parser("active-learn", help="Run active learning")
    active_parser.add_argument("--max", type=int, default=3)

    sub.add_parser("export-training", help="Export JSONL for fine-tuning")
    sub.add_parser("create-modelfile", help="Generate Ollama Modelfile")

    repo_parser = sub.add_parser("learn-repo", help="Learn from GitHub repo")
    repo_parser.add_argument("url")

    rss_parser = sub.add_parser("learn-rss", help="Learn from RSS feed")
    rss_parser.add_argument("url")
    rss_parser.add_argument("--limit", type=int, default=5)

    sub.add_parser("telegram-bot", help="Start Telegram bot (requires TELEGRAM_BOT_TOKEN)")

    sub.add_parser("sync-test", help="Test Supabase connection")
    sub.add_parser("sync-push", help="Push local data to Supabase")
    sub.add_parser("sync-pull", help="Pull data from Supabase to local")

    args = parser.parse_args()

    if args.command == "index-docs":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        index_docs(args.dir, tags)
    elif args.command == "index-file":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        index_single_file(args.path, tags)
    elif args.command == "watch-docs":
        watch_docs(args.dir, args.interval)
    elif args.command == "init-db":
        db.init_db()
        print("Database initialized.")
    elif args.command == "bootstrap-curriculum":
        from learning_agent.bootstrap_curriculum import main as bootstrap_main

        bootstrap_main()
    elif args.command == "fetch-learn":
        from learning_agent.core import web
        import json

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        result = web.fetch_and_learn(args.url, title=args.title, tags=tags)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "search-web":
        from learning_agent.core import web
        import json

        print(json.dumps(web.search_web(args.query, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "search-learn":
        from learning_agent.core import web
        import json

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        print(json.dumps(web.search_and_learn(args.query, args.limit, tags), ensure_ascii=False, indent=2))
    elif args.command == "distill":
        from learning_agent.core import distillation
        import json

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        result = distillation.distill_topic(args.topic, context=args.context, tags=tags)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "index-codebase":
        from learning_agent.core import codebase
        import json

        dirs = [d.strip() for d in args.dirs.split(",") if d.strip()]
        print(json.dumps(codebase.index_codebase(dirs), ensure_ascii=False, indent=2))
    elif args.command == "get-context":
        from learning_agent.core import context
        import json

        print(json.dumps(context.get_context_for_task(args.task, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "suggest-learning":
        from learning_agent.core import active_learning
        import json

        print(json.dumps(active_learning.suggest_learning(), ensure_ascii=False, indent=2))
    elif args.command == "active-learn":
        from learning_agent.core import active_learning
        import json

        print(json.dumps(active_learning.run_active_learning(args.max), ensure_ascii=False, indent=2))
    elif args.command == "export-training":
        from learning_agent.core import finetune
        import json

        print(json.dumps(finetune.export_training_data(), ensure_ascii=False, indent=2))
    elif args.command == "create-modelfile":
        from learning_agent.core import finetune
        import json

        print(json.dumps(finetune.create_modelfile(), ensure_ascii=False, indent=2))
    elif args.command == "learn-repo":
        from learning_agent.core import sources
        import json

        print(json.dumps(sources.learn_from_repo(args.url), ensure_ascii=False, indent=2))
    elif args.command == "learn-rss":
        from learning_agent.core import sources
        import json

        print(json.dumps(sources.learn_from_rss(args.url, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "telegram-bot":
        from learning_agent.channels.telegram_bot import main as telegram_main

        telegram_main()
    elif args.command == "distill-status":
        from learning_agent.core import distillation
        import json

        print(json.dumps(distillation.get_status(), ensure_ascii=False, indent=2))
    elif args.command == "run-proofs":
        from learning_agent.core import proofs
        import json

        print(json.dumps(proofs.run_full_proof_suite(), ensure_ascii=False, indent=2))
    elif args.command == "supervise-ide-tests":
        from learning_agent.scripts.run_ide_test_supervision import main as supervise_main
        import asyncio

        raise SystemExit(asyncio.run(supervise_main()))
    elif args.command == "sync-test":
        from learning_agent import sync
        import json

        print(json.dumps(sync.test_connection(), ensure_ascii=False, indent=2))
    elif args.command == "sync-push":
        from learning_agent import sync
        import json

        print(json.dumps(sync.push_to_cloud(), ensure_ascii=False, indent=2))
    elif args.command == "sync-pull":
        from learning_agent import sync
        import json

        print(json.dumps(sync.pull_from_cloud(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
