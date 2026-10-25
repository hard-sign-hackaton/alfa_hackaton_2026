"""Durable votes, scope and writer permissions on an isolated test database."""
import os
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'links'))
import test_repository as link_fixtures
from app.modules.feedback.models import AnalysisFeedback
from app.modules.feedback.repository import FeedbackRepository, analysis_version

URL = os.environ.get('FEEDBACK_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'Set FEEDBACK_TEST_DATABASE_URL to a dedicated *_test database')
class FeedbackPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not make_url(URL).database.endswith('_test'):
            raise ValueError('Dedicated test database required')
        link_fixtures.URL = URL
        link_fixtures.PersistenceTests.setUpClass.__func__(cls)
        cls.feedback = FeedbackRepository(URL)

    def setUp(self):
        link_fixtures.PersistenceTests.setUp(self)
        self.state = {'company_id': self.company_id, 'news_id': self.article.id,
            'as_of': datetime.now(timezone.utc).isoformat(), 'result': {'summary': 'Test analysis'}}
        self.reviewer = 'a' * 32

    def tearDown(self):
        link_fixtures.PersistenceTests.tearDown(self)

    def count(self):
        with self.sessions() as session:
            return session.scalar(select(func.count()).select_from(AnalysisFeedback).where(AnalysisFeedback.company_id == self.company_id))

    def test_upsert_change_remove_and_new_repository_restore_vote(self):
        for vote in (1, 1, -1):
            self.feedback.save(self.state, self.reviewer, vote)
            self.assertEqual(self.count(), 1)
        fresh = FeedbackRepository(URL)
        self.assertEqual(fresh.read(self.company_id, self.article.id, analysis_version(self.state), self.reviewer)['vote'], -1)
        self.feedback.save(self.state, self.reviewer, None)
        self.assertEqual(self.count(), 0)

    def test_different_versions_reviewers_and_demo_votes_are_separate(self):
        self.feedback.save(self.state, self.reviewer, 1)
        self.feedback.save(self.state, 'b' * 32, -1)
        newer = {**self.state, 'as_of': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}
        self.feedback.save(newer, self.reviewer, -1)
        demo = {**self.state, 'news_id': 'demo:' + self.token + ':0', 'is_demo': True}
        self.feedback.save(demo, self.reviewer, 1, demo_id=self.token)
        self.assertEqual(self.count(), 4)
        with self.sessions() as session:
            test_count = session.scalar(select(func.count()).select_from(AnalysisFeedback).where(AnalysisFeedback.company_id == self.company_id, AnalysisFeedback.is_demo.is_(True)))
        self.assertEqual(test_count, 1)

    def test_invalid_vote_and_mixed_demo_scope_are_rejected(self):
        for value in (True, 2, '1'):
            with self.assertRaises(ValueError):
                self.feedback.save(self.state, self.reviewer, value)
        with self.assertRaises(ValueError):
            self.feedback.save(self.state, self.reviewer, 1, demo_id=self.token)
        self.assertEqual(self.count(), 0)

    def test_application_role_can_write_feedback_but_cannot_update_source_company(self):
        with self.sessions.begin() as session:
            exists = session.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='analysis_links_writer')"))
            if not exists:
                self.skipTest('Application writer role is not configured')
            session.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON analysis_feedback TO analysis_links_writer'))
        with self.sessions.begin() as session:
            session.execute(text('SET LOCAL ROLE analysis_links_writer'))
            session.execute(text('''INSERT INTO analysis_feedback
                (company_id,news_id,analysis_version,reviewer_id,vote,is_demo,analysis_as_of)
                VALUES (:company,:news,:version,:reviewer,1,false,now())'''),
                dict(company=self.company_id, news=self.article.id, version=analysis_version(self.state), reviewer=self.reviewer))
        self.assertEqual(self.count(), 1)
        with self.assertRaises(ProgrammingError):
            with self.sessions.begin() as session:
                session.execute(text('SET LOCAL ROLE analysis_links_writer'))
                session.execute(text("UPDATE companies SET region='forbidden' WHERE id=:id"), {'id': self.company_id})
