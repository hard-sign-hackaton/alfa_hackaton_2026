"""Validated import contracts and normalized records for analytics storage."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .identity import parse_manifest_datetime


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str | None = None
    source_name: str = Field(min_length=1)
    source_stem: str | None = None
    title: str | None = None
    subtitle: str | None = None
    doc_type: str = Field(default='analytics', min_length=1, max_length=64)
    published_at: datetime | None = None
    language: str = Field(default='ru', min_length=2, max_length=16)
    tags: list[str] = Field(default_factory=list)
    source_uri: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r'^[0-9a-fA-F]{64}$')
    source_bytes: int | None = Field(default=None, ge=0)
    ignore_headings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator('published_at', mode='before')
    @classmethod
    def parse_published_at(cls, value):
        return parse_manifest_datetime(value)

    @field_validator('tags', 'ignore_headings')
    @classmethod
    def unique_strings(cls, values):
        result, seen = [], set()
        for value in values:
            value = str(value).strip()
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    schema_version: str = '1.0.0'
    documents: list[ManifestEntry]

    @model_validator(mode='before')
    @classmethod
    def accept_list_or_mapping(cls, value):
        if isinstance(value, list):
            return {'documents': value}
        if isinstance(value, dict) and isinstance(value.get('documents'), dict):
            documents = []
            for key, item in value['documents'].items():
                if not isinstance(item, dict):
                    raise ValueError('Manifest document entries must be objects')
                item = dict(item)
                item.setdefault('source_name', key)
                documents.append(item)
            return {**value, 'documents': documents}
        return value


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    title: str
    subtitle: str | None
    doc_type: str
    published_at: datetime
    language: str
    tags: list[str]
    source_name: str
    source_uri: str | None
    source_sha256: str | None
    source_bytes: int | None
    page_count: int | None
    markdown: str
    content_hash: str
    extraction: dict[str, Any]
    meta: dict[str, Any]
    collected_at: datetime


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    document_id: str
    ordinal: int
    kind: Literal['text', 'table', 'mixed']
    section_path: list[str]
    text: str
    embedding_text: str
    content_hash: str
    input_hash: str
    chars: int
    size: int
    pages: list[int]
    page_from: int | None
    page_to: int | None
    table_refs: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableRecord:
    id: str
    document_id: str
    table_id: str
    page: int | None
    nrows: int
    ncols: int
    rows: list[list[str]]
    source: dict[str, Any]
    warnings: list[str]
    content_hash: str


@dataclass(frozen=True)
class EmbeddingInput:
    chunk_id: str
    text: str
    input_hash: str
