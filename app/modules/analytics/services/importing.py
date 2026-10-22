"""Import extracted PDFs and semantic chunks into analytics storage."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..dto import ChunkRecord, DocumentRecord, ManifestEntry, TableRecord
from ..identity import (
    document_id as make_document_id,
    first_heading,
    parse_published_at,
    sha256_text,
)
from ..manifest import load_manifest, manifest_index, source_stem

VALID_KINDS = {'text', 'table', 'mixed'}


def _read_document(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'Extraction must be an object: {path}')
    return payload


def _read_chunks(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        raise ValueError(f'Chunks file not found: {path}')
    grouped: dict[str, list[dict[str, Any]]] = {}
    aliases: dict[str, str] = {}
    with path.open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Invalid chunk JSON at {path}:{line_number}: {exc}') from exc
            if not isinstance(chunk, dict):
                raise ValueError(f'Chunk must be an object at {path}:{line_number}')
            key = chunk.get('doc_id') or chunk.get('source_name') or chunk.get('source_pdf')
            if not key:
                raise ValueError(f'Chunk without doc_id/source_name at {path}:{line_number}')
            primary = source_stem(str(key))
            grouped.setdefault(primary, []).append(chunk)
            for field in ('source_name', 'source_pdf'):
                alias = chunk.get(field)
                if alias:
                    alias = source_stem(str(alias))
                    if alias != primary:
                        aliases[alias] = primary
    for alias, primary in aliases.items():
        if alias not in grouped:
            grouped[alias] = grouped[primary]
    return grouped


def _relative_uri(value: str | None, source_root: Path | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if source_root is not None and path.is_absolute():
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix() if path.is_absolute() else value.replace('\\', '/')


def _embedding_text(title: str, section_path: list[str], text: str) -> str:
    context = [f'Документ: {title}']
    if section_path:
        context.append('Раздел: ' + ' > '.join(section_path))
    return '\n'.join(context) + '\n\n' + text


def _chunk_records(
    document: DocumentRecord,
    chunks: list[dict[str, Any]],
) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    used_ids: set[str] = set()
    for ordinal, raw in enumerate(chunks):
        text = str(raw.get('text') or '').strip()
        if not text:
            continue
        kind = str(raw.get('kind') or 'text')
        if kind not in VALID_KINDS:
            kind = 'text'
        section_path = [
            str(item).strip()
            for item in (raw.get('section_path') or [])
            if str(item).strip()
        ]
        digest = sha256_text(text)
        chunk_key = f'{document.id}#{digest[:16]}'
        if chunk_key in used_ids:
            chunk_key = f'{chunk_key}-{ordinal}'
        used_ids.add(chunk_key)

        embedding_text = str(raw.get('embedding_text') or '').strip()
        if not embedding_text:
            embedding_text = _embedding_text(document.title, section_path, text)

        pages = sorted({
            int(page)
            for page in (raw.get('pages') or [])
            if isinstance(page, (int, float, str)) and str(page).isdigit() and int(page) > 0
        })
        table_refs = []
        for item in (raw.get('tables') or []):
            if not isinstance(item, dict):
                continue
            reference = dict(item)
            table_key = str(reference.get('id') or '')
            if table_key and not table_key.startswith(f'{document.id}#'):
                reference['id'] = f'{document.id}#{table_key}'
            table_refs.append(reference)
        size = int(raw.get('size') or 0)
        records.append(
            ChunkRecord(
                id=chunk_key,
                document_id=document.id,
                ordinal=len(records),
                kind=kind,
                section_path=section_path,
                text=text,
                embedding_text=embedding_text,
                content_hash=digest,
                input_hash=sha256_text(embedding_text),
                chars=len(text),
                size=size,
                pages=pages,
                page_from=pages[0] if pages else None,
                page_to=pages[-1] if pages else None,
                table_refs=table_refs,
                meta={
                    'oversized': bool(raw.get('oversized')),
                    'source_chunk_id': raw.get('id'),
                    'source_size': raw.get('size'),
                },
            )
        )
    return records


def _table_records(document: DocumentRecord, tables: list[dict[str, Any]]) -> list[TableRecord]:
    records: list[TableRecord] = []
    for index, raw in enumerate(tables, 1):
        if not isinstance(raw, dict):
            continue
        table_id = str(raw.get('id') or f'table-{index}')
        rows = raw.get('rows') or []
        source = raw.get('source') or {}
        warnings = [
            str(item) for item in (raw.get('warnings') or []) if str(item).strip()
        ]
        page = source.get('page') if isinstance(source, dict) else None
        if page is not None:
            try:
                page = int(page)
            except (TypeError, ValueError):
                page = None
        canonical = json.dumps(
            {'rows': rows, 'source': source}, ensure_ascii=False, sort_keys=True
        )
        records.append(
            TableRecord(
                id=f'{document.id}#{table_id}',
                document_id=document.id,
                table_id=table_id,
                page=page,
                nrows=int(raw.get('nrows') or len(rows)),
                ncols=int(raw.get('ncols') or (len(rows[0]) if rows else 0)),
                rows=rows,
                source=source,
                warnings=warnings,
                content_hash=sha256_text(canonical),
            )
        )
    return records


def _document_record(
    path: Path,
    raw: dict[str, Any],
    entry: ManifestEntry | None,
    source_root: Path | None,
    collected_at: datetime,
) -> DocumentRecord:
    source_name = (
        (entry.source_name if entry else None)
        or raw.get('source_name')
        or Path(str(raw.get('source_pdf') or path.name)).name
    )
    markdown = str(raw.get('markdown') or '')
    title = (entry.title if entry else None) or raw.get('title') or first_heading(markdown)
    if not title:
        raise ValueError(f'{path.name}: document title is missing; set it in the manifest')
    published_at = (
        (entry.published_at if entry else None)
        or parse_published_at(markdown)
    )
    if published_at is None:
        raise ValueError(
            f'{path.name}: publication date is missing; set published_at in the manifest'
        )
    doc_id = make_document_id(source_name, entry.id if entry else None)
    subtitle = (entry.subtitle if entry else None)
    if subtitle is None:
        subtitle = raw.get('subtitle')
    source_value = str(raw.get('source_pdf') or source_name)
    source_sha256 = raw.get('source_sha256') or (entry.source_sha256 if entry else None)
    if source_sha256 is not None:
        source_sha256 = str(source_sha256).lower()
        if len(source_sha256) != 64:
            source_sha256 = None
    source_bytes = raw.get('source_bytes')
    if source_bytes is None and entry is not None:
        source_bytes = entry.source_bytes
    extraction = {
        key: raw[key]
        for key in (
            'schema_version',
            'title',
            'subtitle',
            'headings',
            'pages_processed',
            'skipped_pages',
            'warnings',
            'extractor',
        )
        if key in raw
    }
    extraction['tables_count'] = len(raw.get('tables') or [])
    meta = dict(entry.metadata) if entry else {}
    meta.update({
        'source_stem': source_stem(source_name),
        'ignore_headings': list(entry.ignore_headings) if entry else [],
        'manifest_id': entry.id if entry else None,
    })
    return DocumentRecord(
        id=doc_id,
        title=title,
        subtitle=subtitle,
        doc_type=entry.doc_type if entry else 'analytics',
        published_at=published_at,
        language=entry.language if entry else 'ru',
        tags=list(entry.tags) if entry else [],
        source_name=source_name,
        source_uri=_relative_uri(source_value, source_root),
        source_sha256=source_sha256,
        source_bytes=int(source_bytes) if source_bytes is not None else None,
        page_count=int(raw['page_count']) if raw.get('page_count') is not None else None,
        markdown=markdown,
        content_hash=sha256_text(markdown),
        extraction=extraction,
        meta=meta,
        collected_at=collected_at,
    )


class AnalyticsImportService:
    def __init__(self, repository):
        self.repository = repository

    def run(
        self,
        extracted_dir: Path,
        *,
        manifest_path: Path | None = None,
        chunks_path: Path | None = None,
        source_root: Path | None = None,
    ) -> dict[str, Any]:
        extracted = Path(extracted_dir)
        if not extracted.is_dir():
            raise ValueError(f'Extracted directory not found: {extracted}')
        if manifest_path is None and (extracted / 'manifest.json').is_file():
            manifest_path = extracted / 'manifest.json'
        manifest = load_manifest(manifest_path)
        entries = manifest_index(manifest)
        chunks_path = Path(chunks_path) if chunks_path else extracted / 'chunks.jsonl'
        chunks_by_document = _read_chunks(chunks_path)

        document_files = [
            path for path in sorted(extracted.glob('*.json'))
            if path.name != 'manifest.json' and not path.name.endswith('.chunks.json')
        ]
        if not document_files:
            raise ValueError(f'No extracted documents found in {extracted}')

        started_at = datetime.now(timezone.utc)
        report: dict[str, Any] = {
            'extracted_dir': str(extracted),
            'manifest_path': str(manifest_path) if manifest_path else None,
            'chunks_path': str(chunks_path),
            'source_root': str(source_root) if source_root else None,
            'documents': [],
            'warnings': [],
            'status': 'running',
        }
        try:
            for path in document_files:
                raw = _read_document(path)
                source_name = (
                    raw.get('source_name')
                    or Path(str(raw.get('source_pdf') or path.name)).name
                )
                stem = source_stem(source_name)
                entry = (
                    entries.get(source_name)
                    or entries.get(stem)
                    or entries.get(str(raw.get('id') or ''))
                )
                if entry is None:
                    report['warnings'].append(
                        f'{source_name}: no manifest entry; metadata was inferred from the extraction'
                    )
                document = _document_record(
                    path, raw, entry, source_root, started_at
                )
                chunks = chunks_by_document.get(stem, [])
                if not chunks:
                    report['warnings'].append(f'{source_name}: no chunks found')
                chunk_records = _chunk_records(document, chunks)
                table_records = _table_records(
                    document, raw.get('tables') or []
                )
                result = self.repository.save_document(
                    document, chunk_records, table_records
                )
                report['documents'].append({
                    'id': document.id,
                    'source_name': document.source_name,
                    **result,
                })
            report['summary'] = {
                'documents': len(report['documents']),
                'chunks': sum(item['chunks'] for item in report['documents']),
                'tables': sum(item['tables'] for item in report['documents']),
            }
            report['status'] = 'ok'
        except Exception as exc:
            report['status'] = 'failed'
            report['error'] = str(exc)
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            report['started_at'] = started_at.isoformat()
            try:
                self.repository.record_run(report)
            except Exception:
                pass
            raise

        report['started_at'] = started_at.isoformat()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        self.repository.record_run(report)
        return report
