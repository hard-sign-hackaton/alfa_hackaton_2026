"""Find explainable news candidates for a company; no LLM API calls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from dataset import CompanyDataset
from model_config import load_environment
from news_repository import NewsReader
from company_repository import CompanyReader
from retrieval import timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--dataset', type=Path, help='Prepared company/payment JSON; otherwise read company DB')
    parser.add_argument('--as-of', type=timestamp, default=datetime.now(timezone.utc))
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    load_environment()
    reader = NewsReader.from_env()
    if reader is None:
        parser.error('NEWS_DATABASE_URL required')
    if args.dataset:
        dataset = CompanyDataset(args.dataset)
        company, metrics = dataset.profile(args.company_id), dataset.metrics(args.company_id, as_of=args.as_of)
    else:
        companies = CompanyReader.from_env()
        if companies is None:
            parser.error('COMPANY_DATABASE_URL or NEWS_DATABASE_URL required')
        company = companies.get_company_profile(args.company_id, as_of=args.as_of)
        metrics = companies.get_company_metrics(args.company_id, as_of=args.as_of)
    result = reader.match_company(company, as_of=args.as_of, metrics=metrics, limit=args.limit)
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + '\n', encoding='utf-8')
    else:
        print(content)


if __name__ == '__main__': main()
