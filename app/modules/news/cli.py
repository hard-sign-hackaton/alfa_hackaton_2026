"""Arguments and dependency composition only; persistence and workflows live behind services."""
import argparse
import json
from pathlib import Path
import sys
from app.shared.config import runtime_dir
from app.shared.db.migrations import upgrade_database
from app.shared.files import write_json
from .bootstrap import repositories
from .config import Settings, period
from .parsers.registry import SOURCES
from .services.export import NewsExportService
from .services.ingestion import NewsIngestionService
from .services.search import NewsSearchService


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manual news collection, embeddings and retrieval')
    commands = parser.add_subparsers(dest='command', required=True)
    db = commands.add_parser('db')
    db.add_argument('action', choices=['upgrade'])
    collect = commands.add_parser('collect')
    collect.add_argument('--sources', nargs='+', choices=list(SOURCES), default=list(SOURCES))
    collect.add_argument('--from', dest='start')
    collect.add_argument('--to', dest='end')
    collect.add_argument('--days', type=int)
    collect.add_argument('--limit', type=int, help='Successful articles per source; omitted means no article limit')
    collect.add_argument('--max-requests', type=int, default=3000)
    collect.add_argument('--max-sitemaps', type=int, default=100)
    collect.add_argument('--timeout', type=float, default=20)
    collect.add_argument('--delay', type=float, default=1)
    collect.add_argument('--report', type=Path, default=runtime_dir() / 'collection-report.json')
    export = commands.add_parser('export')
    export.add_argument('--format', choices=['ingestion', 'ai'], default='ingestion')
    export.add_argument('--output', type=Path, default=runtime_dir() / 'news.json')
    embed = commands.add_parser('embed')
    embed.add_argument('--batch-size', type=int, default=16)
    embed.add_argument('--revision')
    embed.add_argument('--report', type=Path, default=runtime_dir() / 'embedding-report.json')
    query = commands.add_parser('search')
    query.add_argument('query')
    query.add_argument('--top-k', type=int, default=5)
    query.add_argument('--profile')
    query.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'db':
        upgrade_database()
        news, _ = repositories()
        news.seed([source.source for source in SOURCES.values()])
        return 0
    news, vectors = repositories()
    if args.command == 'collect':
        if args.limit is not None and args.limit <= 0:
            parser.error('--limit must be positive')
        start, end = period(args.start, args.end, args.days)
        settings = Settings(delay=args.delay, timeout=args.timeout,
            max_requests=args.max_requests, max_sitemaps=args.max_sitemaps)
        service = NewsIngestionService(news, [SOURCES[s] for s in dict.fromkeys(args.sources)], settings)
        result = service.collect(start, end, args.limit)
        write_json(args.report, result)
        service.record_reports(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if any(r['status'] == 'failed' for r in result['reports']) else 0
    if args.command == 'export':
        records = NewsExportService(news).export(ai=args.format == 'ai')
        write_json(args.output, records)
        print(json.dumps(dict(output=str(args.output), records=len(records))))
        return 0
    if args.command == 'embed':
        from app.shared.embeddings.e5 import E5Provider
        from .services.embedding import NewsEmbeddingService
        result = NewsEmbeddingService(vectors, E5Provider(revision=args.revision)).run(args.batch_size)
        write_json(args.report, result)
    else:
        profiles = vectors.list_profiles()
        profile = next((p for p in profiles if p['id'] == args.profile), None) if args.profile else profiles[0] if len(profiles) == 1 else None
        if profile is None:
            raise ValueError('Select one stored embedding --profile; run embed first if none exist')
        from app.shared.embeddings.e5 import E5Provider
        from .services.embedding import NewsEmbeddingService
        embeddings = NewsEmbeddingService(vectors, E5Provider(revision=profile['revision']))
        if embeddings.profile != profile:
            raise ValueError('Stored embedding preparation is incompatible; regenerate embeddings')
        result = NewsSearchService(vectors, embeddings).search(args.query, args.top_k)
        if args.output:
            write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def entrypoint():
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
