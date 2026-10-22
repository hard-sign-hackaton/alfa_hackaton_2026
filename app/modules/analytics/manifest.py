"""Manifest loading for analytical document metadata."""
from __future__ import annotations

import json
from pathlib import Path

from .dto import Manifest, ManifestEntry


def source_stem(source_name: str) -> str:
    name = source_name.replace('\\', '/').rsplit('/', 1)[-1]
    return name.rsplit('.', 1)[0]


def load_manifest(path: Path | None) -> Manifest | None:
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'Manifest not found: {path}')
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid manifest JSON in {path}: {exc}') from exc
    return Manifest.model_validate(payload)


def manifest_index(manifest: Manifest | None) -> dict[str, ManifestEntry]:
    if manifest is None:
        return {}
    result: dict[str, ManifestEntry] = {}
    for entry in manifest.documents:
        keys = {entry.source_name, source_stem(entry.source_name)}
        if entry.source_stem:
            keys.add(entry.source_stem)
        if entry.id:
            keys.add(entry.id)
        for key in keys:
            if key in result:
                raise ValueError(f'Duplicate manifest key: {key}')
            result[key] = entry
    return result
