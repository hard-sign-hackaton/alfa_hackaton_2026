from datetime import timezone
from .dto import ParsedArticle, NewsArticleDTO
from .identity import article_id, canonical_url

def normalize_article(parsed: ParsedArticle) -> NewsArticleDTO:
    if not parsed.title or not parsed.title.strip() or not parsed.text or len(parsed.text.strip()) < 200:
        raise ValueError('missing_or_short_article_body')
    if parsed.published_at is None or parsed.published_at.tzinfo is None:
        raise ValueError('unknown_publication_date')
    url = canonical_url(parsed.url)
    return NewsArticleDTO(id=article_id(url), source_id=parsed.source_id, publisher=parsed.publisher,
        url=url, title=parsed.title.strip(), text=parsed.text.strip(),
        published_at=parsed.published_at.astimezone(timezone.utc), collected_at=parsed.collected_at,
        date_provenance=parsed.date_provenance, extraction_method=parsed.extraction_method,
        publisher_categories=parsed.publisher_categories, limitations=parsed.limitations)
