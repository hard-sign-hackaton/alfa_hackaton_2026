"""Match sources into persistent pairs and assess their importance independently."""
from datetime import datetime, timezone
import logging

LOG = logging.getLogger('links')


class LinkService:
    def __init__(self, repository, classifications=None, progress=None):
        from company_repository import CompanyReader
        from news_repository import NewsReader
        from provider import LangChainClient
        self.repository = repository
        self.companies, self.news = CompanyReader.from_env(), NewsReader.from_env()
        self.client = LangChainClient()
        self.classifications = dict(classifications or {})
        self.progress = progress or (lambda stage: None)
        self.as_of = datetime.now(timezone.utc)

    def close(self):
        self.client.close()

    def classification(self, event):
        from tasks import TopicClassification, validate_classification
        value = self.classifications.get(event.id)
        if value:
            try:
                parsed = TopicClassification.model_validate(value)
                validate_classification(parsed, event)
                return parsed
            except ValueError:
                pass
        parsed = self.client.classify(event)
        self.classifications[event.id] = parsed.model_dump()
        return parsed

    def assess(self, pair, company, event):
        if pair['importance_status'] == 'ready' or pair['importance_attempts'] >= 3:
            return
        if not self.client.api_key:
            return
        from importance import assess
        self.progress('Оценка важности: ' + company.id)
        try:
            result = assess(self.client, company, event)
            self.repository.assessment(pair, result)
        except Exception as exc:
            self.repository.assessment_failed(pair)
            LOG.warning('Importance unavailable (%s)', type(exc).__name__)

    def sync(self):
        ids = self.repository.company_ids()
        count = 0
        for company_id in ids:
            self.progress('Подбор новостей: ' + company_id)
            profile = self.companies.get_company_profile(company_id, as_of=self.as_of)
            metrics = self.companies.get_company_metrics(company_id, as_of=self.as_of)
            result = self.news.match_company(profile, as_of=self.as_of, metrics=metrics,
                classifications=self.classifications, limit=10)
            selected = []
            for hit in result['candidates']:
                event = self.news.get_news(hit['id'], as_of=self.as_of)
                classified = self.classification(event)
                if not classified.business_relevant:
                    continue
                event = event.model_copy(update={'topics': classified.topics})
                pair = self.repository.ensure(company_id, event.id, method='hybrid', score=hit['retrieval_score'],
                    reasons=hit['match_reasons'], topics=classified.topics)
                selected.append(event.id)
                self.assess(pair, profile, event)
                count += 1
            self.repository.deactivate(company_id, selected)
        # Imported or explicitly selected pairs also receive an importance label.
        for pair in self.repository.list(active_only=True):
            if pair['importance_status'] != 'ready' and pair['importance_attempts'] < 3:
                profile = self.companies.get_company_profile(pair['company_id'], as_of=self.as_of)
                event = self.news.get_news(pair['news_id'], as_of=self.as_of)
                event = event.model_copy(update={'topics': pair['topics']})
                self.assess(pair, profile, event)
        return {'matched': count, 'telemetry': self.client.telemetry}

    def match_news(self, news_id, limit=5):
        event = self.news.get_news(news_id, as_of=self.as_of)
        classification = self.classification(event)
        event = event.model_copy(update={'topics': classification.topics})
        result = self.companies.match_news(event, as_of=self.as_of, limit=limit)
        for hit in result['candidates']:
            pair = self.repository.ensure(hit['id'], event.id, method='company_embedding', score=hit['similarity'],
                reasons=[{'kind': 'semantic', 'matched_topics': hit['matched_topics'],
                          'limitation': 'Сходство определяет кандидатов, а не доказанное влияние.'}], topics=classification.topics)
            company = self.companies.get_company_profile(hit['id'], as_of=self.as_of)
            self.assess(pair, company, event)
        return result
