"""CLI for importing, inspecting and searching analytical materials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.shared.db.migrations import upgrade_database
from app.shared.files import write_json

from .bootstrap import repositories
from .config import parse_time, runtime_dir
from .services.importing import AnalyticsImportService
from .services.search import AnalyticsSearchService


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Import and search Alfa-Bank analytical materials'
    )
    commands = parser.add_subparsers(dest='command', required=True)

    db = commands.add_parser('db')
    db.add_argument('action', choices=['upgrade'])

    importer = commands.add_parser('import')
    importer.add_argument('--extracted', type=Path, required=True,
                          help='Directory with extracted JSON files')
    importer.add_argument('--manifest', type=Path,
                          help='Manifest with canonical document metadata')
    importer.add_argument('--chunks', type=Path,
                          help='chunks.jsonl path; defaults to <extracted>/chunks.jsonl')
    importer.add_argument('--source-root', type=Path,
                          help='Store source paths relative to this directory')
    importer.add_argument('--report', type=Path,
                          default=runtime_dir() / 'import-report.json')

    listing = commands.add_parser('list')
    listing.add_argument('--doc-type')
    listing.add_argument('--as-of', type=parse_time)
    listing.add_argument('--limit', type=int, default=100)

    show = commands.add_parser('show')
    show.add_argument('document_id')
    show.add_argument('--markdown', action='store_true',
                      help='Include the full extracted Markdown')

    stats = commands.add_parser('stats')

    profiles = commands.add_parser('profiles')

    embed = commands.add_parser('embed')
    embed.add_argument('--batch-size', type=int, default=16)
    embed.add_argument('--revision')
    embed.add_argument('--report', type=Path,
                       default=runtime_dir() / 'embedding-report.json')

    search = commands.add_parser('search')
    search.add_argument('query')
    search.add_argument('--top-k', type=int, default=5)
    search.add_argument('--mode', choices=['text', 'vector'], default='text')
    search.add_argument('--profile')
    search.add_argument('--as-of', type=parse_time)
    search.add_argument('--per-document', type=int, default=2)
    search.add_argument('--output', type=Path)

    args = parser.parse_args(argv)
    if args.command == 'db':
        upgrade_database()
        return 0

    documents, vectors = repositories()

    if args.command == 'import':
        result = AnalyticsImportService(documents).run(
            args.extracted,
            manifest_path=args.manifest,
            chunks_path=args.chunks,
            source_root=args.source_root,
        )
        write_json(args.report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == 'list':
        result = documents.list_documents(
            doc_type=args.doc_type, as_of=args.as_of, limit=args.limit
        )
    elif args.command == 'show':
        document = documents.get_document(
            args.document_id, include_markdown=args.markdown
        )
        if document is None:
            raise ValueError(f'Document not found: {args.document_id}')
        document['chunks'] = documents.get_chunks(args.document_id)
        document['tables'] = documents.get_tables(args.document_id)
        result = document
    elif args.command == 'stats':
        result = documents.stats()
    elif args.command == 'profiles':
        result = vectors.list_profiles()
    elif args.command == 'embed':
        from app.shared.embeddings.e5 import E5Provider

        from .services.embedding import AnalyticsEmbeddingService

        result = AnalyticsEmbeddingService(
            vectors, E5Provider(revision=args.revision)
        ).run(args.batch_size)
        write_json(args.report, result)
    else:
        embeddings = None
        if args.mode == 'vector':
            from app.shared.embeddings.e5 import E5Provider

            from .services.embedding import AnalyticsEmbeddingService

            profiles = vectors.list_profiles()
            usable = [
                item for item in profiles if item.get('embeddings', 0) > 0
            ]
            if args.profile:
                profile = next(
                    (item for item in profiles if item['id'] == args.profile), None
                )
            else:
                profile = usable[0] if len(usable) == 1 else None
            if profile is None:
                raise ValueError(
                    'Select one stored embedding --profile; run embed first if none exist'
                )
            embeddings = AnalyticsEmbeddingService(
                vectors, E5Provider(revision=profile['revision'])
            )
            if embeddings.profile['id'] != profile['id']:
                raise ValueError(
                    'Stored embedding preparation is incompatible; regenerate embeddings'
                )
        result = AnalyticsSearchService(documents, embeddings).search(
            args.query,
            args.top_k,
            as_of=args.as_of,
            mode=args.mode,
            per_document=args.per_document,
        )
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
