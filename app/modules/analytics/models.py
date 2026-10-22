from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class AnalyticsDocument(Base):
    __tablename__ = 'analytics_documents'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    language: Mapped[str] = mapped_column(String(16), server_default=sql_text("'ru'"))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    source_name: Mapped[str] = mapped_column(Text)
    source_uri: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_bytes: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    extraction: Mapped[dict] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    meta: Mapped[dict] = mapped_column(
        'metadata', JSONB, server_default=sql_text("'{}'::jsonb")
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('source_sha256', name='uq_analytics_documents_source_sha256'),
        Index('ix_analytics_documents_published_at', 'published_at'),
        Index('ix_analytics_documents_doc_type', 'doc_type', 'published_at'),
        Index('ix_analytics_documents_tags', 'tags', postgresql_using='gin'),
    )


class AnalyticsChunk(Base):
    __tablename__ = 'analytics_chunks'
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey('analytics_documents.id', ondelete='CASCADE')
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    section_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    text: Mapped[str] = mapped_column(Text)
    embedding_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    chars: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    pages: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=sql_text("'{}'::integer[]")
    )
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    table_refs: Mapped[list] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    meta: Mapped[dict] = mapped_column(
        'metadata', JSONB, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian'::regconfig, text)", persisted=True)
    )
    __table_args__ = (
        Index('ix_analytics_chunks_document_ordinal', 'document_id', 'ordinal'),
        Index('ix_analytics_chunks_search', 'search_vector', postgresql_using='gin'),
        Index('ix_analytics_chunks_content_hash', 'content_hash'),
    )


class AnalyticsTable(Base):
    __tablename__ = 'analytics_tables'
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey('analytics_documents.id', ondelete='CASCADE')
    )
    table_id: Mapped[str] = mapped_column(String(64))
    page: Mapped[int | None] = mapped_column(Integer)
    nrows: Mapped[int] = mapped_column(Integer)
    ncols: Mapped[int] = mapped_column(Integer)
    rows: Mapped[list] = mapped_column(JSONB)
    source: Mapped[dict] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    warnings: Mapped[list] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('document_id', 'table_id', name='uq_analytics_tables_document_table'),
        Index('ix_analytics_tables_document', 'document_id', 'table_id'),
    )


class AnalyticsEmbeddingProfile(Base):
    __tablename__ = 'analytics_embedding_profiles'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String)
    revision: Mapped[str] = mapped_column(String)
    dimensions: Mapped[int] = mapped_column(Integer)
    normalized: Mapped[bool] = mapped_column(Boolean)
    preparation: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticsChunkEmbedding(Base):
    __tablename__ = 'analytics_chunk_embeddings'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey('analytics_chunks.id', ondelete='CASCADE')
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey('analytics_embedding_profiles.id', ondelete='CASCADE')
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[list] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('chunk_id', 'profile_id', name='uq_analytics_chunk_embedding'),
        Index('ix_analytics_embedding_profile_id', 'profile_id', 'id'),
        Index(
            'ix_analytics_chunk_vector_hnsw',
            'vector',
            postgresql_using='hnsw',
            postgresql_ops={'vector': 'vector_cosine_ops'},
        ),
    )


class AnalyticsImportRun(Base):
    __tablename__ = 'analytics_import_runs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
    source_root: Mapped[str | None] = mapped_column(Text)
    manifest_path: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (Index('ix_analytics_import_runs_started', 'started_at'),)
