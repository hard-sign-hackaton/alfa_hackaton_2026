"""News-specific chunking/aggregation and orchestration; model implementation is shared."""
from dataclasses import asdict
import hashlib
import json
import numpy as np
from app.shared.embeddings.provider import EmbeddingProvider, normalize

PREPARATION = 'e5-title64-body384-overlap64-mean-l2-v1'

class NewsEmbeddingService:
    def __init__(self, repository, provider: EmbeddingProvider):
        self.repository, self.provider = repository, provider

    @property
    def profile(self):
        profile = dict(**asdict(self.provider.info), preparation=PREPARATION)
        profile['id'] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        return profile

    def encode_query(self, text):
        return self.provider.encode_query(text)

    def chunks(self, title, text):
        title_tokens = self.provider.tokenize(title)[:64]
        tokens = self.provider.tokenize(text)
        if not tokens:
            raise ValueError('Empty tokenized document')
        chunks = []
        for start in range(0, len(tokens), 320):
            body = tokens[start:start + 384]
            ids = self.provider.document_window(title_tokens, body)
            if len(ids) > self.provider.max_input_tokens:
                raise ValueError('Chunk exceeds model context')
            chunks.append(ids)
            if start + 384 >= len(tokens):
                break
        return chunks


    def encode_articles(self, articles):
        windows, counts = [], []
        for article in articles:
            chunks = self.chunks(article.title, article.text)
            windows.extend(chunks)
            counts.append(len(chunks))
        vectors = self.provider.encode_windows(windows)
        if len(vectors) != len(windows):
            raise ValueError('Provider returned wrong window count')
        offset, result = 0, []
        for count in counts:
            result.append((normalize(np.mean(vectors[offset:offset + count], axis=0)), count))
            offset += count
        return result

    def run(self, batch_size=16):
        if batch_size <= 0:
            raise ValueError('Batch size must be positive')
        profile = self.profile
        self.repository.ensure_profile(profile)
        saved, raced = 0, 0
        while True:
            articles = self.repository.pending(profile['id'], batch_size)
            if not articles:
                break
            outputs = self.encode_articles(articles)
            if len(outputs) != len(articles):
                raise ValueError('Provider returned wrong batch length')
            for article, (vector, chunks) in zip(articles, outputs):
                if self.repository.save_embedding(article, profile['id'], normalize(vector), chunks):
                    saved += 1
                else:
                    raced += 1
            if raced:
                # Avoid an unbounded loop during concurrent edits; next manual run can finish.
                break
        return dict(profile=profile, saved=saved, concurrently_changed=raced)
