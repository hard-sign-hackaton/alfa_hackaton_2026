"""Synthetic publication ingestion followed by the production matching/research services."""
from datetime import datetime, timezone
import os
from uuid import uuid4


class ExpertPipeline:
    def __init__(self, links, runner):
        self.links, self.runner, self.embeddings = links, runner, None

    def __call__(self, event, company_id, progress, cancelled):
        from app.modules.news.bootstrap import repositories
        from app.modules.news.dto import NewsArticleDTO, EmbeddingInput, SourceDTO
        from app.modules.news.identity import input_hash
        from app.modules.links.service import LinkService
        from news_repository import NewsReader

        def report(phase, stage, **values):
            if cancelled():
                raise ValueError('Scenario stopped')
            progress(phase, stage, **values)

        url = os.environ.get('EXPERT_DATABASE_URL')
        if not url or not self.links:
            raise ValueError('Expert ingestion storage is not configured')
        repository, vectors = repositories(url)
        source_id = 'expert-demo:' + event['id'].split(':')[1]
        article = NewsArticleDTO(id=event['id'], source_id=source_id, publisher='Тестовый сценарий',
            title=event['title'], text=event['text'], url=event['url'],
            published_at=datetime.fromisoformat(event['published_at']), collected_at=datetime.now(timezone.utc),
            date_provenance='synthetic_arrival', extraction_method='expert_scenario',
            limitations=['Вымышленная новость. Только поступление смоделировано; обработка выполняется реально.'])
        report('ingesting', 'Сохранение и проверка дублей')
        repository.seed([SourceDTO(source_id, 'Тестовый сценарий', 'expert-demo.invalid', '', '')])
        if self.embeddings is None:
            self.embeddings = NewsReader.from_env()._semantic().embeddings
        outcome = repository.save_deduplicated(article, embeddings=self.embeddings, dedup_source_id=source_id)
        if outcome.outcome == 'duplicate':
            return {'duplicate': True, 'duplicate_of': outcome.original_id}
        report('embedding', 'Расчёт эмбеддинга новости')
        profile = self.embeddings.profile
        vectors.ensure_profile(profile)
        record = EmbeddingInput(article.id, article.title, article.text, input_hash(article.title, article.text))
        vector, chunks = self.embeddings.encode_articles([record])[0]
        if not vectors.save_embedding(record, profile['id'], vector, chunks):
            raise ValueError('Publication changed during embedding')
        report('classifying', 'Классификация новости моделью')
        service = LinkService(self.links, progress=lambda stage: report('assessing', stage))
        selected_state = None
        try:
            limit = max(1, min(5, int(os.environ.get('EXPERT_MATCH_LIMIT', '5'))))
            result = service.match_news(article.id, limit=limit,
                on_matched=lambda: report('matched', 'Компании подобраны по эмбеддингам'),
                on_classified=lambda: report('matching', 'Поиск компаний по эмбеддингам'))
            rows = self.links.list(news_id=article.id, active_only=True, include_demo=True)
            report('matched', 'Подбор завершён · запуск полного разбора', matches=rows)
            for hit in result['candidates']:
                pair = next(row for row in rows if row['company_id'] == hit['id'])
                run_id = uuid4().hex
                if not self.links.claim_analysis(pair, run_id):
                    raise ValueError('Could not claim analysis')
                try:
                    report('analyzing', 'Полный разбор: ' + hit['id'], matches=rows)
                    state = self.runner(hit['id'], article.id,
                        lambda stage: report('analyzing', hit['id'] + ' · ' + stage))
                    if cancelled():
                        raise ValueError('Scenario stopped')
                    if not state.get('is_demo'):
                        raise ValueError('Synthetic publication metadata was lost')
                    if not self.links.analysis(pair, state, run_id=run_id):
                        raise ValueError('Source changed during analysis')
                    if hit['id'] == company_id:
                        selected_state = state
                    rows = self.links.list(news_id=article.id, active_only=True, include_demo=True)
                    report('analyzing', 'Разбор сохранён: ' + hit['id'], matches=rows, state=selected_state)
                except Exception:
                    self.links.analysis_failed(pair, run_id)
                    raise
            return {'state': selected_state, 'matches': rows, 'telemetry': service.client.telemetry,
                    'not_business': not service.classifications[article.id]['business_relevant']}
        finally:
            service.close()
