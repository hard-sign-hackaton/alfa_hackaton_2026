\getenv agent_password DB_AGENT_PASSWORD
CREATE USER analysis_agent PASSWORD :'agent_password';
ALTER ROLE analysis_agent SET default_transaction_read_only = on;
ALTER ROLE analysis_agent SET statement_timeout = '5s';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE TABLE company_profiles (
    id text PRIMARY KEY,
    payload jsonb NOT NULL
);
CREATE TABLE news (
    id text PRIMARY KEY,
    title text NOT NULL,
    text text NOT NULL,
    published_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS
        (to_tsvector('russian', title || ' ' || text)) STORED
);
CREATE INDEX news_search_idx ON news USING gin(search_vector);
CREATE TABLE bank_analytics (
    id text PRIMARY KEY,
    title text NOT NULL,
    text text NOT NULL,
    published_at timestamptz NOT NULL,
    url text,
    source_ref text NOT NULL,
    is_demo boolean NOT NULL DEFAULT false,
    search_vector tsvector GENERATED ALWAYS AS
        (to_tsvector('russian', title || ' ' || text)) STORED
);
CREATE INDEX bank_analytics_search_idx ON bank_analytics USING gin(search_vector);
CREATE TABLE company_metrics (
    id text NOT NULL,
    company_id text NOT NULL REFERENCES company_profiles(id),
    available_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (company_id, id)
);
CREATE TABLE analysis_pairs (
    id text PRIMARY KEY,
    company_id text NOT NULL REFERENCES company_profiles(id),
    news_id text NOT NULL REFERENCES news(id),
    UNIQUE (company_id, news_id)
);
GRANT USAGE ON SCHEMA public TO analysis_agent;
GRANT SELECT ON company_profiles, news, bank_analytics, company_metrics, analysis_pairs TO analysis_agent;
