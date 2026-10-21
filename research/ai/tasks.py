"""Structured outputs for publication preparation."""
from typing import Literal
from pydantic import Field, model_validator
from contracts import StrictModel, Claim, Evidence

Topic = Literal['metallurgy', 'electronics', 'automotive', 'construction', 'retail_ecommerce',
                'logistics', 'financial_markets', 'energy', 'regulation', 'other_business', 'not_business']


class TopicClassification(StrictModel):
    news_id: str
    business_relevant: bool
    topics: list[Topic] = Field(min_length=1, max_length=3)
    evidence: list[Evidence] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def consistent_topics(self):
        if len(self.topics) != len(set(self.topics)):
            raise ValueError('Duplicate topics')
        if self.business_relevant == ('not_business' in self.topics):
            raise ValueError('Business relevance contradicts topics')
        if not self.business_relevant and self.topics != ['not_business']:
            raise ValueError('Non-business publication must have only not_business topic')
        return self


class EventExtraction(StrictModel):
    news_id: str
    facts: list[Claim] = Field(min_length=1, max_length=5)
    missing_data: list[str]

    @model_validator(mode='after')
    def facts_only(self):
        if any(claim.kind != 'fact' for claim in self.facts):
            raise ValueError('Extraction accepts source facts only')
        return self


class NewsPreparation(StrictModel):
    classification: TopicClassification
    extraction: EventExtraction | None

    @model_validator(mode='after')
    def same_publication(self):
        if self.classification.business_relevant != (self.extraction is not None):
            raise ValueError('Business publication requires extracted facts')
        if self.extraction and self.extraction.news_id != self.classification.news_id:
            raise ValueError('Mixed publications in preparation')
        return self
