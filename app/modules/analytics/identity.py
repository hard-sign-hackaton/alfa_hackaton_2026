"""Stable identifiers and date inference for analytical materials."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

_RU_TRANSLITERATION = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

_RU_MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5,
    'июня': 6, 'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10,
    'ноября': 11, 'декабря': 12,
}

_WORD_DATE_RE = re.compile(
    r'\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|'
    r'сентября|октября|ноября|декабря)\s+(\d{4})',
    re.IGNORECASE,
)
_DOT_DATE_RE = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b')
_HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*$')
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def slugify(value: str) -> str:
    """Convert a source filename/title to a stable ASCII identifier."""
    translated = ''.join(_RU_TRANSLITERATION.get(char, char) for char in value.lower())
    slug = re.sub(r'[^a-z0-9]+', '-', translated).strip('-')
    if slug:
        return slug
    return 'doc-' + sha256_text(value)[:8]


def document_id(source_name: str, explicit: str | None = None) -> str:
    if explicit:
        value = explicit.strip()
        if not _SAFE_ID_RE.match(value):
            raise ValueError(
                f'Document id must contain only letters, digits, dot, dash or underscore: {explicit!r}'
            )
        return value
    return slugify(source_name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1].rsplit('.', 1)[0])


def parse_manifest_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_published_at(markdown: str) -> datetime | None:
    """Read the first human-readable date from the document header."""
    head = markdown[:5000]
    match = _WORD_DATE_RE.search(head)
    if match:
        day, month, year = match.groups()
        return datetime(
            int(year), _RU_MONTHS[month.lower()], int(day), tzinfo=timezone.utc
        )
    match = _DOT_DATE_RE.search(head)
    if match:
        day, month, year = match.groups()
        return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
    return None


def first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            return match.group(1).strip()
    return None
