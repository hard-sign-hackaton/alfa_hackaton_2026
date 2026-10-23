from datetime import datetime
from sqlalchemy import String, Float, Text, DateTime, ForeignKey, Boolean, Integer, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.shared.db.base import Base


class NewsCompanyLink(Base):
    __tablename__ = 'news_company_links'
    news_id: Mapped[str] = mapped_column(ForeignKey('news_articles.id', ondelete='CASCADE'), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id', ondelete='CASCADE'), primary_key=True)
    news_hash: Mapped[str] = mapped_column(String(64))
    company_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_method: Mapped[str] = mapped_column(String(32))
    match_score: Mapped[float | None] = mapped_column(Float)
    match_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    topics: Mapped[list] = mapped_column(JSONB, default=list)
    importance: Mapped[str | None] = mapped_column(String(8))
    importance_status: Mapped[str] = mapped_column(String(12), default='pending')
    importance_reason: Mapped[str | None] = mapped_column(Text)
    importance_evidence: Mapped[list] = mapped_column(JSONB, default=list)
    importance_method: Mapped[str | None] = mapped_column(String(32))
    importance_attempts: Mapped[int] = mapped_column(Integer, default=0)
    analysis_status: Mapped[str] = mapped_column(String(12), default='pending')
    analysis_run_id: Mapped[str | None] = mapped_column(String(32))
    analysis_result: Mapped[dict | None] = mapped_column(JSONB)
    analysis_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("importance IS NULL OR importance IN ('high','medium','low')"),
        CheckConstraint("importance_status IN ('pending','ready','failed')"),
        CheckConstraint("analysis_status IN ('pending','running','ready','partial','failed')"),
        CheckConstraint("importance_status != 'ready' OR importance IS NOT NULL"),
        CheckConstraint("match_score IS NULL OR (match_score >= -1 AND match_score <= 1)"),
        Index('ix_links_company_active', 'company_id', 'active', 'importance'),
        Index('ix_links_news_active', 'news_id', 'active'),
    )
