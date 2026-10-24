import unittest

from bank_context import bank_query, describe_bank_context, needs_bank_refresh, summarize_bank_context
from fixtures import news
from test_database_agent import ClientFixture


class BankContextTests(unittest.TestCase):
    def test_specific_event_takes_priority_over_broad_sector(self):
        event = news()[0].model_copy(update={'title': 'Ставки на перевозку российской нефти выросли'})
        self.assertEqual(bank_query(event, ClientFixture([]).prepare(event)), 'нефть')
        event = event.model_copy(update={'title': 'ЦБ сохранит ключевую ставку'})
        self.assertEqual(bank_query(event, ClientFixture([]).prepare(event)), 'ключевая ставка')

    def test_found_sources_are_not_presented_as_cited_evidence(self):
        state = {'retrieved_sources': [{'kind': 'bank', 'source_id': 'bank:one'}], 'result': {'claims': []}}
        self.assertEqual(describe_bank_context(state)['status'], 'retrieved')
        self.assertEqual(describe_bank_context(state)['cited_count'], 0)
        state['result']['claims'] = [{'evidence': [{'source_id': 'bank:one'}, {'source_id': 'bank:missing'}]}]
        self.assertEqual(describe_bank_context(state)['cited_source_ids'], ['bank:one'])

    def test_empty_missing_and_unavailable_are_distinct(self):
        self.assertEqual(describe_bank_context({})['status'], 'not_searched')
        for value, expected in [('not_found', 'not_found'), ('unavailable', 'unavailable'), ('limited', 'incomplete')]:
            self.assertEqual(describe_bank_context({'trace': [{'tool': 'search_bank_analytics', 'status': value}]})['status'], expected)

    def test_refresh_does_not_loop_on_a_new_genuine_empty_search(self):
        state = {'preparation': {'classification': {'business_relevant': True}}}
        self.assertTrue(needs_bank_refresh(state))
        state['bank_context_version'] = 1
        self.assertFalse(needs_bank_refresh(state))

    def test_summary_reuses_bank_facts_and_keeps_company_hypothesis_separate(self):
        source = {'kind': 'bank', 'source_id': 'bank:one', 'text': 'Банк ожидает снижения инфляции.'}
        evidence = [{'source_id': 'bank:one', 'quote': source['text']}]
        state = {'company_id': 'one', 'news_id': 'event', 'retrieved_sources': [source], 'result': {'claims': [
            {'kind': 'fact', 'text': source['text'], 'evidence': evidence},
            {'kind': 'hypothesis', 'text': 'Для компании стоимость кредита может снизиться.',
             'evidence': evidence + [{'source_id': 'company:one:banking_services', 'quote': 'credit'},
                                     {'source_id': 'news:event', 'quote': 'Ставка'}]}]}}
        summary = summarize_bank_context(state)
        self.assertEqual(summary['highlights'][0]['text'], source['text'])
        self.assertEqual(summary['highlights'][0]['method'], 'accepted_claim')
        self.assertIn('может', summary['impact']['text'])
        self.assertIsNone(summary['note'])
        state['result']['claims'][1]['evidence'].pop()
        self.assertIsNotNone(summarize_bank_context(state)['impact'])
        state['company_id'] = 'other'
        self.assertIsNone(summarize_bank_context(state)['impact'])

    def test_uncited_summary_uses_original_excerpts_and_excludes_ocr_headers(self):
        body = 'Банк ожидает замедления инфляции и постепенного снижения ключевой ставки.'
        state = {'event': {'title': 'ЦБ обсуждает ключевую ставку'}, 'retrieved_sources': [
            {'kind': 'bank', 'source_id': 'bank:one#1', 'text': 'Документ: Обзор\nСтраницы: 1\n\n' + body},
            {'kind': 'bank', 'source_id': 'bank:one#2', 'text': body}], 'result': {'claims': []}}
        summary = summarize_bank_context(state)
        self.assertEqual(len(summary['highlights']), 1)
        self.assertEqual(summary['highlights'][0]['text'], body)
        self.assertEqual(summary['highlights'][0]['evidence'][0]['quote'], body)
        self.assertEqual(summary['highlights'][0]['method'], 'excerpt')
        self.assertIsNone(summary['impact'])

    def test_summary_is_bounded_and_does_not_reuse_unverified_bank_claim(self):
        sentence = ('Прогноз по инфляции требует проверки исходных допущений ' * 20).strip()
        state = {'retrieved_sources': [{'kind': 'bank', 'source_id': 'bank:one', 'text': sentence}],
                 'result': {'claims': [{'kind': 'fact', 'text': 'Придуманное утверждение',
                                       'evidence': [{'source_id': 'bank:one', 'quote': 'несуществующая цитата'}]}]}}
        item = summarize_bank_context(state)['highlights'][0]
        self.assertLessEqual(len(item['text']), 320)
        self.assertEqual(item['method'], 'excerpt')
        self.assertEqual(item['evidence'][0]['quote'], sentence)


if __name__ == '__main__':
    unittest.main()
