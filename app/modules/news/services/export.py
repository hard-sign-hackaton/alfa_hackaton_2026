class NewsExportService:
    def __init__(self, repository):
        self.repository = repository

    def export(self, ai=False):
        return [article.ai_event() if ai else article.model_dump(mode='json')
                for article in self.repository.list_articles()]
