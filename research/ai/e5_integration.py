"""Real E5 query/pgvector check confined to the disposable news database."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from app.modules.news.bootstrap import repositories
from app.modules.news.models import Article, Embedding, EmbeddingProfile
from app.modules.news.normalization import normalize_article
from app.modules.news.parsers.registry import SOURCES
from app.modules.news.services.embedding import NewsEmbeddingService
from app.shared.embeddings.e5 import E5Provider
from news_repository import NewsReader


def main():
    url = os.environ['DATABASE_URL']
    if not make_url(url).database.endswith('_test') or not make_url(os.environ['NEWS_DATABASE_URL']).database.endswith('_test'):
        raise ValueError('E5 smoke test requires separate *_test databases')
    repository, vectors = repositories(url)
    before = {profile['id'] for profile in vectors.list_profiles()}
    cutoff = datetime.now(timezone.utc)
    ids, profile_id = [], None
    try:
        repository.seed([value.source for value in SOURCES.values()])
        for source_id, filename, article_url in [
            ('kommersant','kom_article.html','https://www.kommersant.ru/doc/9043090'),
            ('interfax','inter_article.html','https://www.interfax.ru/business/1123769')]:
            content = (Path('/app/research/news') / filename).read_text(encoding='utf-8')
            article = normalize_article(SOURCES[source_id].parse(article_url,content,None))
            if repository.get_article(article.id, as_of=cutoff) is not None:
                raise ValueError('Test article already exists; refusing to overwrite it')
            repository.save(article); ids.append(article.id)
        provider = E5Provider()
        embeddings = NewsEmbeddingService(vectors,provider)
        profile_id = embeddings.profile['id']
        result = embeddings.run(batch_size=2)
        reader = NewsReader(os.environ['NEWS_DATABASE_URL'],mode='semantic',embeddings=embeddings)
        sources = reader.search_news('спрос на сталь',as_of=cutoff,exclude_id=ids[1],limit=1)
        if not sources or sources[0].source_id != 'news:' + ids[0] or not sources[0].text:
            raise ValueError('Real E5 search did not return the expected saved steel article')
        print(json.dumps({'model':provider.info.model,'revision':provider.info.revision,
                          'saved':result['saved'],'sources':len(sources),'text_and_dates':True}))
    finally:
        with repository.session.begin() as session:
            session.execute(delete(Article).where(Article.id.in_(ids)))
            if profile_id and profile_id not in before:
                session.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id==profile_id,
                    ~select(Embedding.id).where(Embedding.profile_id==profile_id).exists()))


if __name__ == '__main__':
    main()
