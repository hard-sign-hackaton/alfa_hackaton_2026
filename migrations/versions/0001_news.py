"""Initial news storage, vector index and cache invalidation triggers."""
from alembic import op

revision = '0001_news'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('''CREATE TABLE news_sources (
        id varchar PRIMARY KEY, name varchar NOT NULL, sitemap text NOT NULL, rss text NOT NULL)''')
    op.execute('''CREATE TABLE news_articles (
        id varchar(64) PRIMARY KEY, source_id varchar NOT NULL REFERENCES news_sources(id),
        url text NOT NULL UNIQUE, title text NOT NULL, text text NOT NULL,
        published_at timestamptz NOT NULL, collected_at timestamptz NOT NULL,
        content_hash varchar(64) NOT NULL, details jsonb NOT NULL)''')
    op.execute('CREATE INDEX ix_news_source_date ON news_articles(source_id, published_at)')
    op.execute('CREATE INDEX ix_news_published_at ON news_articles(published_at)')
    op.execute('''CREATE TABLE news_ingestion_runs (
        id bigserial PRIMARY KEY, source_id varchar NOT NULL REFERENCES news_sources(id),
        started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
        status varchar NOT NULL, report jsonb NOT NULL)''')
    op.execute('''CREATE TABLE news_embedding_profiles (
        id varchar(64) PRIMARY KEY, model varchar NOT NULL, revision varchar NOT NULL,
        dimensions integer NOT NULL CHECK(dimensions=384), normalized boolean NOT NULL,
        preparation varchar NOT NULL)''')
    op.execute('''CREATE TABLE news_embeddings (
        id bigserial PRIMARY KEY, article_id varchar(64) NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
        profile_id varchar(64) NOT NULL REFERENCES news_embedding_profiles(id), input_hash varchar(64) NOT NULL,
        chunk_count integer NOT NULL CHECK(chunk_count>0), vector vector(384) NOT NULL,
        created_at timestamptz NOT NULL)''')
    op.execute('CREATE UNIQUE INDEX uq_news_embedding_article_profile ON news_embeddings(article_id, profile_id)')
    op.execute('CREATE INDEX ix_news_vector_hnsw ON news_embeddings USING hnsw (vector vector_cosine_ops)')
    op.execute('CREATE TABLE news_index_state (id integer PRIMARY KEY CHECK(id=1), version bigint NOT NULL)')
    op.execute('INSERT INTO news_index_state VALUES (1, 0)')
    op.execute('''CREATE FUNCTION news_bump_index_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE news_index_state SET version=version+1 WHERE id=1; RETURN NULL; END $$''')
    op.execute('''CREATE TRIGGER news_embedding_change AFTER INSERT OR UPDATE OR DELETE ON news_embeddings
        FOR EACH STATEMENT EXECUTE FUNCTION news_bump_index_version()''')
    op.execute('''CREATE FUNCTION news_invalidate_vectors() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN DELETE FROM news_embeddings WHERE article_id=OLD.id; RETURN NEW; END $$''')
    op.execute('''CREATE TRIGGER news_text_change BEFORE UPDATE OF content_hash ON news_articles
        FOR EACH ROW WHEN (OLD.content_hash IS DISTINCT FROM NEW.content_hash)
        EXECUTE FUNCTION news_invalidate_vectors()''')


def downgrade():
    op.execute('DROP TABLE news_embeddings, news_ingestion_runs, news_articles, news_sources, news_embedding_profiles, news_index_state CASCADE')
    op.execute('DROP FUNCTION news_bump_index_version(), news_invalidate_vectors()')
