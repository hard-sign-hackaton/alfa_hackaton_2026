import time
from urllib.parse import urljoin
import requests

class HttpClient:
    def __init__(self, source, settings):
        self.source, self.settings = source, settings
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'AlfaHackNewsPipeline/1.0'
        self.count, self.last = 0, 0.0

    def get(self, url):
        # Redirects are followed manually so a publisher cannot redirect into another host.
        for _ in range(6):
            if not self.source.allowed(url):
                raise ValueError('off_domain_url')
            redirect = False
            for attempt in range(3):
                if self.count >= self.settings.max_requests:
                    raise RuntimeError('request_budget_exhausted')
                time.sleep(max(0, self.settings.delay - (time.monotonic() - self.last)))
                self.count += 1
                self.last = time.monotonic()
                try:
                    with self.session.get(url, timeout=self.settings.timeout, allow_redirects=False, stream=True) as r:
                        if r.status_code in (301, 302, 303, 307, 308):
                            url = urljoin(url, r.headers['Location'])
                            redirect = True
                            break
                        if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                            retry = r.headers.get('Retry-After', '')
                            time.sleep(min(60, max(2 ** attempt, int(retry) if retry.isdigit() else 0)))
                            continue
                        r.raise_for_status()
                        chunks, size = [], 0
                        for chunk in r.iter_content(65536):
                            size += len(chunk)
                            if size > self.settings.max_bytes:
                                raise ValueError('response_too_large')
                            chunks.append(chunk)
                        content = b''.join(chunks)
                        # Publishers in this set serve UTF-8; do not use requests' ISO-8859-1 default.
                        encoding = r.encoding if r.encoding and r.encoding.lower() not in ('iso-8859-1', 'ascii') else 'utf-8'
                        return url, content, content.decode(encoding, errors='replace')
                except requests.HTTPError:
                    # Permanent HTTP failures (e.g. 403/404) are not transient network errors.
                    raise
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            if not redirect:
                raise RuntimeError('request_failed')
        raise ValueError('redirect_limit')

    def close(self):
        self.session.close()
