"""Only the application writer may update link rows; source tables stay read-only."""
from datetime import datetime, timezone
from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.dialects.postgresql import insert
from app.shared.db.session import get_session_factory
from app.modules.news.models import Article
from app.modules.companies.models import Company
from .models import NewsCompanyLink as Link


def current(query):
    return query.join(Article, Article.id == Link.news_id).join(Company, Company.id == Link.company_id).where(
        Link.news_hash == Article.content_hash, Link.company_hash == Company.content_hash,
        Article.published_at <= datetime.now(timezone.utc), Company.imported_at <= datetime.now(timezone.utc))


def output(row):
    return {c.name: (value.isoformat() if isinstance(value, datetime) else value)
            for c in Link.__table__.columns for value in [getattr(row, c.name)]}


class LinkRepository:
    def __init__(self, url):
        self.session = get_session_factory(url)

    def company_ids(self):
        with self.session() as s:
            return list(s.scalars(select(Company.id).where(Company.imported_at <= datetime.now(timezone.utc)).order_by(Company.id)))

    def ensure(self, company_id, news_id, *, method='selected', score=None, reasons=(), topics=()):
        with self.session.begin() as s:
            news = s.get(Article, news_id)
            company = s.get(Company, company_id)
            cutoff = datetime.now(timezone.utc)
            if news is None or company is None or news.published_at > cutoff or company.imported_at > cutoff:
                raise ValueError('Unknown or future company/news record')
            values = dict(company_id=company_id, news_id=news_id, news_hash=news.content_hash,
                company_hash=company.content_hash, active=True, match_method=method, match_score=score,
                match_reasons=list(reasons), topics=list(topics), importance_status='pending',
                importance_evidence=[], importance_attempts=0, analysis_status='pending')
            statement = insert(Link).values(**values).on_conflict_do_nothing()
            s.execute(statement)
            row = s.scalar(select(Link).where(Link.company_id == company_id, Link.news_id == news_id).with_for_update())
            if (row.news_hash, row.company_hash) != (news.content_hash, company.content_hash):
                for key, value in values.items():
                    setattr(row, key, value)
                row.importance = row.importance_reason = row.importance_method = None
                row.analysis_result = row.analysis_as_of = row.analysis_run_id = row.error_code = None
            row.active = True
            if reasons:
                row.match_reasons = list(reasons)
            if topics:
                row.topics = list(topics)
            if score is not None:
                row.match_score = score
            if method != 'selected':
                row.match_method = method
            row.updated_at = cutoff
            s.flush()
            return output(row)

    def list(self, *, company_id=None, news_id=None, active_only=False):
        query = current(select(Link))
        if company_id is not None:
            query = query.where(Link.company_id == company_id)
        if news_id is not None:
            query = query.where(Link.news_id == news_id)
        if active_only:
            query = query.where(Link.active)
        with self.session() as s:
            return [output(r) for r in s.scalars(query.order_by(Link.company_id, Link.news_id))]

    def _write(self, pair, values, *, run_id=None, newer_than=None, only_unrated=False, only_running=False):
        query = update(Link).where(Link.company_id == pair['company_id'], Link.news_id == pair['news_id'],
            Link.news_hash == pair['news_hash'], Link.company_hash == pair['company_hash'],
            Link.news_hash == select(Article.content_hash).where(Article.id == Link.news_id).scalar_subquery(),
            Link.company_hash == select(Company.content_hash).where(Company.id == Link.company_id).scalar_subquery())
        if run_id:
            query = query.where(Link.analysis_run_id == run_id)
        if newer_than:
            query = query.where(or_(Link.analysis_as_of.is_(None), Link.analysis_as_of <= newer_than))
        if only_unrated:
            query = query.where(Link.importance_status != 'ready')
        if only_running:
            query = query.where(Link.analysis_status == 'running')
        with self.session.begin() as s:
            return bool(s.execute(query.values(**values, updated_at=datetime.now(timezone.utc))).rowcount)

    def assessment(self, pair, result):
        return self._write(pair, dict(importance=result['level'], importance_status='ready',
            importance_reason=result['reason'], importance_evidence=result['evidence'],
            importance_method='triage', error_code=None), only_unrated=True)

    def assessment_failed(self, pair):
        return self._write(pair, dict(importance_status='failed', importance_attempts=pair['importance_attempts'] + 1,
            error_code='importance_unavailable'), only_unrated=True)

    def claim_analysis(self, pair, run_id):
        return self._write(pair, dict(analysis_status='running', analysis_run_id=run_id, error_code=None))

    def analysis_failed(self, pair, run_id):
        return self._write(pair, dict(analysis_status='failed', error_code='analysis_unavailable'), run_id=run_id, only_running=True)

    def analysis(self, pair, state, *, run_id=None):
        from app.modules.news.identity import input_hash
        if (state['company_id'], state['news_id']) != (pair['company_id'], pair['news_id']):
            raise ValueError('Mixed analysis identity')
        if input_hash(state['event']['title'], state['event']['text']) != pair['news_hash']:
            raise ValueError('Analysis publication content has changed')
        as_of = datetime.fromisoformat(state['as_of'])
        if as_of.tzinfo is None:
            raise ValueError('Analysis time requires timezone')
        values = dict(analysis_result=state, analysis_as_of=as_of,
            analysis_status='ready' if state['result']['status'] == 'supported' else 'partial', error_code=None)
        classification = state.get('brief', {}).get('classification', {})
        if classification.get('importance'):
            values.update(importance=classification['importance'], importance_status='ready',
                importance_reason=classification['importance_reason'], importance_method='analysis',
                importance_evidence=state['brief']['evidence']['importance'])
        return self._write(pair, values, run_id=run_id, newer_than=as_of)

    def deactivate(self, company_id, selected_ids):
        with self.session.begin() as s:
            s.execute(update(Link).where(Link.company_id == company_id, Link.match_method == 'hybrid',
                Link.news_id.not_in(selected_ids)).values(active=False))
