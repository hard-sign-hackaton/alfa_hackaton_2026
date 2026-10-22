from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path


def parse_date(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Date must include a timezone: e.g. 2026-10-22T00:00:00+05:00')
    return result.astimezone(timezone.utc)


def period(start=None, end=None, days=None):
    end = parse_date(end) if end else datetime.now(timezone.utc)
    days = days if days is not None else int(os.getenv('NEWS_LOOKBACK_DAYS', '15'))
    if days <= 0:
        raise ValueError('Lookback must be positive')
    start = parse_date(start) if start else end - timedelta(days=days)
    if start >= end:
        raise ValueError('Expected from < to')
    return start, end


@dataclass(frozen=True)
class Settings:
    timeout: float = 20
    delay: float = 1
    max_requests: int = 3000
    max_sitemaps: int = 100
    max_bytes: int = 30_000_000

    def __post_init__(self):
        if self.delay < 1 or min(self.timeout, self.max_requests, self.max_sitemaps, self.max_bytes) <= 0:
            raise ValueError('Delay must be >= 1; all request limits must be positive')



from app.shared.config import runtime_dir
