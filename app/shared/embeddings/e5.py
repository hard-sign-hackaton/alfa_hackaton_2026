"""Local E5 model adapter. No SQLAlchemy, news DTOs or repository imports."""
import os
import numpy as np
from .provider import EmbeddingModelInfo, normalize

MODEL = 'intfloat/multilingual-e5-small'

class E5Provider:
    max_input_tokens = 512

    def __init__(self, revision=None, device=None):
        from huggingface_hub import HfApi
        from sentence_transformers import SentenceTransformer
        revision = revision or os.getenv('NEWS_MODEL_REVISION')
        # Resolve a moving branch once; persist the immutable Hub commit in the profile.
        if not revision or len(revision) != 40:
            revision = HfApi().model_info(MODEL, revision=revision or 'main').sha
        self.model = SentenceTransformer(MODEL, revision=revision, device=device or os.getenv('NEWS_EMBEDDING_DEVICE', 'cpu'))
        self.model.eval()
        self.tokenizer = self.model.tokenizer
        if self.model.get_sentence_embedding_dimension() != 384:
            raise ValueError('Model dimension mismatch')
        self.info = EmbeddingModelInfo(MODEL, revision, 384, True)


    def tokenize(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False)

    def document_window(self, title_tokens, body_tokens):
        if self.tokenizer.cls_token_id is None or self.tokenizer.sep_token_id is None:
            raise ValueError('Expected an XLM-R tokenizer with CLS/SEP tokens')
        return ([self.tokenizer.cls_token_id] + self.tokenize('passage: ') + title_tokens
                + self.tokenize('\n\n') + body_tokens + [self.tokenizer.sep_token_id])

    def encode_windows(self, windows, batch_size=32):
        import torch
        outputs = []
        with torch.inference_mode():
            for start in range(0, len(windows), batch_size):
                features = self.tokenizer.pad({'input_ids': windows[start:start + batch_size]},
                    padding=True, return_attention_mask=True, return_tensors='pt')
                features = {k: v.to(self.model.device) for k, v in features.items()}
                outputs.extend(normalize(self.model(features)['sentence_embedding'].cpu().numpy()))
        return np.asarray(outputs, dtype=np.float32)

    def encode_query(self, query):
        if not query.strip():
            raise ValueError('Empty query')
        return normalize(self.model.encode(['query: ' + query.strip()], convert_to_numpy=True, normalize_embeddings=True)[0])
