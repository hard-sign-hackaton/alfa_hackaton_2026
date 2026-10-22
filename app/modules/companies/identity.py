import hashlib


def text_hash(text: str) -> str:
    """Stable input hash for embedding invalidation."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
