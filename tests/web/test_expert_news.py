import unittest

from app.web.expert_news import company_publications, scenario_publications


class ExpertNewsTests(unittest.TestCase):
    def test_publications_have_company_facts_but_no_assessment_or_analysis_fields(self):
        company = {'id': 'U_1234', 'okved': '46.43', 'industry': 'Торговля бытовой техникой', 'region': 'Москва'}
        publications = company_publications(company)
        self.assertEqual(len(publications), 2)
        for article in publications:
            self.assertIn(company['id'], article['title'])
            self.assertIn(company['okved'], article['text'])
            self.assertIn(company['industry'], article['text'])
            self.assertIn('вымышленная', article['text'])
            self.assertFalse(set(article) & {'importance', 'classification', 'analysis', 'brief', 'expected'})
        self.assertIn('вступившее в силу', publications[0]['text'])
        self.assertIn('300 до 324', publications[1]['text'])

    def test_every_company_has_two_inputs_and_one_shared_control(self):
        companies = [{'id': 'U_' + str(index), 'okved': '45.31', 'industry': 'Торговля автодеталями'} for index in range(12)]
        publications = scenario_publications(companies)
        self.assertEqual(len(publications), 25)
        for company in companies:
            self.assertEqual(sum(article.get('target_company_id') == company['id'] for article in publications), 2)
        self.assertEqual(sum(article['case'] == 'control' for article in publications), 1)
