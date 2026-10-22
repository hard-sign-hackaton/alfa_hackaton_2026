from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class CompanyGroup(Base):
    __tablename__ = 'company_groups'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    okved_section_code: Mapped[str] = mapped_column(String)
    okved_section_name: Mapped[str] = mapped_column(Text)
    okved_class: Mapped[str] = mapped_column(String)
    main_okved_code: Mapped[str] = mapped_column(String)
    main_okved_name: Mapped[str] = mapped_column(Text)
    headquarters_region: Mapped[str] = mapped_column(Text)
    headquarters_city: Mapped[str] = mapped_column(Text)
    edges_count: Mapped[int] = mapped_column(Integer)
    min_company_edges_count: Mapped[int] = mapped_column(Integer)
    companies_count: Mapped[int] = mapped_column(Integer)
    total_revenue_rub: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB)


class Company(Base):
    __tablename__ = 'companies'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey('company_groups.id'))
    okved_code: Mapped[str] = mapped_column(String)
    okved_name: Mapped[str] = mapped_column(Text)
    okved_section_code: Mapped[str] = mapped_column(String)
    okved_section_name: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    ownership_form: Mapped[str] = mapped_column(Text)
    annual_revenue_rub: Mapped[int] = mapped_column(BigInteger)
    business_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_type: Mapped[str] = mapped_column(String)
    bank_services: Mapped[dict] = mapped_column(JSONB)
    foreign_trade_countries: Mapped[list] = mapped_column(JSONB)
    profile_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index('ix_companies_group_id', 'group_id'),
        Index('ix_companies_okved_code', 'okved_code'),
        Index('ix_companies_region', 'region'),
    )


class CompanyImportRun(Base):
    __tablename__ = 'company_import_runs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
    report: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (Index('ix_company_run_started', 'started_at'),)


class CompanyEmbeddingProfile(Base):
    __tablename__ = 'company_embedding_profiles'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String)
    revision: Mapped[str] = mapped_column(String)
    dimensions: Mapped[int] = mapped_column(Integer)
    normalized: Mapped[bool] = mapped_column(Boolean)
    preparation: Mapped[str] = mapped_column(String)


class CompanyEmbedding(Base):
    __tablename__ = 'company_embeddings'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id', ondelete='CASCADE'))
    profile_id: Mapped[str] = mapped_column(ForeignKey('company_embedding_profiles.id'))
    input_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    vector: Mapped[list] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index('uq_company_embedding_company_profile', 'company_id', 'profile_id', unique=True),
        Index('ix_company_embedding_profile_id', 'profile_id', 'id'),
        Index('ix_company_vector_hnsw', 'vector', postgresql_using='hnsw',
              postgresql_ops={'vector': 'vector_cosine_ops'}),
    )
