from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, Integer, Boolean, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.shared.db.base import Base

class NewsSource(Base):
    __tablename__ = 'news_sources'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sitemap: Mapped[str] = mapped_column(Text)
    rss: Mapped[str] = mapped_column(Text)


class Article(Base):
    __tablename__ = 'news_articles'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('news_sources.id'))
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (Index('ix_news_source_date', 'source_id', 'published_at'),
                      Index('ix_news_published_at', 'published_at'))


class IngestionRun(Base):
    __tablename__ = 'news_ingestion_runs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('news_sources.id'))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
    report: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (Index('ix_news_run_source_started', 'source_id', 'started_at'),)


class EmbeddingProfile(Base):
    __tablename__ = 'news_embedding_profiles'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String)
    revision: Mapped[str] = mapped_column(String)
    dimensions: Mapped[int] = mapped_column(Integer)
    normalized: Mapped[bool] = mapped_column(Boolean)
    preparation: Mapped[str] = mapped_column(String)


class Embedding(Base):
    __tablename__ = 'news_embeddings'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[str] = mapped_column(ForeignKey('news_articles.id', ondelete='CASCADE'))
    profile_id: Mapped[str] = mapped_column(ForeignKey('news_embedding_profiles.id'))
    input_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index('uq_news_embedding_article_profile', 'article_id', 'profile_id', unique=True),
        Index('ix_news_embedding_profile_id', 'profile_id', 'id'),
        Index('ix_news_vector_hnsw', 'vector', postgresql_using='hnsw', postgresql_ops={'vector': 'vector_cosine_ops'}))
