"""Analyze a company/news pair stored in PostgreSQL."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from database import DatabaseError, DatabaseSettings, PostgresRepository
from database_agent import DatabaseResearchAgent
from model_config import load_environment
from provider import LangChainClient, ModelError
from retrieval import timestamp
from news_repository import NewsReader
from company_repository import CompanyReader
from bank_repository import BankReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair-id', help='ID from analysis_pairs; defaults to demo-metal-primary')
    parser.add_argument('--company-id')
    parser.add_argument('--news-id')
    parser.add_argument('--as-of', type=timestamp, default=datetime.now(timezone.utc))
    parser.add_argument('--question')
    parser.add_argument('--output', type=Path, default=Path('/output/database-agent'))
    args = parser.parse_args()
    if bool(args.company_id) != bool(args.news_id) or (args.pair_id and args.company_id):
        parser.error('Pass --pair-id or both --company-id and --news-id')
    load_environment()
    client = LangChainClient()
    try:
        if not client.api_key:
            raise ModelError('LLM_API_KEY is required')
        repository = PostgresRepository(DatabaseSettings.from_env(), news_reader=NewsReader.from_env(),
                                        company_reader=CompanyReader.from_env(), bank_reader=BankReader.from_env(), as_of=args.as_of)
        company_id, news_id = ((args.company_id, args.news_id) if args.company_id else
                               repository.get_pair(args.pair_id or 'demo-metal-primary'))
        state = DatabaseResearchAgent(repository, client, as_of=args.as_of).run(company_id, news_id, question=args.question)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'result.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (args.output / 'brief.json').write_text(json.dumps(state['brief'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': state['result']['status'], 'tool_calls': len(state['trace']),
                          'retrieved_sources': len(state['retrieved_sources']), 'model_calls': len(client.telemetry)}))
    except (ModelError, DatabaseError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')
    finally:
        if client.telemetry:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'telemetry.json').write_text(json.dumps(client.telemetry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        client.close()


if __name__ == '__main__':
    main()
