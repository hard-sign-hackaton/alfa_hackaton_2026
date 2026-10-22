import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Invalid article URL')
    if parts.port not in (None, 80, 443):
        raise ValueError('Nonstandard URL port')
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('from', 'ref', 'yclid', 'gclid', 'fbclid', 'xtor')]
    return urlunsplit(('https', parts.hostname.lower(), parts.path or '/', urlencode(sorted(query)), ''))


def article_id(url):
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def input_hash(title, text):
    return hashlib.sha256((title + '\n\n' + text).encode()).hexdigest()
