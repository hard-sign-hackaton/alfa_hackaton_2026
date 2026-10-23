"""Persist versioned company/news matches, importance and analytical results."""
from alembic import op

revision = '0006_news_company_links'
down_revision = '0005_merge_data_modules'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE news_company_links (
        news_id varchar(64) NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
        company_id varchar NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        news_hash varchar(64) NOT NULL, company_hash varchar(64) NOT NULL,
        active boolean NOT NULL DEFAULT true,
        match_method varchar(32) NOT NULL, match_score double precision,
        match_reasons jsonb NOT NULL DEFAULT '[]', topics jsonb NOT NULL DEFAULT '[]',
        importance varchar(8), importance_status varchar(12) NOT NULL DEFAULT 'pending',
        importance_reason text, importance_evidence jsonb NOT NULL DEFAULT '[]',
        importance_method varchar(32), importance_attempts integer NOT NULL DEFAULT 0,
        analysis_status varchar(12) NOT NULL DEFAULT 'pending', analysis_run_id varchar(32),
        analysis_result jsonb, analysis_as_of timestamptz, error_code varchar(40),
        matched_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (news_id,company_id),
        CHECK (importance IS NULL OR importance IN ('high','medium','low')),
        CHECK (importance_status IN ('pending','ready','failed')),
        CHECK (analysis_status IN ('pending','running','ready','partial','failed')),
        CHECK (importance_status != 'ready' OR importance IS NOT NULL),
        CHECK (match_score IS NULL OR (match_score >= -1 AND match_score <= 1))
    )''')
    op.execute('CREATE INDEX ix_links_company_active ON news_company_links(company_id,active,importance)')
    op.execute('CREATE INDEX ix_links_news_active ON news_company_links(news_id,active)')


def downgrade():
    op.drop_table('news_company_links')
