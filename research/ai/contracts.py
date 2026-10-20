"""Company, publication and insight contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class CompanyProfile(StrictModel):
    id: str = Field(min_length=1)
    provenance: Literal['synthetic_demo', 'dataset']
    source_ref: str = Field(min_length=1)
    okved_codes: list[str]
    okved_names: list[str]
    registration_region: str | None
    ownership_form: str | None
    annual_revenue_rub: float | None = Field(ge=0)
    banking_services: list[str]
    trade_countries: list[str] | None
    development_stage: str | None


class NewsEvent(StrictModel):
    id: str
    title: str
    text: str
    url: str
    published_at: str
    topics: list[str]
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)


class Evidence(StrictModel):
    source_id: str
    quote: str = Field(min_length=1)


class Claim(StrictModel):
    kind: Literal['fact', 'hypothesis']
    text: str = Field(min_length=1)
    evidence: list[Evidence]

    @model_validator(mode='after')
    def facts_need_evidence(self):
        if not self.evidence:
            raise ValueError('Every fact and hypothesis needs cited premises')
        return self


class Insight(StrictModel):
    company_id: str
    news_id: str
    status: Literal['supported', 'insufficient_data']
    summary: str = Field(min_length=1)
    claims: list[Claim]
    missing_data: list[str]
    follow_up_answer: str | None

    @model_validator(mode='after')
    def supported_needs_claims(self):
        if self.status == 'supported' and not self.claims:
            raise ValueError('Supported result needs claims')
        if self.status == 'insufficient_data' and not self.missing_data:
            raise ValueError('Insufficient result must identify missing data')
        return self


def evidence_sources(company, news):
    sources = {
        f'news:{news.id}': news.title + '\n' + news.text,
    }
    # Only explicitly populated fields may support company facts.
    for name, value in company.model_dump().items():
        if name not in ('id', 'source_ref', 'provenance') and value is not None and value != []:
            import json
            sources[f'company:{company.id}:{name}'] = json.dumps(value, ensure_ascii=False)
    return sources


def validate_evidence(insight, company, news):
    if insight.company_id != company.id or insight.news_id != news.id:
        raise ValueError('Cross-company/news response rejected')
    sources = evidence_sources(company, news)
    for claim in insight.claims:
        for evidence in claim.evidence:
            if evidence.source_id not in sources or evidence.quote not in sources[evidence.source_id]:
                raise ValueError('Unknown source or non-verbatim quote')
    # Checks source IDs and quote presence; semantic validation is separate.
    return insight
