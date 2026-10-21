class NewsSearchService:
    def __init__(self, repository, embeddings):
        self.repository, self.embeddings = repository, embeddings

    def search(self, query, top_k=5):
        if top_k <= 0:
            raise ValueError('top-k must be positive')
        if self.embeddings is None:
            raise ValueError('Search requires an embedding service')
        profile = self.embeddings.profile
        vector = self.embeddings.encode_query(query)
        return self.repository.search_pg(vector, profile['id'], top_k)
