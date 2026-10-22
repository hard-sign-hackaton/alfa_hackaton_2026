"""Remove file-index bookkeeping; preserve publications, profiles and vectors."""
from alembic import op

revision = '0003_pgvector_only'
down_revision = '0002_news_fk_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('DROP TRIGGER news_embedding_change ON news_embeddings')
    op.execute('DROP FUNCTION news_bump_index_version()')
    op.drop_table('news_index_state')


def downgrade():
    op.execute('CREATE TABLE news_index_state (id integer PRIMARY KEY CHECK(id=1), version bigint NOT NULL)')
    op.execute('INSERT INTO news_index_state VALUES (1, 0)')
    op.execute('''CREATE FUNCTION news_bump_index_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE news_index_state SET version=version+1 WHERE id=1; RETURN NULL; END $$''')
    op.execute('''CREATE TRIGGER news_embedding_change AFTER INSERT OR UPDATE OR DELETE ON news_embeddings
        FOR EACH STATEMENT EXECUTE FUNCTION news_bump_index_version()''')
