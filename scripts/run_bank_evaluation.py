"""Run the bank-context functionality check in Docker."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['check', 'analyze', 'compact', 'report'])
    parser.add_argument('--database', required=True)
    parser.add_argument('--reuse-preparation', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database):
        parser.error('Invalid database name')
    root = Path(__file__).resolve().parents[1]
    if args.reuse_preparation and not (root/'research/ai/live_results/dataset-final-20261022/classification').is_dir():
        parser.error('Local dataset-final-20261022 preparation cache is missing')
    docker = shutil.which('docker')
    if not docker:
        parser.error('Docker CLI required')
    reports = root/'research/evaluation'
    reports.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy(); env['NEWS_DATABASE_NAME'] = args.database
    command = [docker, 'compose', 'run', '--rm', '--no-deps', '--entrypoint', 'python',
        '-v', str(root)+':/app:ro', '-v', str(reports)+':/reports',
        '-e', 'PYTHONPATH=/app:/app/research/ai', '-e', 'BANK_SEARCH_MODE=hybrid',
        '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
        'ai-agent-semantic', '/app/research/ai/evaluate_bank_context.py', args.phase,
        '--report-dir', '/reports/2026-10-22-bank']
    if args.reuse_preparation:
        command += ['--prepared', '/output/dataset-final-20261022']
    raise SystemExit(subprocess.call(command, cwd=root, env=env))


if __name__ == '__main__': main()
