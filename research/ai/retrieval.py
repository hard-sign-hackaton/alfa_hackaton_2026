"""Retrieved evidence shared by tools, analysis and presentation adapters."""
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator

from contracts import StrictModel


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timezone is required')
    return result


class RetrievedSource(StrictModel):
    source_id: str = Field(min_length=1, max_length=250)
    kind: Literal['news', 'bank', 'metric']
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=6000)
    published_at: str = Field(json_schema_extra={'format': 'date-time'})
    locator: str = Field(min_length=1, max_length=1000)
    url: str | None = None
    company_id: str | None = None
    is_demo: bool = False
    publisher: str | None = None
    collected_at: str | None = None

    @model_validator(mode='after')
    def identity(self):
        timestamp(self.published_at)
        if self.collected_at is not None:
            timestamp(self.collected_at)
        prefix = f'metric:{self.company_id}:' if self.kind == 'metric' else self.kind + ':'
        if not self.source_id.startswith(prefix) or self.source_id == prefix:
            raise ValueError('Invalid source namespace')
        if self.kind == 'metric' and not self.company_id:
            raise ValueError('Metric requires a company')
        if self.kind != 'metric' and self.company_id is not None:
            raise ValueError('Public source cannot carry a private company scope')
        if self.url is not None:
            parsed = urlparse(self.url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Source URL must be a public HTTP(S) address without credentials')
        return self


def source_registry(values, company, news, *, as_of=None):
    """Accept only server-retrieved sources; never take this registry from a model."""
    from contracts import evidence_sources
    reserved = set(evidence_sources(company, news))
    registry = {}
    for value in values or []:
        source = RetrievedSource.model_validate(value.model_dump() if isinstance(value, RetrievedSource) else value)
        if source.company_id is not None and source.company_id != company.id:
            raise ValueError('Foreign company source')
        if source.source_id in reserved or source.source_id in registry:
            raise ValueError('Duplicate or reserved source ID')
        if as_of is not None and timestamp(source.published_at) > timestamp(as_of):
            raise ValueError('Future source rejected')
        registry[source.source_id] = source
    return registry
