from dataclasses import dataclass
from typing import Protocol
import numpy as np

@dataclass(frozen=True)
class EmbeddingModelInfo:
    model: str
    revision: str
    dimensions: int
    normalized: bool

class EmbeddingProvider(Protocol):
    """Model/tokenization interface independent of publications and persistence."""
    info: EmbeddingModelInfo
    max_input_tokens: int

    def tokenize(self, text: str) -> list[int]: ...
    def document_window(self, title_tokens: list[int], body_tokens: list[int]) -> list[int]: ...
    def encode_windows(self, windows: list[list[int]], batch_size: int = 32) -> np.ndarray: ...
    def encode_query(self, text: str) -> np.ndarray: ...

def normalize(vectors):
    x = np.asarray(vectors, dtype=np.float32)
    if x.ndim not in (1, 2) or x.shape[-1] != 384 or not np.isfinite(x).all():
        raise ValueError('Expected finite float32 vectors with dimension 384')
    lengths = np.linalg.norm(x, axis=-1, keepdims=True)
    if np.any(lengths <= 0):
        raise ValueError('Zero embedding')
    return np.ascontiguousarray(x / lengths, dtype=np.float32)
