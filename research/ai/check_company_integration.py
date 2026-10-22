"""Read-only integration evidence for a prepared research database."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from sqlalchemy import select, text
from app.modules.companies.models import Company
from company_repository import CompanyReader
from news_repository import NewsReader
from tasks import TopicClassification, validate_classification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--classifications', type=Path, help='Optional cached classification directory')
    args = parser.parse_args()
    companies, news = CompanyReader.from_env(), NewsReader.from_env()
    if companies is None or news is None:
        parser.error('NEWS_DATABASE_URL is required')
    now = datetime.now(timezone.utc)
    with companies.session() as session:
        ids = list(session.scalars(select(Company.id).order_by(Company.id)))
        earliest = session.scalar(select(Company.imported_at).order_by(Company.imported_at).limit(1))
        counts = dict(session.execute(text('SELECT (SELECT count(*) FROM news_articles) AS news, '
            '(SELECT count(*) FROM news_embeddings) AS news_vectors, '
            '(SELECT count(*) FROM companies) AS companies, '
            '(SELECT count(*) FROM company_embeddings) AS company_vectors')).one()._mapping)
        permissions = dict(session.execute(text("SELECT current_user AS role, "
            "has_table_privilege(current_user, 'companies', 'SELECT') AS company_read, "
            "has_table_privilege(current_user, 'companies', 'INSERT') AS company_insert, "
            "has_table_privilege(current_user, 'news_articles', 'UPDATE') AS news_update")).one()._mapping)
    assert counts == dict(news=153, news_vectors=153, companies=12, company_vectors=12), counts
    assert permissions['company_read'] and not permissions['company_insert'] and not permissions['news_update']
    profiles = []
    for company_id in ids:
        profile = companies.get_company_profile(company_id, as_of=now)
        metrics = companies.get_company_metrics(company_id, as_of=now)
        assert metrics and all(source.company_id == company_id for source in metrics)
        profiles.append(dict(company_id=company_id, okved=profile.okved_codes, payment_sources=len(metrics)))
    before = earliest - timedelta(seconds=1)
    try:
        companies.get_company_profile(ids[0], as_of=before)
    except ValueError:
        pass
    else:
        raise AssertionError('Future company snapshot was exposed')
    sample_ids = [
        '6fd817b6b18a3c411d8fd211415892665b9b818b72cc3d64c13f61fe937b10b7',
        '9bfb602e317f62a40ab4bd588e14178869a9ee317e02572c6083315e6f4fd66c',
        '1056dce3cfa282c8aee1ecd173c5273091e4715beda0b3930c733a3261c46b2e',
    ]
    reverse = []
    for news_id in sample_ids:
        event = news.get_news(news_id, as_of=now)
        result = companies.match_news(event, as_of=now, limit=5)
        assert result['candidates'] and all(row['id'] in ids for row in result['candidates'])
        row = dict(title=event.title, **result)
        if args.classifications:
            saved = json.loads((args.classifications / (news_id + '.json')).read_text(encoding='utf-8'))
            classification = TopicClassification.model_validate(saved['result'])
            validate_classification(classification, event)
            classified = event.model_copy(update={'topics': classification.topics})
            row['reranked'] = companies.match_news(classified, as_of=now, limit=5)
            if news_id == sample_ids[0]:
                assert row['reranked']['candidates'][0]['okved_code'].startswith('45.')
        reverse.append(row)
    event = news.get_news(sample_ids[0], as_of=now)
    assert companies.match_news(event, as_of=before, limit=5)['candidates'] == []
    company_profile = companies.vectors.list_profiles()[0]
    news_profile = news.vectors.list_profiles()[0]
    assert all(company_profile[key] == news_profile[key] for key in ('model', 'revision', 'dimensions', 'normalized'))
    result = dict(checked_at=now.isoformat(), counts=counts, permissions=permissions,
        company_profile=company_profile, news_profile=news_profile, profiles=profiles,
        reverse_matches=reverse, cutoff_checks_passed=True,
        limitations=['Reverse matches are candidates only, without relevance labels.',
            'Company snapshots are current versions; no historical profile versions are stored.',
            'Payment dates and observation period are absent.'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(counts=counts, readonly=True, cutoff_checks_passed=True)))


if __name__ == '__main__':
    main()
