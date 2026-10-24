"""Lazy, thread-safe access to the ordinary news embedding preparation."""
from threading import RLock
from .embedding import NewsEmbeddingService


class LazyNewsEmbeddings:
    def __init__(self, provider_factory=None):
        self._factory = provider_factory
        self._service = None
        self._failure = None
        self._lock = RLock()

    def _get(self):
        if self._failure is not None:
            raise RuntimeError(self._failure)
        if self._service is None:
            try:
                if self._factory is None:
                    from app.shared.embeddings.e5 import E5Provider
                    provider = E5Provider()
                else:
                    provider = self._factory()
                self._service = NewsEmbeddingService(None, provider)
            except Exception as exc:
                # Do not repeatedly download/reinitialize a failed model per article.
                self._failure = type(exc).__name__
                raise RuntimeError(self._failure) from None
        return self._service

    @property
    def profile(self):
        with self._lock:
            return self._get().profile

    def encode_articles(self, articles):
        with self._lock:
            return self._get().encode_articles(articles)
