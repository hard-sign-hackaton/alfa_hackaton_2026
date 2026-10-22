import os
from datetime import datetime, timezone
from pathlib import Path

from app.shared.config import PROJECT_ROOT


def runtime_dir() -> Path:
    return Path(
        os.getenv(
            'ANALYTICS_RUNTIME_DIR',
            str(PROJECT_ROOT.parent / 'local_runtime' / 'analytics'),
        )
    )


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'Invalid ISO date/time: {value}') from exc
    if parsed.tzinfo is None:
        if len(value) == 10:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            raise ValueError('Date/time must include a timezone')
    return parsed.astimezone(timezone.utc)
