"""Import prepared JSONL without pretending to have the original PDF extraction."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ..manifest import load_manifest, manifest_index, source_stem
from .importing import _chunk_records, _document_record


class ChunkFileImportService:
    def __init__(self, repository):
        self.repository = repository

    def run(self, chunks_path: Path, *, manifest_path: Path):
        chunks_path, manifest_path = Path(chunks_path), Path(manifest_path)
        entries = manifest_index(load_manifest(manifest_path))
        grouped, seen = {}, set()
        payload = chunks_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        for number, line in enumerate(payload.decode('utf-8-sig').splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except ValueError:
                raise ValueError(f'Invalid chunk JSON on line {number}') from None
            if not isinstance(raw, dict) or not isinstance(raw.get('text'), str) or not raw['text'].strip():
                raise ValueError(f'Nonempty chunk text required on line {number}')
            source_name = str(raw.get('source_name') or raw.get('doc_id') or '')
            entry = entries.get(source_name) or entries.get(source_stem(source_name))
            if entry is None or entry.published_at is None or not entry.title:
                raise ValueError(f'Manifest title and publication date required on line {number}')
            if raw.get('id'):
                key = (entry.source_name, raw['id'])
                if key in seen:
                    raise ValueError(f'Duplicate chunk ID on line {number}')
                seen.add(key)
            grouped.setdefault(entry.source_name, (entry, []))[1].append(raw)
        if not grouped:
            raise ValueError('Chunks file is empty')

        started = datetime.now(timezone.utc)
        prepared = []
        for source_name, (entry, rows) in grouped.items():
            raw = dict(source_name=source_name, source_pdf=source_name,
                       markdown='\n\n'.join(row['text'] for row in rows),
                       warnings=['Reconstructed from prepared chunks; not the complete original PDF.',
                                 'Original table grids and charts are not available in this import.'])
            document = _document_record(Path(source_name), raw, entry, None, started)
            document = replace(document, extraction={**document.extraction, 'mode': 'chunks_only'},
                meta={**document.meta, 'chunks_sha256': digest, 'full_pdf_available': False})
            existing = self.repository.get_document(document.id)
            if existing and existing['extraction'].get('mode') != 'chunks_only':
                raise ValueError(f'Refusing to replace a full extraction with chunks only: {document.id}')
            prepared.append((document, _chunk_records(document, rows)))

        report = dict(started_at=started.isoformat(), source_root=None,
            chunks_path=chunks_path.name, chunks_sha256=digest, manifest_path=manifest_path.name,
            mode='chunks_only', documents=[], status='running',
            warnings=['PDF text is reconstructed from chunks. Table references are retained; original table grids and chart data are absent.'])
        try:
            for document, chunks in prepared:
                result = self.repository.save_document(document, chunks, [])
                report['documents'].append(dict(id=document.id, source_name=document.source_name, **result))
            report['summary'] = dict(documents=len(prepared), chunks=sum(len(c) for _, c in prepared), tables=0)
            report['status'] = 'ok'
        except Exception as exc:
            report['status'] = 'failed'
            report['error'] = type(exc).__name__
            raise
        finally:
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            self.repository.record_run(report)
        return report
