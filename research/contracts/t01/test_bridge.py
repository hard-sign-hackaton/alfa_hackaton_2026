import copy
import json
import unittest
from pathlib import Path

from adapter import adapt, CompanyProfile, NewsEvent, Insight
from verify import validate_request, validate_bundle, validate_analysis_request, validator

ROOT = Path(__file__).resolve().parent

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((ROOT / 'examples/assembly-request.json').read_text(encoding='utf-8'))

    def test_saved_ai_contract_exports_match_code(self):
        for name, model in [('ai-company-profile', CompanyProfile), ('ai-news-event', NewsEvent), ('ai-insight', Insight)]:
            exported = json.loads((ROOT / (name + '.schema.json')).read_text(encoding='utf-8'))
            exported.pop('$schema')
            self.assertEqual(exported, model.model_json_schema())

    def test_round_trip_keeps_ai_payload_and_does_not_mutate_request(self):
        before = copy.deepcopy(self.request)
        validate_request(self.request)
        bundle = adapt(self.request)
        validate_bundle(bundle)
        self.assertEqual(bundle['ai_insight'], self.request['ai_insight'])
        self.assertEqual(self.request, before)
        self.assertEqual(bundle['insight']['content_status'], 'partial')

    def test_retrieved_bank_evidence_survives_projection(self):
        source = {'source_id': 'bank:test', 'kind': 'bank', 'title': 'Bank outlook',
                  'text': 'Demand may fall.', 'published_at': '2026-10-01T00:00:00Z',
                  'locator': 'fixture:bank', 'url': None, 'company_id': None, 'is_demo': True}
        self.request['retrieved_sources'] = [source]
        self.request['ai_insight']['claims'].append({'kind': 'fact', 'text': source['text'],
            'evidence': [{'source_id': source['source_id'], 'quote': source['text']}]})
        validate_request(self.request)
        bundle = adapt(self.request)
        validate_bundle(bundle)
        self.assertEqual(bundle['insight']['bank']['status'], 'found')
        self.assertIn('bank:test', {item['id'] for item in bundle['insight']['sources']})

    def test_foreign_retrieved_metric_and_future_article_are_rejected(self):
        source = {'source_id': 'metric:other:test', 'kind': 'metric', 'title': 'Observed inflow',
                  'text': '100 RUB', 'published_at': '2026-10-01T00:00:00Z',
                  'locator': 'fixture:metric', 'url': None, 'company_id': 'other', 'is_demo': True}
        self.request['retrieved_sources'] = [source]
        with self.assertRaises(ValueError):
            validate_request(self.request)
        source.update(source_id='bank:future', kind='bank', company_id=None, published_at='2099-01-01T00:00:00Z')
        with self.assertRaises(ValueError):
            adapt(self.request)

    def test_empty_retrieved_context_does_not_claim_search_is_unimplemented(self):
        self.request['retrieved_sources'] = []
        bundle = adapt(self.request)
        validate_bundle(bundle)
        self.assertEqual(bundle['insight']['bank']['status'], 'unavailable')
        self.assertIn('статус поиска', bundle['insight']['bank']['note'])

    def test_relevance_is_not_impact(self):
        for importance in ('low', 'medium', 'high'):
            self.request['impact']['importance'] = importance
            self.assertEqual(adapt(self.request)['feed_card']['importance'], importance)

    def test_missing_date_and_revenue_period_stay_unknown(self):
        bundle = adapt(self.request)
        self.assertIsNone(bundle['company']['profile_as_of'])
        revenue = next(f for f in bundle['company']['features'] if f['id'] == 'annual_revenue_rub')
        self.assertIsNone(revenue['period'])
        self.assertEqual(bundle['insight']['bank']['status'], 'unavailable')

    def test_wrong_company_and_fake_quote_are_rejected(self):
        for update in ('company', 'quote'):
            request = copy.deepcopy(self.request)
            if update == 'company':
                request['ai_insight']['company_id'] = 'another-company'
            else:
                request['ai_insight']['claims'][0]['evidence'][0]['quote'] = 'a fabricated quotation'
            with self.assertRaises(ValueError):
                validate_request(request)

    def test_wrong_classifier_context_is_rejected(self):
        self.request['impact']['news_id'] = 'another-news'
        with self.assertRaises(ValueError):
            adapt(self.request)

    def test_stale_classifier_profile_version_is_rejected(self):
        self.request['impact']['profile_version'] = 'stale-profile'
        with self.assertRaises(ValueError):
            adapt(self.request)

    def test_bank_and_enrichment_are_separate_inputs(self):
        rich = json.loads((ROOT / 'examples/assembly-with-enrichment.json').read_text(encoding='utf-8'))
        validate_request(rich)
        bundle = adapt(rich)
        validate_bundle(bundle)
        self.assertEqual(bundle['insight']['bank']['status'], 'found')
        self.assertTrue(bundle['insight']['is_demo'])
        self.assertEqual(bundle['insight']['checks'], rich['enrichment']['checks'])
        self.assertEqual(bundle['ai_insight'], self.request['ai_insight'])

    def test_cross_company_enrichment_is_rejected(self):
        rich = json.loads((ROOT / 'examples/assembly-with-enrichment.json').read_text(encoding='utf-8'))
        rich['enrichment']['company_id'] = 'another-company'
        with self.assertRaises(ValueError):
            adapt(rich)

    def test_invalid_classifier_evidence_is_rejected(self):
        self.request['impact']['evidence'][0]['source_id'] = 'missing-source'
        with self.assertRaises(ValueError):
            adapt(self.request)

    def test_dangling_fragment_in_enrichment_is_rejected(self):
        rich = json.loads((ROOT / 'examples/assembly-with-enrichment.json').read_text(encoding='utf-8'))
        rich['enrichment']['risks'] = [{'id': 'bad-risk', 'text': 'Unsupported risk', 'kind': 'ai_inference', 'evidence': [{'source_id': 'missing', 'fragment_id': 'missing'}], 'feature_ids': [], 'assumptions': [], 'limitations': []}]
        with self.assertRaises(ValueError):
            validate_bundle(adapt(rich))

    def test_analysis_request_requires_selected_event(self):
        request = json.loads((ROOT / 'examples/analysis-request.json').read_text(encoding='utf-8'))
        request['news_id'] = 'absent'
        with self.assertRaises(ValueError):
            validate_analysis_request(request)

if __name__ == '__main__':
    unittest.main()
