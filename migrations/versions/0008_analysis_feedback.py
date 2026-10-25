"""Persist browser feedback separately for each analysis version and test scope."""
from alembic import op

revision = '0008_analysis_feedback'
down_revision = '0007_link_source_invalidation'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE analysis_feedback (
        company_id varchar NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        news_id varchar(96) NOT NULL, analysis_version varchar(64) NOT NULL,
        reviewer_id varchar(32) NOT NULL, vote smallint NOT NULL,
        is_demo boolean NOT NULL, demo_id varchar(32), analysis_as_of timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (company_id,news_id,analysis_version,reviewer_id),
        CHECK (vote IN (-1,1)), CHECK (is_demo = (demo_id IS NOT NULL))
    )''')
    op.execute('CREATE INDEX ix_feedback_quality ON analysis_feedback(is_demo,created_at,vote)')


def downgrade():
    op.execute('DROP TABLE analysis_feedback')
