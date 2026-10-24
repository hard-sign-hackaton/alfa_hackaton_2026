import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from precompute_analyses import pending_jobs
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'research' / 'ai'))


class PrecomputeSelectionTests(unittest.TestCase):
    def test_refresh_bank_selects_only_legacy_business_analyses_without_bank_sources(self):
        state = {'brief': {'summary': 'Ready'}, 'preparation': {'classification': {'business_relevant': True}}}
        old = {'active': True, 'analysis_result': state}
        fresh = {'active': True, 'analysis_result': {**state, 'bank_context_version': 1}}
        with_bank = {'active': True, 'analysis_result': {**state, 'retrieved_sources': [{'kind': 'bank'}]}}
        self.assertEqual(pending_jobs([old, fresh, with_bank]), [])
        self.assertEqual(pending_jobs([old, fresh, with_bank], refresh_bank_context=True), [old])
    def test_keeps_personal_pairs_even_when_news_is_shared(self):
        rows = [{'company_id': name, 'news_id': 'same', 'active': True, 'analysis_result': None}
                for name in ('one', 'two')]
        self.assertEqual([r['company_id'] for r in pending_jobs(rows)], ['one', 'two'])

    def test_completed_insufficient_data_result_is_not_retried(self):
        rows = [{'active': True, 'analysis_result': {'result': {'status': 'insufficient_data'},
                                                  'brief': {'short_answer': 'Нужны дополнительные данные'}}}]
        self.assertEqual(pending_jobs(rows), [])

    def test_resume_includes_missing_briefs_and_excludes_inactive_links(self):
        rows = [{'active': True, 'analysis_result': {'result': {'summary': 'Есть полный разбор'}}},
                {'active': False, 'analysis_result': None},
                {'active': True, 'analysis_result': None}]
        self.assertEqual(pending_jobs(rows), [rows[0], rows[2]])


if __name__ == '__main__':
    unittest.main()
