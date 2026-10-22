"""Arguments and dependency composition only; persistence and workflows live behind services."""
import argparse
import json
from pathlib import Path
import sys

from app.shared.db.migrations import upgrade_database
from app.shared.files import write_json

from .bootstrap import repositories
from .config import DEFAULT_DATASET, dataset_path, runtime_dir
from .services.export import CompanyExportService
from .services.ingestion import CompanyImportService
from .services.search import CompanySearchService


def main(argv=None):
    parser = argparse.ArgumentParser(description='Company snapshot import, embeddings and retrieval')
    commands = parser.add_subparsers(dest='command', required=True)

    db = commands.add_parser('db')
    db.add_argument('action', choices=['upgrade'])

    load = commands.add_parser('import', aliases=['load'], help='Validate and upsert the company JSON snapshot')
    load.add_argument('--data', type=dataset_path, default=DEFAULT_DATASET)
    load.add_argument('--report', type=Path, default=runtime_dir() / 'import-report.json')
    load.add_argument('--dry-run', action='store_true', help='Validate only; no database connection')

    embed = commands.add_parser('embed')
    embed.add_argument('--batch-size', type=int, default=16)
    embed.add_argument('--revision')
    embed.add_argument('--report', type=Path, default=runtime_dir() / 'embedding-report.json')

    query = commands.add_parser('search')
    query.add_argument('query')
    query.add_argument('--top-k', type=int, default=10)
    query.add_argument('--profile')
    query.add_argument('--output', type=Path)

    export = commands.add_parser('export')
    export.add_argument('--format', choices=['ingestion', 'ai'], default='ingestion')
    export.add_argument('--output', type=Path, default=runtime_dir() / 'companies.json')

    show = commands.add_parser('get')
    show.add_argument('company_id')
    show.add_argument('--output', type=Path)

    args = parser.parse_args(argv)

    if args.command == 'db':
        upgrade_database()
        return 0

    if args.command in ('import', 'load') and args.dry_run:
        report = CompanyImportService(None).import_file(args.data, dry_run=True)
        write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report['status'] == 'failed' else 0

    companies, vectors = repositories()

    if args.command in ('import', 'load'):
        service = CompanyImportService(companies)
        report = service.import_file(args.data)
        write_json(args.report, report)
        service.record_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report['status'] == 'failed' else 0

    if args.command == 'export':
        records = CompanyExportService(companies).export(ai=args.format == 'ai')
        write_json(args.output, records)
        print(json.dumps(dict(output=str(args.output), records=len(records))))
        return 0

    if args.command == 'embed':
        from app.shared.embeddings.e5 import E5Provider
        from .services.embedding import CompanyEmbeddingService
        result = CompanyEmbeddingService(vectors, E5Provider(revision=args.revision)).run(args.batch_size)
        write_json(args.report, result)
    elif args.command == 'search':
        profiles = vectors.list_profiles()
        profile = (next((item for item in profiles if item['id'] == args.profile), None)
                   if args.profile else profiles[0] if len(profiles) == 1 else None)
        if profile is None:
            raise ValueError('Select one stored embedding --profile; run embed first if none exist')
        from app.shared.embeddings.e5 import E5Provider
        from .services.embedding import CompanyEmbeddingService
        embeddings = CompanyEmbeddingService(vectors, E5Provider(revision=profile['revision']))
        if embeddings.profile != profile:
            raise ValueError('Stored embedding preparation is incompatible; regenerate embeddings')
        result = CompanySearchService(vectors, embeddings).search(args.query, args.top_k)
        if args.output:
            write_json(args.output, result)
    else:
        company = companies.get_company(args.company_id)
        if company is None:
            raise ValueError(f'Company not found: {args.company_id}')
        result = company.model_dump(mode='json')
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
