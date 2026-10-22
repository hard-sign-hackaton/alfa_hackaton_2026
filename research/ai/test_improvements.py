"""Regression cases for failures observed in company/news matching."""
import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from agent import offline_insight
from contracts import Evidence
from fixtures import profiles, news
from grounding import (fragment_catalog, resolve_selection, ClassificationSelection,
                       CitationChoice, finalize_insight)
from langchain_provider import LangChainClient, ModelError
from matching import merge_hits, company_search_plan, military_logistics, match_company
from model_config import GatewaySettings
from ranking import rank_pair, industry_topics
from research_tools import ToolSession
from run import AS_OF


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.company, self.event = profiles()[0], news()[0]

    def test_fragment_ids_resolve_to_original_text(self):
        catalog = fragment_catalog(self.event)
        selected = ClassificationSelection(news_id=self.event.id, business_relevant=True,
            topics=['metallurgy'], evidence=[CitationChoice(source_id='news:' + self.event.id, fragment_id='f0000')])
        value = resolve_selection(selected, self.event, catalog)
        self.assertEqual(value.evidence[0].quote, self.event.title)

    def test_source_identity_can_be_bound_by_server_without_generation(self):
        selected = ClassificationSelection(business_relevant=True, topics=['metallurgy'],
            evidence=[CitationChoice(fragment_id='f0000')])
        value = resolve_selection(selected, self.event, fragment_catalog(self.event))
        self.assertEqual(value.news_id, self.event.id)
        self.assertEqual(value.evidence[0].source_id, 'news:' + self.event.id)

    def test_fragment_id_cannot_switch_source_or_invent_text(self):
        catalog = fragment_catalog(self.event)
        for source, fragment in [('news:foreign', 'f0000'), ('news:' + self.event.id, 'fabricated')]:
            value = ClassificationSelection(news_id=self.event.id, business_relevant=True, topics=['metallurgy'],
                evidence=[CitationChoice(source_id=source, fragment_id=fragment)])
            with self.assertRaises(ValueError): resolve_selection(value, self.event, catalog)

    def test_quote_ellipsis_is_still_rejected(self):
        value = ClassificationSelection(news_id=self.event.id, business_relevant=True, topics=['metallurgy'],
            evidence=[CitationChoice(source_id='news:' + self.event.id, quote=self.event.title[:4] + '...')])
        with self.assertRaises(ValueError): resolve_selection(value, self.event, fragment_catalog(self.event))

    def test_whitespace_and_long_fragments_are_verbatim(self):
        event = self.event.model_copy(update={'text': 'Первая строка.\n\n' + 'ю' * 1500 + ' Конец.'})
        self.assertTrue(all(text in event.title + '\n' + event.text for text in fragment_catalog(event).values()))

    def test_summary_cannot_invent_deposit_income(self):
        value = offline_insight(self.company, self.event)
        value.summary = 'Компания получает годовые поступления от депозитов.'
        result = finalize_insight(value, self.company, self.event)
        self.assertNotIn('депозит', result.summary)
        self.assertTrue(any(claim.text in result.summary for claim in result.claims))

    def test_only_company_facts_do_not_establish_applicability(self):
        value = offline_insight(self.company, self.event)
        value.claims = [claim for claim in value.claims if claim.kind == 'fact']
        self.assertEqual(finalize_insight(value, self.company, self.event).status, 'insufficient_data')

    def test_added_okved_codes_and_specific_wholesale_activity(self):
        for code, topic in [('45.31.1', 'automotive'), ('46.43', 'electronics'), ('68.20.2', 'real_estate')]:
            company = self.company.model_copy(update={'okved_codes': [code]})
            self.assertIn(topic, industry_topics(company))
            self.assertEqual(rank_pair(company, self.event.model_copy(update={'topics': [topic]}), as_of=AS_OF)['score'], 70)
        self.assertNotIn('construction', industry_topics(self.company.model_copy(update={'okved_codes': ['68.20.2']})))

    def test_nonbusiness_is_not_eligible_even_with_same_region(self):
        value = self.event.model_copy(update={'topics': ['not_business'], 'regions': [self.company.registration_region]})
        self.assertFalse(rank_pair(self.company, value, as_of=AS_OF)['eligible'])

    def test_rank_fusion_beats_semantic_only_hub(self):
        lexical = [{'id': 'relevant', 'title': 'Автокредитование', 'text': 'Спрос на автомобили'}]
        semantic = [{'id': 'hub', 'title': 'ЛУКОЙЛ', 'text': 'Иностранные активы'}, lexical[0]]
        self.assertEqual(merge_hits(lexical, semantic, 2)[0]['id'], 'relevant')

    def test_duplicate_stories_do_not_fill_search_limit(self):
        first = {'id': 'one', 'title': 'ЦБ сохранил ключевую ставку', 'text': 'Изменение ставки'}
        second = {**first, 'id': 'two'}
        other = {'id': 'three', 'title': 'Автокредитование', 'text': 'Спрос на машины'}
        self.assertEqual([r['id'] for r in merge_hits([first, second, other], [], 2)], ['one', 'three'])
        self.assertEqual([r['id'] for r in merge_hits([first, other], [], 2, excluded=[second])], ['three'])

    def test_military_logistics_is_not_commercial_exposure(self):
        self.assertTrue(military_logistics('Минобороны сообщило об ударе по логистическому центру'))
        self.assertFalse(military_logistics('Логистический центр увеличил выручку'))

    def test_queries_preserve_specialization_and_avoid_registration_noise(self):
        company = self.company.model_copy(update={'okved_codes': ['46.43']})
        plan = company_search_plan(company)
        self.assertIn('Бытовая техника', plan[0]['query'])
        self.assertNotIn(company.registration_region, plan[0]['query'])

    def test_company_module_credit_code_has_financing_branch(self):
        company = self.company.model_copy(update={'banking_services': ['credit', 'cash_register']})
        self.assertIn('financing', [row['kind'] for row in company_search_plan(company)])

    def test_semantic_only_candidates_are_not_presented_as_company_matches(self):
        reader = Mock()
        reader.search_hits.return_value = [{'id': 'hub', 'title': 'ЛУКОЙЛ', 'text': 'Активы', 'retrieval_channels': ['semantic']}]
        result = match_company(reader, self.company, as_of=AS_OF)
        self.assertEqual(result['candidates'], [])

    def test_incidental_body_keyword_is_not_an_industry_match(self):
        reader = Mock()
        reader.search_hits.return_value = [{'id': 'noise', 'title': 'Постороннее событие', 'text': 'Упоминание в меню сайта',
            'retrieval_channels': ['lexical'], 'retrieval_score': .05, 'title_match': False}]
        company = self.company.model_copy(update={'banking_services': []})
        self.assertEqual(match_company(reader, company, as_of=AS_OF)['candidates'], [])

    def test_transient_errors_retry_but_authentication_does_not(self):
        class Temporary(Exception): status_code = 503
        count = []
        def invoke(prompt):
            count.append(1)
            if len(count) < 3: raise Temporary()
            return AIMessage(content=json.dumps({'news_id': self.event.id, 'business_relevant': True,
                'topics': ['metallurgy'], 'evidence': [{'source_id': 'news:' + self.event.id, 'fragment_id': 'f0000'}]}))
        client = LangChainClient(settings=GatewaySettings.from_env({}), sleeper=lambda _: None,
            model_factory=lambda route: RunnableLambda(invoke))
        client.classify(self.event)
        self.assertEqual(len(count), 3)
        self.assertEqual(client.telemetry[-1]['status'], 'validated_references')

    def test_unavailable_database_is_not_requeried_with_different_keywords(self):
        from database import DatabaseError
        repo = Mock()
        repo.search_bank_analytics.side_effect = DatabaseError('unavailable')
        session = ToolSession(repo, self.company, self.event, as_of=AS_OF)
        session.invoke('search_bank_analytics', {'query': 'сталь'})
        session.invoke('search_bank_analytics', {'query': 'металлургия'})
        self.assertEqual(repo.search_bank_analytics.call_count, 1)
        self.assertTrue(session.trace[-1]['cached'])


if __name__ == '__main__': unittest.main()
