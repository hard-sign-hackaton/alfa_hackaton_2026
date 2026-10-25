from copy import deepcopy
from threading import RLock
import unittest
from unittest.mock import Mock

from app.web.server import Application


def card(identity, importance=None, published='2026-10-25T12:00:00+00:00', ready=False):
    return dict(id=identity, classification={'importance': importance}, published_at=published,
                has_analysis=ready)


class FeedOrderTests(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.app.refresh_database = Mock()
        self.app.reload_links = Mock()
        self.app.companies = {'a': {}, 'b': {}}
        self.app.matches = {}
        self.app.events = {}
        self.app.lock = RLock()
        self.app.card = lambda company_id, event, candidate: deepcopy(event)
        self.app.link_rows = {}
        self.app.links_initialized = False
        self.app.links_sync = {}
        self.app.expert_demo = Mock()

    def feed(self, ordinary, demo=()):
        self.app.events = {row['id']: row for row in ordinary}
        self.app.expert_demo.view.return_value = {'items': deepcopy(list(demo))}
        return self.app.feed('a', 'session')['items']

    def test_merged_importance_overrides_source_ready_and_matching(self):
        self.app.matches = {'a': [{'id': 'ordinary-medium', 'retrieval_score': 1}]}
        rows = self.feed([card('ordinary-medium', 'medium', ready=True), card('ordinary-high', 'high')],
                         [card('demo-low', 'low', ready=True), card('demo-pending')])
        self.assertEqual([row['id'] for row in rows],
                         ['ordinary-high', 'ordinary-medium', 'demo-low', 'demo-pending'])

    def test_date_is_second_key_compared_as_instants(self):
        rows = self.feed([card('newer', 'high', '2026-10-25T09:30:00+00:00')],
                         [card('older', 'high', '2026-10-25T12:00:00+05:00', ready=True)])
        self.assertEqual([row['id'] for row in rows], ['newer', 'older'])

    def test_equal_keys_keep_original_merged_order(self):
        rows = self.feed([card('ordinary-1', 'high'), card('ordinary-2', 'high')],
                         [card('demo-1', 'high'), card('demo-2', 'high')])
        self.assertEqual([row['id'] for row in rows], ['demo-1', 'demo-2', 'ordinary-1', 'ordinary-2'])

    def test_assessed_card_moves_before_full_analysis(self):
        ordinary = [card('ordinary-medium', 'medium', ready=True)]
        pending = card('demo', published='2026-10-26T12:00:00+00:00')
        self.assertEqual(self.feed(ordinary, [pending])[0]['id'], 'ordinary-medium')
        pending['classification']['importance'] = 'high'
        updated = self.feed(ordinary, [pending])
        self.assertEqual(updated[0]['id'], 'demo')
        self.assertFalse(updated[0]['has_analysis'])

    def test_company_specific_ranks_and_failed_assessment_remain_unknown(self):
        self.app.events = {'ordinary': card('ordinary', 'medium')}
        unknown = card('failed')
        self.app.expert_demo.view.side_effect = lambda sid, company: {'items': [
            card('demo', 'high' if company == 'a' else 'low'), unknown]}
        first = self.app.feed('a', 'session')['items']
        second = self.app.feed('b', 'session')['items']
        self.assertEqual([row['id'] for row in first], ['demo', 'ordinary', 'failed'])
        self.assertEqual([row['id'] for row in second], ['ordinary', 'demo', 'failed'])
        self.assertIsNone(first[-1]['classification']['importance'])

    def test_feed_without_scenario_uses_same_order(self):
        self.app.events = {row['id']: row for row in [card('low', 'low', ready=True), card('high', 'high')]}
        self.assertEqual([row['id'] for row in self.app.feed('a')['items']], ['high', 'low'])
