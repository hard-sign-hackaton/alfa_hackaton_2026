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
        if mode in ('vector', 'hybrid'):
            if self.embeddings is None:
                raise ValueError('Vector search requires an embedding service')
            profile = self.embeddings.profile
            rows = self.embeddings.repository.search_pg(
                self.embeddings.encode_query(query),
                profile['id'],
                top_k,
                as_of=as_of,
            )
            if mode == 'hybrid':
                lexical = self.repository.search_text(query, top_k, as_of=as_of)
                merged, scores = {}, {}
                for hits, weight in ((rows, 2), (lexical, 1)):
                    seen = set()
                    for rank, row in enumerate(hits, 1):
                        key = row['chunk_id']
                        if key in seen:
                            continue
                        seen.add(key)
                        merged.setdefault(key, row)
                        scores[key] = scores.get(key, 0) + weight / (30 + rank)
                rows = [{**merged[key], 'retrieval_score': scores[key]} for key in
                        sorted(merged, key=lambda key: (-scores[key], key))]
        elif mode == 'text':
            rows = self.repository.search_text(query, top_k, as_of=as_of)
        else:
            raise ValueError(f'Unknown search mode: {mode}')
        return diversify(rows, top_k, per_document)
