from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

@dataclass(frozen=True)
class SourceDTO:
    id: str
    name: str
    host: str
    sitemap: str
    rss: str

@dataclass(frozen=True)
class ParsedArticle:
    source_id: str
    publisher: str
    url: str
    title: str | None
    text: str | None
    published_at: datetime | None
    collected_at: datetime
    date_provenance: str | None
    extraction_method: str | None
    publisher_categories: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class EmbeddingInput:
    id: str
    title: str
    text: str
    content_hash: str

class NewsArticleDTO(BaseModel):
    # Retain the published schema title; the Python type is explicitly a DTO.
    model_config = ConfigDict(extra='forbid', title='IngestedNews')
    schema_version: Literal['1.0.0'] = '1.0.0'
    id: str
    source_id: str
    publisher: str
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    url: str
    published_at: datetime
    collected_at: datetime
    publisher_categories: list[str] = Field(default_factory=list)
    date_provenance: str
    extraction_method: str
    extraction_status: Literal['body_extracted'] = 'body_extracted'
    limitations: list[str] = Field(default_factory=list)

    @field_validator('published_at', 'collected_at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Timezone required')
        return value

    def ai_event(self):
        return dict(id=self.id, title=self.title, text=self.text, url=self.url,
                    published_at=self.published_at.isoformat(), topics=[], regions=[], countries=[])
