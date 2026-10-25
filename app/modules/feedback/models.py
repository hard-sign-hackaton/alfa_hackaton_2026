from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.shared.db.base import Base


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedback'
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id', ondelete='CASCADE'), primary_key=True)
    # Test publications are ephemeral and deliberately absent from news_articles.
    news_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    analysis_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    vote: Mapped[int] = mapped_column(SmallInteger)
    is_demo: Mapped[bool] = mapped_column(Boolean)
    demo_id: Mapped[str | None] = mapped_column(String(32))
    analysis_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint('vote IN (-1,1)'),
        CheckConstraint('is_demo = (demo_id IS NOT NULL)'),
        Index('ix_feedback_quality', 'is_demo', 'created_at', 'vote'),
    )
