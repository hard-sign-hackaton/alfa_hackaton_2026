"""Index profile-scoped vector scans and source-scoped run history."""
from alembic import op

revision = '0002_news_fk_indexes'
down_revision = '0001_news'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_news_embedding_profile_id', 'news_embeddings', ['profile_id', 'id'])
    op.create_index('ix_news_run_source_started', 'news_ingestion_runs', ['source_id', 'started_at'])


def downgrade():
    op.drop_index('ix_news_run_source_started', table_name='news_ingestion_runs')
    op.drop_index('ix_news_embedding_profile_id', table_name='news_embeddings')
