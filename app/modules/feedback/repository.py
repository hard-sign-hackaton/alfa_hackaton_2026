import hashlib
import json
from datetime import datetime
import re
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from app.shared.db.session import get_session_factory
from .models import AnalysisFeedback as Feedback


def analysis_version(state):
    payload = {key: state.get(key) for key in ('company_id', 'news_id', 'as_of', 'company', 'event', 'result', 'brief', 'retrieved_sources')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class FeedbackRepository:
    def __init__(self, url):
        self.session = get_session_factory(url)

    @staticmethod
    def _identity(company_id, news_id, version, reviewer_id):
        if not isinstance(company_id, str) or not company_id or not isinstance(news_id, str) or not 1 <= len(news_id) <= 96:
            raise ValueError('Invalid feedback identity')
        if not isinstance(version, str) or not isinstance(reviewer_id, str) or not re.fullmatch(r'[a-f0-9]{64}', version) or not re.fullmatch(r'[a-f0-9]{32}', reviewer_id):
            raise ValueError('Invalid feedback version or reviewer')
        return dict(company_id=company_id, news_id=news_id, analysis_version=version, reviewer_id=reviewer_id)

    def read(self, company_id, news_id, version, reviewer_id):
        identity = self._identity(company_id, news_id, version, reviewer_id)
        with self.session() as session:
            row = session.get(Feedback, identity)
            return {'vote': row.vote if row else None}

    def save(self, state, reviewer_id, vote, *, demo_id=None):
        if vote is not None and (type(vote) is not int or vote not in (-1, 1)):
            raise ValueError('Vote must be -1, 1 or null')
        identity = self._identity(state['company_id'], state['news_id'], analysis_version(state), reviewer_id)
        is_demo = bool(state.get('is_demo'))
        if is_demo != bool(demo_id) or (demo_id and not re.fullmatch(r'[a-f0-9]{32}', demo_id)):
            raise ValueError('Invalid demo feedback scope')
        with self.session.begin() as session:
            if vote is None:
                session.execute(delete(Feedback).filter_by(**identity))
            else:
                values = dict(**identity, vote=vote, is_demo=is_demo, demo_id=demo_id,
                              analysis_as_of=datetime.fromisoformat(state['as_of']))
                statement = insert(Feedback).values(**values)
                session.execute(statement.on_conflict_do_update(
                    index_elements=['company_id', 'news_id', 'analysis_version', 'reviewer_id'],
                    set_={'vote': statement.excluded.vote, 'updated_at': func.now()}))
        return {'vote': vote, 'analysis_version': identity['analysis_version'], 'is_demo': is_demo}
