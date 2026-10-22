"""Analytical documents, chunks, tables and chunk-level pgvector embeddings."""
from alembic import op

revision = '0004_analytics'
down_revision = '0003_pgvector_only'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
        CREATE TABLE analytics_documents (
            id varchar(128) PRIMARY KEY,
            title text NOT NULL,
            subtitle text,
            doc_type varchar(64) NOT NULL,
            published_at timestamptz NOT NULL,
            language varchar(16) NOT NULL DEFAULT 'ru',
            tags text[] NOT NULL DEFAULT '{}'::text[],
            source_name text NOT NULL,
            source_uri text,
            source_sha256 varchar(64),
            source_bytes bigint,
            page_count integer,
            markdown text NOT NULL,
            content_hash varchar(64) NOT NULL,
            extraction jsonb NOT NULL DEFAULT '{}'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            collected_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_analytics_documents_source_sha256 UNIQUE (source_sha256)
        )
    ''')
    op.execute('''
        CREATE TABLE analytics_chunks (
            id varchar(200) PRIMARY KEY,
            document_id varchar(128) NOT NULL
                REFERENCES analytics_documents(id) ON DELETE CASCADE,
            ordinal integer NOT NULL,
            kind varchar(16) NOT NULL CHECK (kind IN ('text', 'table', 'mixed')),
            section_path text[] NOT NULL DEFAULT '{}'::text[],
            text text NOT NULL,
            embedding_text text NOT NULL,
            content_hash varchar(64) NOT NULL,
            input_hash varchar(64) NOT NULL,
            chars integer NOT NULL,
            size integer NOT NULL,
            pages integer[] NOT NULL DEFAULT '{}'::integer[],
            page_from integer,
            page_to integer,
            table_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            search_vector tsvector GENERATED ALWAYS AS
                (to_tsvector('russian'::regconfig, text)) STORED
        )
    ''')
    op.execute('''
        CREATE TABLE analytics_tables (
            id varchar(200) PRIMARY KEY,
            document_id varchar(128) NOT NULL
                REFERENCES analytics_documents(id) ON DELETE CASCADE,
            table_id varchar(64) NOT NULL,
            page integer,
            nrows integer NOT NULL,
            ncols integer NOT NULL,
            rows jsonb NOT NULL,
            source jsonb NOT NULL DEFAULT '{}'::jsonb,
            warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
            content_hash varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_analytics_tables_document_table UNIQUE (document_id, table_id)
        )
    ''')
    op.execute('''
        CREATE TABLE analytics_embedding_profiles (
            id varchar(64) PRIMARY KEY,
            model varchar NOT NULL,
            revision varchar NOT NULL,
            dimensions integer NOT NULL,
            normalized boolean NOT NULL,
            preparation varchar NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    ''')
    op.execute('''
        CREATE TABLE analytics_chunk_embeddings (
            id bigserial PRIMARY KEY,
            chunk_id varchar(200) NOT NULL
                REFERENCES analytics_chunks(id) ON DELETE CASCADE,
            profile_id varchar(64) NOT NULL
                REFERENCES analytics_embedding_profiles(id) ON DELETE CASCADE,
            input_hash varchar(64) NOT NULL,
            vector vector(384) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_analytics_chunk_embedding UNIQUE (chunk_id, profile_id)
        )
    ''')
    op.execute('''
        CREATE TABLE analytics_import_runs (
            id bigserial PRIMARY KEY,
            started_at timestamptz NOT NULL,
            finished_at timestamptz NOT NULL,
            status varchar NOT NULL,
            source_root text,
            manifest_path text,
            report jsonb NOT NULL
        )
    ''')

    op.execute('CREATE INDEX ix_analytics_documents_published_at ON analytics_documents(published_at)')
    op.execute('CREATE INDEX ix_analytics_documents_doc_type ON analytics_documents(doc_type, published_at)')
    op.execute('CREATE INDEX ix_analytics_documents_tags ON analytics_documents USING gin(tags)')
    op.execute('CREATE INDEX ix_analytics_chunks_document_ordinal ON analytics_chunks(document_id, ordinal)')
    op.execute('CREATE INDEX ix_analytics_chunks_search ON analytics_chunks USING gin(search_vector)')
    op.execute('CREATE INDEX ix_analytics_chunks_content_hash ON analytics_chunks(content_hash)')
    op.execute('CREATE INDEX ix_analytics_tables_document ON analytics_tables(document_id, table_id)')
    op.execute('CREATE INDEX ix_analytics_embedding_profile_id ON analytics_chunk_embeddings(profile_id, id)')
    op.execute('CREATE INDEX ix_analytics_chunk_vector_hnsw ON analytics_chunk_embeddings USING hnsw (vector vector_cosine_ops)')
    op.execute('CREATE INDEX ix_analytics_import_runs_started ON analytics_import_runs(started_at)')


def downgrade():
    op.execute('DROP TABLE analytics_import_runs')
    op.execute('DROP TABLE analytics_chunk_embeddings')
    op.execute('DROP TABLE analytics_embedding_profiles')
    op.execute('DROP TABLE analytics_tables')
    op.execute('DROP TABLE analytics_chunks')
    op.execute('DROP TABLE analytics_documents')
