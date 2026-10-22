from pathlib import Path

from app.shared.config import PROJECT_ROOT, runtime_dir as shared_runtime_dir

DEFAULT_DATASET = PROJECT_ROOT / 'docs' / 'companies' / 'companies_analytics.json'


def dataset_path(value=None):
    return Path(value) if value else DEFAULT_DATASET


def runtime_dir():
    return shared_runtime_dir('companies')
