"""Retrieve companies for a news-like text query."""
class CompanySearchService:
    def __init__(self, repository, embeddings):
        self.repository, self.embeddings = repository, embeddings

    def search(self, query, top_k=10):
        if not query.strip() or not 1 <= top_k <= 100:
            raise ValueError('Nonempty query and top-k between 1 and 100 required')
        if self.embeddings is None:
            raise ValueError('Search requires an embedding service')
        profile = self.embeddings.profile
        vector = self.embeddings.encode_query(query)
        return self.repository.search_pg(vector, profile['id'], top_k)
