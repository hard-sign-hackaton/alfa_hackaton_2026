"""Chunk-level embeddings for analytical materials."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

import numpy as np

from app.shared.embeddings.provider import EmbeddingProvider, normalize

PREPARATION = 'e5-chunk-embedding-text-passage-v1'


class AnalyticsEmbeddingService:
    def __init__(self, repository, provider: EmbeddingProvider):
        self.repository = repository
        self.provider = provider

    @property
    def profile(self):
        profile = dict(**asdict(self.provider.info), preparation=PREPARATION)
        profile['id'] = hashlib.sha256(
            json.dumps(profile, sort_keys=True).encode('utf-8')
        ).hexdigest()
        return profile

    def encode_query(self, text):
        return self.provider.encode_query(text)

    def _window(self, text: str):
        tokens = self.provider.tokenize(text)
        overhead = len(self.provider.document_window([], []))
        budget = self.provider.max_input_tokens - overhead
        if budget <= 0:
            raise ValueError('Embedding context overhead exceeds model limit')
        return self.provider.document_window([], tokens[:budget])

    def encode_chunks(self, chunks):
        windows = [self._window(chunk.text) for chunk in chunks]
        if not windows:
            return np.empty((0, self.provider.info.dimensions), dtype=np.float32)
        vectors = self.provider.encode_windows(windows)
        if len(vectors) != len(windows):
            raise ValueError('Provider returned wrong window count')
        return vectors

    def run(self, batch_size: int = 16):
        if batch_size <= 0:
            raise ValueError('Batch size must be positive')
        profile = self.profile
        self.repository.ensure_profile(profile)
        saved, raced = 0, 0
        while True:
            chunks = self.repository.pending(profile['id'], batch_size)
            if not chunks:
                break
            vectors = self.encode_chunks(chunks)
            if len(vectors) != len(chunks):
                raise ValueError('Provider returned wrong batch length')
            for chunk, vector in zip(chunks, vectors):
                if self.repository.save_embedding(
                    chunk, profile['id'], normalize(vector).tolist()
                ):
                    saved += 1
                else:
                    raced += 1
            if raced:
                # A concurrent re-import changed a chunk; the next run will pick it up.
                break
        return dict(
            profile=profile,
            saved=saved,
            concurrently_changed=raced,
        )
