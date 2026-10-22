"""Run the research protocol in the existing semantic-agent Docker image."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['classify', 'retrieve', 'select', 'review', 'analyze', 'report'])
    parser.add_argument('--database', required=True, help='Existing restored news database, not a URL or password')
    parser.add_argument('--run-name', default='dataset-20261022')
    parser.add_argument('--report-name', help='Report directory name; defaults to run-name')
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 5))
    parser.add_argument('--refresh-analysis-selection', action='store_true')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database):
        parser.error('Invalid database name')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', args.run_name) or (args.report_name and not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', args.report_name)):
        parser.error('Invalid run name')
    repo = Path(__file__).resolve().parents[1]
    docker = shutil.which('docker')
    if not docker:
        parser.error('Docker CLI required')
    env = os.environ.copy()
    env['NEWS_DATABASE_NAME'] = args.database
    command = [docker, 'compose', 'run', '--rm', '--no-deps', '--entrypoint', 'python',
               '-v', str(repo) + ':/app:ro', '-e', 'PYTHONPATH=/app:/app/research/ai',
               '-e', 'NEWS_SEARCH_MODE=semantic', '-e', 'TOKENIZERS_PARALLELISM=false']
    output = '/output/' + args.run_name
    if args.phase == 'report':
        reports = repo / 'research/evaluation'
        reports.mkdir(parents=True, exist_ok=True)
        command += ['-v', str(reports) + ':/reports', 'ai-agent-semantic',
                    '/app/research/ai/build_evaluation_report.py', '--raw', output,
                    '--output', '/reports/' + (args.report_name or args.run_name)]
    else:
        command += ['ai-agent-semantic', '/app/research/ai/evaluate_dataset.py', args.phase,
                    '--output', output, '--workers', str(args.workers)]
        if args.refresh_analysis_selection:
            command.append('--refresh-analysis-selection')
    raise SystemExit(subprocess.call(command, cwd=repo, env=env))


if __name__ == '__main__':
    main()
