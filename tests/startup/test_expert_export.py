import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from export_startup_data import without_expert_records


class ExpertExportTests(unittest.TestCase):
    def test_excludes_synthetic_sources_articles_vectors_and_links(self):
        sid = 'a' * 32
        rows = [
            "INSERT INTO public.news_sources (id, name) VALUES ('expert-demo:" + sid + "', 'Scenario') ON CONFLICT DO NOTHING;",
            "INSERT INTO public.news_articles (id, title, text) VALUES ('demo:" + sid + ":0', 'ТЕСТ', 'Multi;line\ntext with ''quotes''') ON CONFLICT DO NOTHING;",
            "INSERT INTO public.news_embeddings (id, article_id, vector) VALUES (1, 'demo:" + sid + ":0', '[1,2]') ON CONFLICT DO NOTHING;",
            "INSERT INTO public.news_company_links (company_id, news_id) VALUES ('company', 'demo:" + sid + ":0') ON CONFLICT DO NOTHING;",
        ]
        normal = "INSERT INTO public.news_articles (id, text) VALUES ('actual', 'Обычный текст; с ''кавычками''\nи переносом') ON CONFLICT DO NOTHING;"
        result = without_expert_records('\n'.join(rows + [normal]))
        self.assertNotIn('demo:', result)
        self.assertIn(normal, result)

    def test_unknown_dump_format_fails_closed_instead_of_publishing_test_records(self):
        with self.assertRaises(ValueError):
            without_expert_records("INSERT INTO other VALUES ('demo:" + 'a' * 32 + ":0');")
