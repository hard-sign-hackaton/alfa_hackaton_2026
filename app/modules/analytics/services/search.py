"""Retrieval over stored analytical chunks with document diversification."""
from __future__ import annotations

from .embedding import AnalyticsEmbeddingService


def diversify(rows, top_k: int, per_document: int):
    if per_document <= 0:
        raise ValueError('per_document must be positive')
    counts: dict[str, int] = {}
    result = []
    for row in rows:
        document_id = row['document_id']
        if counts.get(document_id, 0) >= per_document:
            continue
        counts[document_id] = counts.get(document_id, 0) + 1
        result.append(row)
        if len(result) >= top_k:
            break
    return result


class AnalyticsSearchService:
    def __init__(self, repository, embeddings: AnalyticsEmbeddingService | None = None):
        self.repository = repository
        self.embeddings = embeddings

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        as_of=None,
        mode: str = 'text',
        per_document: int = 2,
    ):
        if not query.strip() or not 1 <= top_k <= 100:
            raise ValueError('Nonempty query and top-k between 1 and 100 required')
        if mode == 'vector':
            if self.embeddings is None:
                raise ValueError('Vector search requires an embedding service')
            profile = self.embeddings.profile
            rows = self.embeddings.repository.search_pg(
                self.embeddings.encode_query(query),
                profile['id'],
                top_k,
                as_of=as_of,
            )
        elif mode == 'text':
            rows = self.repository.search_text(query, top_k, as_of=as_of)
        else:
            raise ValueError(f'Unknown search mode: {mode}')
        return diversify(rows, top_k, per_document)
