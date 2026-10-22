"""Short presentation output with citations resolved from accepted analysis claims."""
from typing import Literal
from pydantic import Field

from contracts import StrictModel, Evidence, validate_evidence
from tasks import Topic


class BriefText(StrictModel):
    text: str = Field(min_length=1, max_length=360)
    claim_ids: list[int] = Field(min_length=1, max_length=3)


class ImportanceSelection(StrictModel):
    level: Literal['high', 'medium', 'low']
    reason: BriefText


class BriefSelection(StrictModel):
    news_summary: BriefText
    short_answer: BriefText
    importance: ImportanceSelection


class Classification(StrictModel):
    business_relevant: bool
    topics: list[Topic]
    importance: Literal['high', 'medium', 'low'] | None
    importance_method: Literal['classifier', 'rules'] | None
    importance_reason: str = Field(min_length=1, max_length=360)


class CompactEvidence(StrictModel):
    news_summary: list[Evidence]
    short_answer: list[Evidence]
    importance: list[Evidence]


class CompactResult(StrictModel):
    company_id: str
    news_id: str
    status: Literal['ready', 'partial']
    news_summary: str = Field(min_length=1, max_length=360)
    short_answer: str = Field(min_length=1, max_length=360)
    classification: Classification
    evidence: CompactEvidence


def _evidence(claims):
    return list({(e.source_id, e.quote): e for claim in claims for e in claim.evidence}.values())


def resolve_brief(selection, insight, company, news, preparation, retrieved):
    validate_evidence(insight, company, news, retrieved)
    def claims(value):
        if any(i < 0 or i >= len(insight.claims) for i in value.claim_ids):
            raise ValueError('Unknown accepted claim ID')
        return [insight.claims[i] for i in dict.fromkeys(value.claim_ids)]
    primary = claims(selection.news_summary)
    if any(c.kind != 'fact' or any(e.source_id != 'news:'+news.id for e in c.evidence) for c in primary):
        raise ValueError('News summary must cite primary-news facts')
    for field in (selection.short_answer, selection.importance.reason):
        sources = {e.source_id for c in claims(field) for e in c.evidence}
        if 'news:'+news.id not in sources or not any(s.startswith((f'company:{company.id}:', f'metric:{company.id}:')) for s in sources):
            raise ValueError('Company answer and importance require news and company premises')
    if selection.importance.level == 'high' and insight.status != 'supported':
        raise ValueError('High importance requires a supported analysis')
    return CompactResult(company_id=company.id, news_id=news.id, status='ready',
        news_summary=selection.news_summary.text, short_answer=selection.short_answer.text,
        classification=Classification(business_relevant=preparation.classification.business_relevant,
            topics=preparation.classification.topics, importance=selection.importance.level,
            importance_method='classifier', importance_reason=selection.importance.reason.text),
        evidence=CompactEvidence(news_summary=_evidence(primary), short_answer=_evidence(claims(selection.short_answer)),
            importance=_evidence(claims(selection.importance.reason))))


def _shorten(text):
    if len(text) <= 360:
        return text
    fragment = text[:359]
    boundary = fragment.rfind('. ')
    return fragment[:boundary+1] if boundary >= 60 else fragment.rsplit(' ', 1)[0]+'…'


def fallback_brief(insight, company, news, preparation):
    facts = [c for c in insight.claims if c.kind=='fact' and any(e.source_id=='news:'+news.id for e in c.evidence)]
    paired = [c for c in insight.claims if c.kind=='hypothesis'
        and any(e.source_id=='news:'+news.id for e in c.evidence)
        and any(e.source_id.startswith((f'company:{company.id}:', f'metric:{company.id}:')) for e in c.evidence)]
    business = preparation.classification.business_relevant
    answer = paired[0].text if paired else 'Недостаточно данных для оценки влияния на компанию.'
    if not business:
        answer = 'Публикация не относится к деловым новостям.'
    elif insight.status=='insufficient_data':
        answer = 'Данных для точной оценки недостаточно. '+answer
    return CompactResult(company_id=company.id, news_id=news.id, status='partial' if business else 'ready',
        news_summary=_shorten(facts[0].text if facts else news.title), short_answer=_shorten(answer),
        classification=Classification(business_relevant=business, topics=preparation.classification.topics,
            importance=None if business else 'low', importance_method=None if business else 'rules',
            importance_reason='Оценка важности временно недоступна.' if business else 'Неделовая публикация исключена из деловой ленты.'),
        evidence=CompactEvidence(news_summary=_evidence(facts[:1]) or preparation.classification.evidence,
            short_answer=_evidence(paired[:1]) if business else preparation.classification.evidence,
            importance=[] if business else preparation.classification.evidence))
