"""Company groups, companies, import history and profile vectors."""
from alembic import op

revision = '0004_companies'
down_revision = '0003_pgvector_only'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE company_groups (
        id varchar PRIMARY KEY, rank integer NOT NULL,
        okved_section_code varchar NOT NULL, okved_section_name text NOT NULL,
        okved_class varchar NOT NULL, main_okved_code varchar NOT NULL, main_okved_name text NOT NULL,
        headquarters_region text NOT NULL, headquarters_city text NOT NULL,
        edges_count integer NOT NULL, min_company_edges_count integer NOT NULL,
        companies_count integer NOT NULL, total_revenue_rub bigint NOT NULL,
        reason text NOT NULL, details jsonb NOT NULL)''')
    op.execute('''CREATE TABLE companies (
        id varchar PRIMARY KEY, group_id varchar NOT NULL REFERENCES company_groups(id),
        okved_code varchar NOT NULL, okved_name text NOT NULL,
        okved_section_code varchar NOT NULL, okved_section_name text NOT NULL,
        city text NOT NULL, region text NOT NULL, ownership_form text NOT NULL,
        annual_revenue_rub bigint NOT NULL, business_stage text, client_type varchar NOT NULL,
        bank_services jsonb NOT NULL, foreign_trade_countries jsonb NOT NULL,
        profile_text text NOT NULL, content_hash varchar(64) NOT NULL,
        details jsonb NOT NULL, imported_at timestamptz NOT NULL)''')
    op.execute('CREATE INDEX ix_companies_group_id ON companies(group_id)')
    op.execute('CREATE INDEX ix_companies_okved_code ON companies(okved_code)')
    op.execute('CREATE INDEX ix_companies_region ON companies(region)')
    op.execute('''CREATE TABLE company_import_runs (
        id bigserial PRIMARY KEY, started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
        status varchar NOT NULL, report jsonb NOT NULL)''')
    op.execute('CREATE INDEX ix_company_run_started ON company_import_runs(started_at)')
    op.execute('''CREATE TABLE company_embedding_profiles (
        id varchar(64) PRIMARY KEY, model varchar NOT NULL, revision varchar NOT NULL,
        dimensions integer NOT NULL CHECK(dimensions=384), normalized boolean NOT NULL,
        preparation varchar NOT NULL)''')
    op.execute('''CREATE TABLE company_embeddings (
        id bigserial PRIMARY KEY, company_id varchar NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        profile_id varchar(64) NOT NULL REFERENCES company_embedding_profiles(id),
        input_hash varchar(64) NOT NULL, token_count integer NOT NULL CHECK(token_count>0),
        truncated boolean NOT NULL, vector vector(384) NOT NULL, created_at timestamptz NOT NULL)''')
    op.execute('CREATE UNIQUE INDEX uq_company_embedding_company_profile ON company_embeddings(company_id, profile_id)')
    op.execute('CREATE INDEX ix_company_embedding_profile_id ON company_embeddings(profile_id, id)')
    op.execute('CREATE INDEX ix_company_vector_hnsw ON company_embeddings USING hnsw (vector vector_cosine_ops)')
    op.execute('''CREATE FUNCTION company_invalidate_vectors() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN DELETE FROM company_embeddings WHERE company_id=OLD.id; RETURN NEW; END $$''')
    op.execute('''CREATE TRIGGER company_text_change BEFORE UPDATE OF content_hash ON companies
        FOR EACH ROW WHEN (OLD.content_hash IS DISTINCT FROM NEW.content_hash)
        EXECUTE FUNCTION company_invalidate_vectors()''')


def downgrade():
    op.execute('DROP TABLE company_embeddings, company_import_runs, companies, company_groups, '
               'company_embedding_profiles CASCADE')
    op.execute('DROP FUNCTION company_invalidate_vectors()')
