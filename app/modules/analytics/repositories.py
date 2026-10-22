from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import and_, delete, func, literal_column, or_, select
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import insert

from .dto import ChunkRecord, DocumentRecord, EmbeddingInput, TableRecord
from .models import (
    AnalyticsChunk,
    AnalyticsChunkEmbedding,
    AnalyticsDocument,
    AnalyticsEmbeddingProfile,
    AnalyticsImportRun,
    AnalyticsTable,
)

EXCERPT_OPTIONS = 'MaxWords=180, MinWords=60, MaxFragments=1, StartSel="", StopSel=""'
RUSSIAN = literal_column("'russian'::regconfig")


def search_time(as_of: datetime | None) -> datetime:
    value = as_of or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Search time requires a timezone')
    return value


def _iso(value):
    return value.isoformat() if value is not None else None


def _chunk_signature(chunk):
    return (
        chunk.id,
        chunk.ordinal,
        chunk.kind,
        tuple(chunk.section_path or []),
        chunk.content_hash,
        chunk.input_hash,
        chunk.chars,
        chunk.size,
        tuple(chunk.pages or []),
        chunk.page_from,
        chunk.page_to,
        json.dumps(chunk.table_refs or [], ensure_ascii=False, sort_keys=True),
    )


def _table_signature(table):
    return (
        table.id,
        table.table_id,
        table.page,
        table.nrows,
        table.ncols,
        json.dumps(table.rows or [], ensure_ascii=False, sort_keys=True),
        json.dumps(table.source or {}, ensure_ascii=False, sort_keys=True),
        json.dumps(table.warnings or [], ensure_ascii=False, sort_keys=True),
    )


def _document_dict(row: AnalyticsDocument, include_markdown: bool = False):
    result = {
        'id': row.id,
        'title': row.title,
        'subtitle': row.subtitle,
        'doc_type': row.doc_type,
        'published_at': _iso(row.published_at),
        'language': row.language,
        'tags': list(row.tags or []),
        'source_name': row.source_name,
        'source_uri': row.source_uri,
        'source_sha256': row.source_sha256,
        'source_bytes': row.source_bytes,
        'page_count': row.page_count,
        'content_hash': row.content_hash,
        'collected_at': _iso(row.collected_at),
        'created_at': _iso(row.created_at),
        'updated_at': _iso(row.updated_at),
        'extraction': row.extraction,
        'metadata': row.meta,
    }
    if include_markdown:
        result['markdown'] = row.markdown
    return result


def _chunk_dict(row: AnalyticsChunk):
    return {
        'id': row.id,
        'document_id': row.document_id,
        'ordinal': row.ordinal,
        'kind': row.kind,
        'section_path': list(row.section_path or []),
        'text': row.text,
        'embedding_text': row.embedding_text,
        'content_hash': row.content_hash,
        'input_hash': row.input_hash,
        'chars': row.chars,
        'size': row.size,
        'pages': list(row.pages or []),
        'page_from': row.page_from,
        'page_to': row.page_to,
        'table_refs': row.table_refs,
        'metadata': row.meta,
    }


def _table_dict(row: AnalyticsTable):
    return {
        'id': row.id,
        'document_id': row.document_id,
        'table_id': row.table_id,
        'page': row.page,
        'nrows': row.nrows,
        'ncols': row.ncols,
        'rows': row.rows,
        'source': row.source,
        'warnings': row.warnings,
        'content_hash': row.content_hash,
    }


def _search_hit(row):
    result = dict(row._mapping)
    for key in ('published_at', 'collected_at'):
        if key in result:
            result[key] = _iso(result[key])
    for key in ('section_path', 'pages'):
        if key in result and result[key] is not None:
            result[key] = list(result[key])
    if 'rank' in result and result['rank'] is not None:
        result['rank'] = float(result['rank'])
    if 'similarity' in result and result['similarity'] is not None:
        result['similarity'] = float(result['similarity'])
    return result


class AnalyticsRepository:
    def __init__(self, session_factory):
        self.session = session_factory

    def save_document(
        self,
        document: DocumentRecord,
        chunks: list[ChunkRecord],
        tables: list[TableRecord],
    ):
        now = datetime.now(timezone.utc)
        values = {
            'id': document.id,
            'title': document.title,
            'subtitle': document.subtitle,
            'doc_type': document.doc_type,
            'published_at': document.published_at,
            'language': document.language,
            'tags': document.tags,
            'source_name': document.source_name,
            'source_uri': document.source_uri,
            'source_sha256': document.source_sha256,
            'source_bytes': document.source_bytes,
            'page_count': document.page_count,
            'markdown': document.markdown,
            'content_hash': document.content_hash,
            'extraction': document.extraction,
            'metadata': document.meta,
            'collected_at': document.collected_at,
            'created_at': now,
            'updated_at': now,
        }
        with self.session.begin() as session:
            session.execute(
                sql('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                {'key': f'analytics:{document.id}'},
            )
            old = session.get(AnalyticsDocument, document.id)
            existing_chunks = [
                _chunk_signature(row) for row in session.scalars(
                    select(AnalyticsChunk)
                    .where(AnalyticsChunk.document_id == document.id)
                    .order_by(AnalyticsChunk.ordinal)
                )
            ]
            desired_chunks = [_chunk_signature(chunk) for chunk in chunks]
            chunks_changed = existing_chunks != desired_chunks

            existing_tables = [
                _table_signature(row) for row in session.scalars(
                    select(AnalyticsTable)
                    .where(AnalyticsTable.document_id == document.id)
                    .order_by(AnalyticsTable.table_id)
                )
            ]
            desired_tables = [_table_signature(table) for table in tables]
            tables_changed = existing_tables != desired_tables

            outcome = (
                'inserted' if old is None
                else 'updated' if (
                    old.content_hash != document.content_hash
                    or chunks_changed
                    or tables_changed
                )
                else 'unchanged'
            )
            statement = insert(AnalyticsDocument.__table__).values(**values)
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=['id'],
                    set_={key: value for key, value in values.items() if key not in ('id', 'created_at')},
                )
            )

            if chunks_changed:
                session.execute(
                    delete(AnalyticsChunk).where(AnalyticsChunk.document_id == document.id)
                )
                if chunks:
                    chunk_values = [
                        {
                            'id': chunk.id,
                            'document_id': chunk.document_id,
                            'ordinal': chunk.ordinal,
                            'kind': chunk.kind,
                            'section_path': chunk.section_path,
                            'text': chunk.text,
                            'embedding_text': chunk.embedding_text,
                            'content_hash': chunk.content_hash,
                            'input_hash': chunk.input_hash,
                            'chars': chunk.chars,
                            'size': chunk.size,
                            'pages': chunk.pages,
                            'page_from': chunk.page_from,
                            'page_to': chunk.page_to,
                            'table_refs': chunk.table_refs,
                            'metadata': chunk.meta,
                            'created_at': now,
                            'updated_at': now,
                        }
                        for chunk in chunks
                    ]
                    session.execute(
                        insert(AnalyticsChunk.__table__).values(chunk_values)
                    )

            if tables_changed:
                session.execute(
                    delete(AnalyticsTable).where(AnalyticsTable.document_id == document.id)
                )
                if tables:
                    table_values = [
                        {
                            'id': table.id,
                            'document_id': table.document_id,
                            'table_id': table.table_id,
                            'page': table.page,
                            'nrows': table.nrows,
                            'ncols': table.ncols,
                            'rows': table.rows,
                            'source': table.source,
                            'warnings': table.warnings,
                            'content_hash': table.content_hash,
                            'created_at': now,
                            'updated_at': now,
                        }
                        for table in tables
                    ]
                    session.execute(
                        insert(AnalyticsTable.__table__).values(table_values)
                    )

        return {'document': outcome, 'chunks': len(chunks), 'tables': len(tables)}

    def record_run(self, report: dict):
        started_at = datetime.fromisoformat(report['started_at'])
        finished_at = datetime.fromisoformat(report['finished_at'])
        with self.session.begin() as session:
            session.add(
                AnalyticsImportRun(
                    started_at=started_at,
                    finished_at=finished_at,
                    status=report.get('status', 'unknown'),
                    source_root=report.get('source_root'),
                    manifest_path=report.get('manifest_path'),
                    report=report,
                )
            )

    def list_documents(
        self,
        *,
        doc_type: str | None = None,
        as_of: datetime | None = None,
        limit: int = 100,
    ):
        if not 1 <= limit <= 500:
            raise ValueError('limit must be between 1 and 500')
        chunk_count = (
            select(func.count())
            .select_from(AnalyticsChunk)
            .where(AnalyticsChunk.document_id == AnalyticsDocument.id)
            .scalar_subquery()
        )
        table_count = (
            select(func.count())
            .select_from(AnalyticsTable)
            .where(AnalyticsTable.document_id == AnalyticsDocument.id)
            .scalar_subquery()
        )
        statement = select(
            AnalyticsDocument,
            chunk_count.label('chunk_count'),
            table_count.label('table_count'),
        )
        if doc_type:
            statement = statement.where(AnalyticsDocument.doc_type == doc_type)
        if as_of is not None:
            statement = statement.where(AnalyticsDocument.published_at <= search_time(as_of))
        statement = statement.order_by(
            AnalyticsDocument.published_at.desc(), AnalyticsDocument.id
        ).limit(limit)
        with self.session() as session:
            rows = session.execute(statement).all()
        result = []
        for row in rows:
            item = _document_dict(row[0])
            item['chunk_count'] = row[1]
            item['table_count'] = row[2]
            result.append(item)
        return result

    def get_document(self, document_id: str, *, include_markdown: bool = False):
        with self.session() as session:
            row = session.get(AnalyticsDocument, document_id)
            if row is None:
                return None
            chunks = session.scalar(
                select(func.count())
                .select_from(AnalyticsChunk)
                .where(AnalyticsChunk.document_id == document_id)
            )
            tables = session.scalar(
                select(func.count())
                .select_from(AnalyticsTable)
                .where(AnalyticsTable.document_id == document_id)
            )
            result = _document_dict(row, include_markdown=include_markdown)
            result['chunk_count'] = chunks
            result['table_count'] = tables
            return result

    def get_chunks(self, document_id: str):
        with self.session() as session:
            rows = session.scalars(
                select(AnalyticsChunk)
                .where(AnalyticsChunk.document_id == document_id)
                .order_by(AnalyticsChunk.ordinal)
            )
            return [_chunk_dict(row) for row in rows]

    def get_tables(self, document_id: str):
        with self.session() as session:
            rows = session.scalars(
                select(AnalyticsTable)
                .where(AnalyticsTable.document_id == document_id)
                .order_by(AnalyticsTable.table_id)
            )
            return [_table_dict(row) for row in rows]

    def stats(self):
        with self.session() as session:
            return {
                'documents': session.scalar(select(func.count()).select_from(AnalyticsDocument)),
                'chunks': session.scalar(select(func.count()).select_from(AnalyticsChunk)),
                'tables': session.scalar(select(func.count()).select_from(AnalyticsTable)),
                'embeddings': session.scalar(select(func.count()).select_from(AnalyticsChunkEmbedding)),
                'profiles': session.scalar(select(func.count()).select_from(AnalyticsEmbeddingProfile)),
                'import_runs': session.scalar(select(func.count()).select_from(AnalyticsImportRun)),
            }

    def search_text(self, query: str, top_k: int = 5, *, as_of: datetime | None = None):
        if not query.strip() or not 1 <= top_k <= 100:
            raise ValueError('Nonempty query and top-k between 1 and 100 required')
        vector = func.to_tsvector(RUSSIAN, AnalyticsChunk.text)
        terms = func.websearch_to_tsquery(RUSSIAN, query)
        statement = (
            select(
                AnalyticsChunk.id.label('chunk_id'),
                AnalyticsDocument.id.label('document_id'),
                AnalyticsDocument.title.label('document_title'),
                AnalyticsDocument.doc_type,
                AnalyticsDocument.source_name,
                AnalyticsDocument.extraction,
                AnalyticsDocument.published_at,
                AnalyticsChunk.ordinal,
                AnalyticsChunk.kind,
                AnalyticsChunk.section_path,
                AnalyticsChunk.text,
                AnalyticsChunk.pages,
                func.ts_rank(vector, terms).label('rank'),
            )
            .select_from(AnalyticsChunk)
            .join(AnalyticsDocument, AnalyticsDocument.id == AnalyticsChunk.document_id)
            .where(
                vector.op('@@')(terms),
                AnalyticsDocument.published_at <= search_time(as_of),
            )
            .order_by(
                func.ts_rank(vector, terms).desc(),
                AnalyticsDocument.published_at.desc(),
                AnalyticsChunk.ordinal,
            )
            .limit(top_k * 4)
        )
        with self.session() as session:
            rows = session.execute(statement).all()
        return [_search_hit(row) for row in rows]


class AnalyticsEmbeddingRepository:
    def __init__(self, session_factory):
        self.session = session_factory

    def ensure_profile(self, profile: dict):
        values = dict(profile)
        values.setdefault('created_at', datetime.now(timezone.utc))
        with self.session.begin() as session:
            session.execute(
                insert(AnalyticsEmbeddingProfile)
                .values(**values)
                .on_conflict_do_nothing(index_elements=['id'])
            )

    def pending(self, profile_id: str, limit: int) -> list[EmbeddingInput]:
        with self.session() as session:
            statement = (
                select(AnalyticsChunk)
                .outerjoin(
                    AnalyticsChunkEmbedding,
                    and_(
                        AnalyticsChunkEmbedding.chunk_id == AnalyticsChunk.id,
                        AnalyticsChunkEmbedding.profile_id == profile_id,
                    ),
                )
                .where(
                    or_(
                        AnalyticsChunkEmbedding.id.is_(None),
                        AnalyticsChunkEmbedding.input_hash != AnalyticsChunk.input_hash,
                    )
                )
                .order_by(AnalyticsChunk.document_id, AnalyticsChunk.ordinal)
                .limit(limit)
            )
            rows = session.scalars(statement)
            return [
                EmbeddingInput(row.id, row.embedding_text, row.input_hash)
                for row in rows
            ]

    def save_embedding(
        self,
        chunk: EmbeddingInput,
        profile_id: str,
        vector: list[float],
    ) -> bool:
        with self.session.begin() as session:
            current = session.get(AnalyticsChunk, chunk.chunk_id)
            if current is None or current.input_hash != chunk.input_hash:
                return False
            statement = insert(AnalyticsChunkEmbedding).values(
                chunk_id=chunk.chunk_id,
                profile_id=profile_id,
                input_hash=chunk.input_hash,
                vector=vector,
                created_at=datetime.now(timezone.utc),
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=['chunk_id', 'profile_id'],
                    set_={
                        'input_hash': statement.excluded.input_hash,
                        'vector': statement.excluded.vector,
                        'created_at': statement.excluded.created_at,
                    },
                )
            )
            return True

    def list_profiles(self):
        with self.session() as session:
            statement = (
                select(
                    AnalyticsEmbeddingProfile,
                    func.count(AnalyticsChunkEmbedding.id).label('embeddings'),
                )
                .outerjoin(
                    AnalyticsChunkEmbedding,
                    AnalyticsChunkEmbedding.profile_id == AnalyticsEmbeddingProfile.id,
                )
                .group_by(AnalyticsEmbeddingProfile.id)
                .order_by(AnalyticsEmbeddingProfile.created_at)
            )
            rows = session.execute(statement).all()
            return [
                {
                    'id': row[0].id,
                    'model': row[0].model,
                    'revision': row[0].revision,
                    'dimensions': row[0].dimensions,
                    'normalized': row[0].normalized,
                    'preparation': row[0].preparation,
                    'embeddings': row[1],
                }
                for row in rows
            ]

    def search_pg(
        self,
        vector: list[float],
        profile_id: str,
        top_k: int,
        *,
        as_of: datetime | None = None,
    ):
        if not 1 <= top_k <= 100:
            raise ValueError('top-k must be between 1 and 100')
        distance = AnalyticsChunkEmbedding.vector.cosine_distance(vector)
        with self.session() as session:
            session.execute(sql("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            session.execute(sql('SET LOCAL hnsw.ef_search = 64'))
            statement = (
                select(
                    AnalyticsChunk.id.label('chunk_id'),
                    AnalyticsDocument.id.label('document_id'),
                    AnalyticsDocument.title.label('document_title'),
                    AnalyticsDocument.doc_type,
                    AnalyticsDocument.source_name,
                    AnalyticsDocument.extraction,
                    AnalyticsDocument.published_at,
                    AnalyticsChunk.ordinal,
                    AnalyticsChunk.kind,
                    AnalyticsChunk.section_path,
                    AnalyticsChunk.text,
                    AnalyticsChunk.pages,
                    (1 - distance).label('similarity'),
                )
                .select_from(AnalyticsChunkEmbedding)
                .join(
                    AnalyticsChunk,
                    AnalyticsChunk.id == AnalyticsChunkEmbedding.chunk_id,
                )
                .join(
                    AnalyticsDocument,
                    AnalyticsDocument.id == AnalyticsChunk.document_id,
                )
                .where(
                    AnalyticsChunkEmbedding.profile_id == profile_id,
                    AnalyticsChunkEmbedding.input_hash == AnalyticsChunk.input_hash,
                    AnalyticsDocument.published_at <= search_time(as_of),
                )
                .order_by(distance, AnalyticsChunk.id)
                .limit(top_k * 4)
            )
            rows = session.execute(statement).all()
        return [_search_hit(row) for row in rows]
