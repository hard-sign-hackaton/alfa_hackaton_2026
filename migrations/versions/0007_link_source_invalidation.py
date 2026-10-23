"""Invalidate analytical links when non-embedding source fields change."""
from alembic import op

revision = '0007_link_source_invalidation'
down_revision = '0006_news_company_links'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE FUNCTION invalidate_company_links() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.details IS DISTINCT FROM NEW.details OR OLD.content_hash IS DISTINCT FROM NEW.content_hash THEN
                UPDATE news_company_links SET company_hash='' WHERE company_id=NEW.id;
            END IF;
            RETURN NEW;
        END $$''')
    op.execute('''CREATE TRIGGER invalidate_company_links AFTER UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION invalidate_company_links()''')
    op.execute('''CREATE FUNCTION invalidate_news_links() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.title,OLD.text,OLD.url,OLD.published_at,OLD.source_id)
                IS DISTINCT FROM (NEW.title,NEW.text,NEW.url,NEW.published_at,NEW.source_id) THEN
                UPDATE news_company_links SET news_hash='' WHERE news_id=NEW.id;
            END IF;
            RETURN NEW;
        END $$''')
    op.execute('''CREATE TRIGGER invalidate_news_links AFTER UPDATE ON news_articles
        FOR EACH ROW EXECUTE FUNCTION invalidate_news_links()''')


def downgrade():
    op.execute('DROP TRIGGER invalidate_news_links ON news_articles')
    op.execute('DROP FUNCTION invalidate_news_links()')
    op.execute('DROP TRIGGER invalidate_company_links ON companies')
    op.execute('DROP FUNCTION invalidate_company_links()')
