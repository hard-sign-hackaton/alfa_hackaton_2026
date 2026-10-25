from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.modules.links.service import LinkService


class AssessmentNotificationTests(unittest.TestCase):
    def setUp(self):
        self.service = LinkService.__new__(LinkService)
        self.service.news, self.service.companies, self.service.repository = Mock(), Mock(), Mock()
        self.service.as_of = datetime.now(timezone.utc)
        self.event = Mock(id='news')
        self.event.model_copy.return_value = self.event
        self.service.news.get_news.return_value = self.event
        self.service.classification = Mock(return_value=SimpleNamespace(topics=['economics']))
        self.service.companies.match_news.return_value = {'candidates': [
            {'id': 'a', 'similarity': .9, 'matched_topics': []},
            {'id': 'b', 'similarity': .8, 'matched_topics': []}]}
        self.service.companies.get_company_profile.side_effect = lambda identity, **kwargs: SimpleNamespace(id=identity)

    def test_notifies_after_each_assessment_before_next_company(self):
        actions = []
        self.service.assess = lambda pair, company, event: actions.append('assess-' + company.id)
        self.service.match_news('news', on_assessed=lambda: actions.append('notify'))
        self.assertEqual(actions, ['assess-a', 'notify', 'assess-b', 'notify'])

    def test_existing_call_without_callback_is_compatible(self):
        self.service.assess = Mock()
        self.service.match_news('news')
        self.assertEqual(self.service.assess.call_count, 2)

    def test_failed_model_assessment_is_reported_without_fabricated_level(self):
        self.service.client, self.service.progress = Mock(), Mock()
        self.service.client.api_key = 'test-only'
        self.service.repository.ensure.side_effect = lambda company, *args, **kwargs: {
            'company_id': company, 'importance_status': 'pending', 'importance_attempts': 0}
        notifications = Mock()
        with patch('importance.assess', side_effect=RuntimeError('model unavailable')):
            self.service.match_news('news', on_assessed=notifications)
        self.assertEqual(notifications.call_count, 2)
        self.assertEqual(self.service.repository.assessment_failed.call_count, 2)
        self.service.repository.assessment.assert_not_called()
