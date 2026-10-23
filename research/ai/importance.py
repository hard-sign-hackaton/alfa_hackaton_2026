"""Fast company-specific triage with exact source references, before full research."""
from typing import Literal
from pydantic import Field
from contracts import StrictModel, evidence_sources
from grounding import fragment_catalog


class ImportanceSelection(StrictModel):
    level: Literal['high', 'medium', 'low']
    reason: str = Field(min_length=1, max_length=360)
    news_fragment_id: str
    company_source_id: str


def assess(client, company, news):
    fragments = fragment_catalog(news)
    sources = {key: text for key, text in evidence_sources(company, news).items()
               if key.startswith('company:' + company.id + ':')}
    def validate(value):
        if value.news_fragment_id not in fragments or value.company_source_id not in sources:
            raise ValueError('Unknown importance premise')
    result = client._invoke('importance', dict(company_id=company.id, news_id=news.id,
        fragments=fragments, company_sources=sources, topics=news.topics), ImportanceSelection, validate)
    return {'level': result.level, 'reason': result.reason, 'evidence': [
        {'source_id': 'news:' + news.id, 'quote': fragments[result.news_fragment_id]},
        {'source_id': result.company_source_id, 'quote': sources[result.company_source_id]}]}
