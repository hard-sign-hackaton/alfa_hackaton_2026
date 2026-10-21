from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import time
import requests
from ..normalization import normalize_article
from ..parsers.discovery import discover
from ..parsers.http import HttpClient

def collect_source(source, start, end, limit, settings, save, client_factory=HttpClient):
    started = time.monotonic()
    report = dict(source=source.id, started_at=datetime.now(timezone.utc).isoformat(),
                  from_date=start.isoformat(), to_date=end.isoformat(), limit=limit,
                  discovered=0, discovery_outside_period=0, attempted=0, saved=0,
                  inserted=0, updated=0, unchanged=0, outside_period=0,
                  truncated=False, errors=[])
    client = client_factory(source, settings)
    try:
        references = discover(source, client, start, end, settings, report)
        for ref in references:
            report['discovered'] += 1
            report['attempted'] += 1
            try:
                final_url, _, html = client.get(ref['url'])
                if not source.is_article(final_url):
                    raise ValueError('redirect_not_article')
                article = normalize_article(source.parse(final_url, html, ref))
                if not start <= article.published_at < end:
                    report['outside_period'] += 1
                    continue
                outcome = save(article)
                report[outcome] += 1
                report['saved'] += 1
                if limit is not None and report['saved'] >= limit:
                    report['truncated'] = True
                    break
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                report['errors'].append(dict(url=ref['url'], error=str(exc)))
                if isinstance(exc, RuntimeError):
                    report['truncated'] = True
                    break
    except Exception as exc:
        # Boundaries isolate a worker (including persistence failures) from the other sites.
        report['fatal_error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        client.close()
        report['requests'] = client.count
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['status'] = 'failed' if report.get('fatal_error') or (report['saved'] == 0 and report['errors']) else 'partial' if report['errors'] or report['truncated'] else 'completed'
    return report


def collect_parallel(sources, start, end, limit, settings, save, client_factory=HttpClient):
    with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix='news-source') as pool:
        jobs = [pool.submit(collect_source, s, start, end, limit, settings, save, client_factory) for s in sources]
        return [job.result() for job in jobs]


class NewsIngestionService:
    def __init__(self, repository, sources, settings):
        self.repository, self.sources, self.settings = repository, sources, settings

    def collect(self, start, end, limit=None):
        self.repository.seed([source.source for source in self.sources])
        reports = collect_parallel(self.sources, start, end, limit, self.settings, self.repository.save)
        return dict(settings=asdict(self.settings), workers=len(reports), reports=reports,
            coverage='Available discovery documents only; article/request limits and publisher coverage may truncate the period.')

    def record_reports(self, result):
        for report in result['reports']:
            self.repository.record_run(report)
