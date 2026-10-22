"""Resolve model-selected fragment IDs into exact, server-owned source text."""
import re
from typing import Literal

from pydantic import Field, model_validator
from contracts import StrictModel, Evidence, Claim
from tasks import Topic, TopicClassification, EventExtraction


class CitationChoice(StrictModel):
    source_id: str | None = None
    fragment_id: str | None = None
    quote: str | None = None

    @model_validator(mode='after')
    def one_reference(self):
        if (self.fragment_id is None) == (self.quote is None):
            raise ValueError('Choose one fragment_id or a legacy exact quote')
        return self


class ClassificationSelection(StrictModel):
    news_id: str | None = None
    business_relevant: bool
    topics: list[Topic] = Field(min_length=1, max_length=3)
    evidence: list[CitationChoice] = Field(min_length=1, max_length=3)


class FactSelection(StrictModel):
    kind: Literal['fact']
    text: str = Field(min_length=1)
    evidence: list[CitationChoice] = Field(min_length=1)


class ExtractionSelection(StrictModel):
    news_id: str | None = None
    facts: list[FactSelection] = Field(min_length=1, max_length=5)
    missing_data: list[str]


def fragment_catalog(news):
    """Keep original bytes within each fragment, including punctuation and spaces."""
    pieces = [news.title]
    for sentence in re.split(r'(?<=[.!?…])\s+|\n+', news.text):
        # Fixed windows also handle sources with no sentence punctuation.
        pieces.extend(sentence[start:start + 600] for start in range(0, len(sentence), 600))
    unique = list(dict.fromkeys(piece for piece in pieces if piece.strip()))
    return {f'f{index:04d}': text for index, text in enumerate(unique)}


def resolve_citation(choice, news, catalog):
    if choice.source_id is not None and choice.source_id != 'news:' + news.id:
        raise ValueError('Foreign publication citation')
    if choice.fragment_id is not None:
        if choice.fragment_id not in catalog:
            raise ValueError('Unknown fragment ID')
        quote = catalog[choice.fragment_id]
    else:
        quote = choice.quote
    if not quote or quote not in news.title + '\n' + news.text:
        raise ValueError('Non-verbatim publication citation')
    return Evidence(source_id='news:' + news.id, quote=quote)


def resolve_selection(value, news, catalog):
    if value.news_id is not None and value.news_id != news.id:
        raise ValueError('Foreign publication ID')
    if isinstance(value, ClassificationSelection):
        return TopicClassification(news_id=news.id, business_relevant=value.business_relevant,
            topics=value.topics, evidence=[resolve_citation(e, news, catalog) for e in value.evidence])
    return EventExtraction(news_id=news.id, missing_data=value.missing_data,
        facts=[Claim(kind=fact.kind, text=fact.text,
            evidence=[resolve_citation(e, news, catalog) for e in fact.evidence]) for fact in value.facts])


def finalize_insight(insight, company, news):
    """A summary can only repeat accepted claims; it cannot introduce another fact.

    Citation presence still does not establish semantic entailment of a claim.
    """
    paired = [claim for claim in insight.claims if claim.kind == 'hypothesis'
        and any(e.source_id == 'news:' + news.id for e in claim.evidence)
        and any(e.source_id.startswith((f'company:{company.id}:', f'metric:{company.id}:')) for e in claim.evidence)]
    if insight.status == 'supported' and not paired:
        insight.status = 'insufficient_data'
        insight.missing_data = list(dict.fromkeys(insight.missing_data + ['Обоснованный канал влияния новости на выбранную компанию']))
    facts = [claim for claim in insight.claims if claim.kind == 'fact'
        and any(e.source_id == 'news:' + news.id for e in claim.evidence)]
    selected = facts[:1] + paired[:1]
    if not selected:
        selected = insight.claims[:2]
    prefix = 'Данных для оценки влияния на компанию недостаточно. ' if insight.status == 'insufficient_data' else ''
    insight.summary = prefix + (' '.join(dict.fromkeys(claim.text for claim in selected)) or 'Нет подтверждённых утверждений.')
    return insight
