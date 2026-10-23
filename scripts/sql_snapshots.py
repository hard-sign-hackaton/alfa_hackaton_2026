"""Tables included in the portable startup snapshot, in dependency order."""
from pathlib import Path

SEED_ROOT = Path(__file__).resolve().parents[1] / 'database' / 'seeds'
GROUPS = {
    'news': ('01_news.sql', ('news_sources', 'news_articles', 'news_embedding_profiles', 'news_embeddings')),
    'companies': ('02_companies.sql', ('company_groups', 'companies', 'company_embedding_profiles', 'company_embeddings')),
    'bank': ('03_bank.sql', ('analytics_documents', 'analytics_chunks', 'analytics_tables',
                            'analytics_embedding_profiles', 'analytics_chunk_embeddings')),
    'links': ('04_links.sql', ('news_company_links',)),
    'legacy': ('05_agent.sql', ('company_profiles', 'news', 'bank_analytics', 'company_metrics', 'analysis_pairs')),
}
