"""Company-specific profile windows and orchestration; the model stays shared."""
from dataclasses import asdict
import hashlib
import json

from app.shared.embeddings.provider import EmbeddingProvider, normalize

# Bump when the profile text composition or windowing changes.
PREPARATION = 'e5-company-profile-v1'


class CompanyEmbeddingService:
    def __init__(self, repository, provider: EmbeddingProvider):
        self.repository, self.provider = repository, provider

    @property
    def profile(self):
        profile = dict(**asdict(self.provider.info), preparation=PREPARATION)
        profile['id'] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        return profile

    def encode_query(self, text):
        return self.provider.encode_query(text)

    def window(self, company):
        """Return one E5 passage window and whether the profile had to be truncated."""
        title = self.provider.tokenize(f'Компания {company.company_id}')
        body = self.provider.tokenize(company.profile_text)
        if not body:
            raise ValueError(f'Company {company.company_id} has an empty profile')
        overhead = self.provider.document_window(title, [])
        budget = self.provider.max_input_tokens - len(overhead)
        if budget <= 0:
            raise ValueError('No token budget left for the company profile')
        truncated = len(body) > budget
        ids = self.provider.document_window(title, body[:budget])
        if len(ids) > self.provider.max_input_tokens:
            raise ValueError('Company profile exceeds model context')
        return ids, len(ids), truncated

    def encode_companies(self, companies):
        windows, metadata = [], []
        for company in companies:
            ids, token_count, truncated = self.window(company)
            windows.append(ids)
            metadata.append((token_count, truncated))
        vectors = self.provider.encode_windows(windows)
        if len(vectors) != len(windows):
            raise ValueError('Provider returned wrong window count')
        return [(normalize(vector), token_count, truncated)
                for vector, (token_count, truncated) in zip(vectors, metadata)]

    def run(self, batch_size=16):
        if batch_size <= 0:
            raise ValueError('Batch size must be positive')
        profile = self.profile
        self.repository.ensure_profile(profile)
        saved = raced = truncated = 0
        while True:
            companies = self.repository.pending(profile['id'], batch_size)
            if not companies:
                break
            outputs = self.encode_companies(companies)
            if len(outputs) != len(companies):
                raise ValueError('Provider returned wrong batch length')
            for company, (vector, token_count, was_truncated) in zip(companies, outputs):
                if self.repository.save_embedding(company, profile['id'], vector, token_count, was_truncated):
                    saved += 1
                    truncated += int(was_truncated)
                else:
                    raced += 1
            if raced:
                # Avoid an unbounded loop while another import changes the same row.
                break
        return dict(profile=profile, saved=saved, concurrently_changed=raced, truncated=truncated)
