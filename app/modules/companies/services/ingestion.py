"""Load the documented JSON snapshot, validate it and persist companies."""
import json
from datetime import datetime, timezone
from pathlib import Path

from ..normalization import normalize_dataset


class CompanyImportService:
    def __init__(self, repository):
        self.repository = repository

    def import_file(self, path, dry_run=False):
        path = Path(path)
        started = datetime.now(timezone.utc)
        report = dict(
            dataset=str(path),
            started_at=started.isoformat(),
            groups=0,
            companies=0,
            inserted=0,
            updated=0,
            unchanged=0,
            validated=0,
            errors=[],
        )
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            dataset = normalize_dataset(raw)
            report['meta'] = dataset.dataset.meta
            report['groups'] = len(dataset.groups)
            report['companies'] = len(dataset.companies)
            if dry_run:
                report['validated'] = len(dataset.companies)
            else:
                for group in dataset.groups:
                    try:
                        self.repository.save_group(group)
                    except Exception as exc:
                        report['errors'].append(dict(group_id=group.group_id,
                                                     error=type(exc).__name__ + ': ' + str(exc)))
                for company in dataset.companies:
                    try:
                        outcome = self.repository.save_company(company)
                        report[outcome] += 1
                    except Exception as exc:
                        report['errors'].append(dict(company_id=company.company_id,
                                                     error=type(exc).__name__ + ': ' + str(exc)))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report['errors'].append(dict(error=type(exc).__name__ + ': ' + str(exc)))
        finally:
            finished = datetime.now(timezone.utc)
            report['finished_at'] = finished.isoformat()
            report['elapsed_seconds'] = round((finished - started).total_seconds(), 3)
            saved = report['inserted'] + report['updated'] + report['unchanged']
            if report['errors']:
                report['status'] = 'partial' if saved else 'failed'
            elif dry_run:
                report['status'] = 'validated'
            else:
                report['status'] = 'completed'
        return report

    def record_report(self, report):
        self.repository.record_run(report)
