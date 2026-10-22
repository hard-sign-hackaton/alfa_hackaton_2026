"""Find candidate companies for one stored news item using company embeddings."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from company_repository import CompanyReader
from model_config import load_environment
from news_repository import NewsReader
from retrieval import timestamp
from tasks import NewsPreparation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--news-id', required=True)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--as-of', type=timestamp, default=datetime.now(timezone.utc))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--preparation', type=Path, help='Saved validated NewsPreparation JSON; no new LLM calls')
    args = parser.parse_args()
    load_environment()
    companies, news = CompanyReader.from_env(), NewsReader.from_env()
    if companies is None or news is None:
        parser.error('NEWS_DATABASE_URL required; COMPANY_DATABASE_URL is optional')
    event = news.get_news(args.news_id, as_of=args.as_of)
    if args.preparation:
        from tasks import validate_classification
        prepared = NewsPreparation.model_validate_json(args.preparation.read_text(encoding='utf-8'))
        validate_classification(prepared.classification, event)
        event = event.model_copy(update={'topics': prepared.classification.topics})
    result = companies.match_news(event, as_of=args.as_of, limit=args.limit)
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + '\n', encoding='utf-8')
    else:
        print(content)


if __name__ == '__main__': main()
