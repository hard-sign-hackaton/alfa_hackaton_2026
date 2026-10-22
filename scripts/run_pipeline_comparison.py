"""Run the frozen before/after experiment in Docker without exposing credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['classify', 'retrieval', 'analyze', 'report'])
    parser.add_argument('--database', required=True)
    parser.add_argument('--workers', type=int, default=3, choices=range(1,5))
    parser.add_argument('--download-model', action='store_true', help='Allow fetching E5 if its cache is missing')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database):
        parser.error('Invalid database name')
    root = Path(__file__).resolve().parents[1]
    baseline_path = root / 'research/evaluation/2026-10-22/evaluation.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    raw = root / 'research/ai/live_results/dataset-final-20261022'
    raw.mkdir(parents=True, exist_ok=True)
    if not (raw / 'manifest.json').exists():
        manifest = {**baseline['summary']['manifest'], 'protocol':3,
                    'baseline_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest()}
        (raw / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    reports = root / 'research/evaluation'
    reports.mkdir(parents=True, exist_ok=True)
    docker = shutil.which('docker')
    if not docker: parser.error('Docker CLI required')
    env = os.environ.copy(); env['NEWS_DATABASE_NAME'] = args.database
    command = [docker,'compose','run','--rm','--no-deps','--entrypoint','python',
        '-v',str(root)+':/app:ro','-v',str(reports)+':/reports',
        '-e','PYTHONPATH=/app:/app/research/ai','-e','NEWS_SEARCH_MODE=hybrid','-e','TOKENIZERS_PARALLELISM=false']
    if not args.download_model:
        command += ['-e','HF_HUB_OFFLINE=1','-e','TRANSFORMERS_OFFLINE=1']
    command += ['ai-agent-semantic']
    if args.phase == 'classify':
        command += ['/app/research/ai/evaluate_dataset.py','classify','--output','/output/dataset-final-20261022','--workers',str(args.workers)]
    else:
        command += ['/app/research/ai/compare_improvements.py',args.phase,'--output','/output/dataset-final-20261022',
                    '--report-dir','/reports/2026-10-22-improved']
    raise SystemExit(subprocess.call(command,cwd=root,env=env))


if __name__ == '__main__': main()
