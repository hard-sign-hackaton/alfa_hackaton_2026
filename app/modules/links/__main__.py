import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'research' / 'ai'))
from model_config import load_environment
from .repository import LinkRepository
from .service import LinkService

load_environment()
parser = argparse.ArgumentParser(description='Persist company/news matches and importance')
parser.add_argument('command', choices=['sync', 'match-news', 'stats'])
parser.add_argument('--news-id')
args = parser.parse_args()
repository = LinkRepository(os.environ['LINKS_DATABASE_URL'])
if args.command == 'stats':
    rows = repository.list(active_only=True)
    print(json.dumps({'links': len(rows), 'rated': sum(r['importance_status'] == 'ready' for r in rows),
                      'analysed': sum(bool(r['analysis_result']) for r in rows)}))
else:
    service = LinkService(repository)
    try:
        print(json.dumps(service.sync() if args.command == 'sync' else service.match_news(args.news_id), ensure_ascii=False))
    finally:
        service.close()
