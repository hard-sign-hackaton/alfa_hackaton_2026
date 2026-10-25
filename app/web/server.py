"""Same-origin interface for stored insights and bounded company research."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie, CookieError
import json
import logging
import os
from pathlib import Path
import re
import sys
from threading import RLock, Event, Thread
import time
from urllib.parse import urlparse, parse_qs
from uuid import uuid4
from .profiles import list_profiles, profile_id

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'research' / 'ai'))
LOG = logging.getLogger('web')


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def now():
    return datetime.now(timezone.utc).isoformat()


class Application:
    def __init__(self, root=ROOT, runtime=None, runner=None, chat_runner=None, enable_links=True, feedback_repository=None):
        self.root = Path(root)
        self.runtime = Path(runtime or os.environ.get('WEB_RUNTIME_DIR', ROOT / 'local_runtime' / 'web'))
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='research')
        self.expert_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='expert-research')
        self.jobs, self.conversations, self.analyses = {}, {}, {}
        self.runner, self.chat_runner = runner or self.run_analysis, chat_runner or self.run_chat
        self.events, self.companies, self.classifications, self.matches = {}, {}, {}, {}
        self.database_status = 'snapshot'
        self.database_checked = 0.0
        self.links = None
        self.feedback_repository = feedback_repository
        if self.feedback_repository is None and enable_links and os.environ.get('LINKS_DATABASE_URL'):
            from app.modules.feedback.repository import FeedbackRepository
            self.feedback_repository = FeedbackRepository(os.environ['LINKS_DATABASE_URL'])
        self.link_rows = {}
        self.links_initialized = False
        self.links_sync = {'status': 'disabled', 'stage': '', 'updated_at': None}
        self.links_stop = Event()
        from .expert_demo import ExpertDemo
        from .expert_pipeline import ExpertPipeline
        self.expert_pipeline = ExpertPipeline(self.links, self.runner)
        self.expert_demo = ExpertDemo(processor=self.process_expert, executor=self.expert_executor, runtime=self.runtime)
        if enable_links and os.environ.get('LINKS_DATABASE_URL'):
            from app.modules.links.repository import LinkRepository
            self.links = LinkRepository(os.environ['LINKS_DATABASE_URL'])
            self.links_sync['status'] = 'pending'
        self.load_snapshots()

    def initialize_links(self):
        if self.links_initialized or not self.links:
            return
        existing = {(r['company_id'], r['news_id']): r for r in self.links.list()}
        for company_id, values in self.matches.items():
            for hit in values:
                if company_id in self.companies and hit['id'] in self.events and (company_id, hit['id']) not in existing:
                    self.links.ensure(company_id, hit['id'], method='hybrid', score=hit.get('retrieval_score'),
                        reasons=hit.get('match_reasons', []), topics=self.classifications.get(hit['id'], {}).get('topics', []))
        for (company_id, news_id), state in list(self.analyses.items()):
            if company_id not in self.companies or news_id not in self.events:
                continue
            try:
                pair = existing.get((company_id, news_id)) or self.links.ensure(company_id, news_id, method='saved_analysis',
                    reasons=[{'kind': 'saved_analysis'}], topics=state.get('preparation', {}).get('classification', {}).get('topics', []))
                # An equally dated DB record may contain a subsequently completed brief.
                # Import only strictly newer file snapshots, never downgrade persisted results.
                if pair.get('analysis_result') and pair.get('analysis_as_of') and datetime.fromisoformat(pair['analysis_as_of']) >= datetime.fromisoformat(state['as_of']):
                    continue
                self.links.analysis(pair, state)
            except ValueError:
                LOG.warning('Skipped incompatible stored analysis')
        self.links_initialized = True
        self.reload_links()

    def reload_links(self):
        if not self.links or not self.links_initialized:
            return
        rows = self.links.list()
        with self.lock:
            self.link_rows = {(r['company_id'], r['news_id']): r for r in rows}
            self.analyses = {(r['company_id'], r['news_id']): r['analysis_result'] for r in rows if r['analysis_result']}
            self.matches = {company_id: [dict(id=r['news_id'], retrieval_score=r['match_score'] or 0,
                match_reasons=r['match_reasons']) for r in rows if r['company_id'] == company_id and r['active']]
                for company_id in self.companies}

    def start_links_worker(self):
        if not self.links:
            return
        def work():
            while not self.links_stop.is_set():
                service = None
                try:
                    self.refresh_database()
                    if self.database_status != 'connected':
                        raise RuntimeError('Source database unavailable')
                    self.links_sync.update(status='running', stage='Подготовка связей')
                    self.initialize_links()
                    self.expert_demo.resume()
                    from app.modules.links.service import LinkService
                    service = LinkService(self.links, self.classifications,
                        lambda stage: self.links_sync.update(stage=stage))
                    service.sync()
                    self.classifications.update(service.classifications)
                    self.reload_links()
                    self.links_sync.update(status='done', stage='Связи обновлены', updated_at=now())
                except Exception as exc:
                    self.links_sync.update(status='failed', stage='Не удалось обновить связи', updated_at=now())
                    LOG.warning('Link synchronization failed (%s)', type(exc).__name__)
                finally:
                    if service:
                        service.close()
                self.links_stop.wait(max(30, int(os.environ.get('LINKS_SYNC_SECONDS', '300'))))
        Thread(target=work, name='link-sync', daemon=True).start()

    def news_companies(self, news_id):
        if news_id not in self.events:
            raise ApiError(404, 'Новость не найдена')
        self.reload_links()
        rows = [dict(company=self.companies[r['company_id']], **r) for r in self.link_rows.values()
                if r['news_id'] == news_id and r['active'] and r['company_id'] in self.companies]
        rows.sort(key=lambda r: ({'high': 3, 'medium': 2, 'low': 1}.get(r['importance'], 0), r['match_score'] or 0), reverse=True)
        return {'items': [{k: v for k, v in r.items() if k != 'analysis_result'} for r in rows],
                'available': self.links_initialized, 'sync': dict(self.links_sync)}

    def load_snapshots(self):
        base = self.root / 'research' / 'evaluation'
        baseline = read_json(base / '2026-10-22' / 'evaluation.json', {})
        self.events = {row['id']: row for row in baseline.get('events', [])}
        for row in baseline.get('classifications', []):
            if row.get('result'):
                self.classifications[row['news_id']] = row['result']
        dataset = read_json(self.root / 'docs' / 'companies' / 'companies_analytics.json', {})
        for group in dataset.get('groups', []):
            for row in group['companies']:
                main = row['main']
                self.companies[row['company_id']] = {
                    'id': row['company_id'], 'industry': main['okved']['name'],
                    'okved': main['okved']['code'], 'region': main['location']['region'],
                    'revenue_rub': main['annual_revenue_rub'], 'payments': row['payments'],
                    'services': [k for k, v in main['bank_services'].items() if v is True],
                    'countries': main['foreign_trade_countries'], 'stage': main['business_stage'],
                }
        improved = read_json(base / '2026-10-22-improved' / 'comparison.json', {})
        self.matches = {row['company_id']: row['candidates'] for row in improved.get('matches', [])}
        bank = read_json(base / '2026-10-22-bank' / 'results.json', {})
        rows = baseline.get('analyses', []) + improved.get('analyses', []) + bank.get('analyses', [])
        for row in rows:
            state = row.get('result')
            if isinstance(state, dict) and state.get('event') and state.get('result'):
                self.analyses[(state['company_id'], state['news_id'])] = state
        default = read_json(base / '2026-10-22-bank' / 'default-cli-result.json')
        if default:
            self.analyses[(default['company_id'], default['news_id'])] = default
        for path in sorted(self.runtime.glob('analysis-*.json')):
            try:
                state = read_json(path)
                if state.get('company_id') in self.companies and state.get('event') and state.get('result'):
                    key = (state['company_id'], state['news_id'])
                    prior = self.analyses.get(key)
                    if prior is None or datetime.fromisoformat(state['as_of']) >= datetime.fromisoformat(prior['as_of']):
                        self.analyses[key] = state
            except (ValueError, TypeError, KeyError):
                LOG.warning('Skipped invalid cached analysis')
        self.documents = read_json(self.root / 'research' / 'bank' / 'manifest.json', {}).get('documents', [])
        for state in self.analyses.values():
            self.events[state['news_id']] = state['event']
            classification = state.get('preparation', {}).get('classification')
            if classification:
                self.classifications[state['news_id']] = classification

    def refresh_database(self):
        """Read current source records; retained snapshots remain visibly identified on failure."""
        if time.monotonic() - self.database_checked < 30:
            return
        self.database_checked = time.monotonic()
        if not os.environ.get('NEWS_DATABASE_URL'):
            self.database_status = 'snapshot'
            return
        try:
            from news_repository import NewsReader
            from company_repository import CompanyReader
            from sqlalchemy import select
            from app.modules.companies.models import Company
            reader = NewsReader.from_env()
            articles = reader.articles.list_articles()
            events = {}
            for article in articles:
                value = article.ai_event()
                value['publisher'] = article.publisher
                events[value['id']] = value
            companies = {}
            company_reader = CompanyReader.from_env()
            with company_reader.session() as session:
                for row in session.scalars(select(Company)):
                    companies[row.id] = {
                        'id': row.id, 'industry': row.okved_name, 'okved': row.okved_code,
                        'region': row.region, 'revenue_rub': row.annual_revenue_rub,
                        'payments': row.details.get('payments', {}),
                        'services': [k for k, v in row.bank_services.items() if v is True],
                        'countries': row.foreign_trade_countries, 'stage': row.business_stage,
                    }
            with self.lock:
                self.events, self.companies = events, companies
                self.database_status = 'connected'
        except Exception:
            self.database_status = 'unavailable'
            LOG.warning('Source database unavailable; retained snapshot is displayed')

    def bootstrap(self):
        self.refresh_database()
        self.reload_links()
        with self.lock:
            return {
                'companies': [{**c, 'profile_id': profile_id(c['okved'])} for c in self.companies.values()],
                'profiles': [{**p, 'analysis_count': sum(cid in p['company_ids'] for cid, _ in self.analyses)}
                             for p in list_profiles(list(self.companies.values()))],
                'documents': self.documents,
                'status': {'database': self.database_status, 'news_count': len(self.events),
                           'company_count': len(self.companies), 'document_count': len(self.documents),
                           'analysis_count': len(self.analyses), 'live_available': bool(os.environ.get('LLM_API_KEY')) and self.database_status == 'connected',
                           'updated_at': max((e['published_at'] for e in self.events.values()), default=None),
                           'links_sync': dict(self.links_sync), 'links_count': len(self.link_rows),
                           'links_available': self.links_initialized, 'feedback_available': self.feedback_repository is not None},
            }

    def pair(self, company_id, news_id):
        if company_id not in self.companies:
            raise ApiError(404, 'Компания не найдена')
        if news_id not in self.events:
            raise ApiError(404, 'Новость не найдена')
        return company_id, news_id

    def card(self, company_id, event, candidate=None):
        state = self.analyses.get((company_id, event['id']))
        brief = (state or {}).get('brief')
        short_answer = (brief or {}).get('short_answer')
        if not short_answer and state:
            from brief import _shorten
            short_answer = _shorten((state.get('result') or {}).get('summary') or '') or None
        classification = (brief or {}).get('classification') or self.classifications.get(event['id'], {})
        link = self.link_rows.get((company_id, event['id']))
        if link:
            classification = {**classification, 'importance': link['importance'], 'importance_reason': link['importance_reason'],
                'importance_method': link['importance_method'], 'topics': link['topics'] or classification.get('topics', [])}
        return {
            **event, 'text': event['text'][:1500], 'publisher': event.get('publisher') or self.publisher(event['url']),
            'classification': classification, 'has_analysis': bool(state), 'brief': brief, 'short_answer': short_answer,
            'analysis_status': (state or {}).get('result', {}).get('status'),
            'match_reasons': (candidate or {}).get('match_reasons', []),
            'retrieval_channels': (candidate or {}).get('retrieval_channels', []),
            'link': {k: link[k] for k in ('importance_status', 'analysis_status', 'match_method', 'match_score', 'importance_evidence')} if link else None,
        }

    @staticmethod
    def publisher(url):
        host = urlparse(url).hostname or ''
        for domain, name in [('vedomosti', 'Ведомости'), ('kommersant', 'Коммерсантъ'), ('interfax', 'Интерфакс'), ('rbc', 'РБК'), ('tass', 'ТАСС')]:
            if domain in host:
                return name
        return host.removeprefix('www.')

    def demo_control(self, data):
        if set(data) - {'company_id', 'action', 'demo_id'} or data.get('action') not in ('start', 'stop', 'retry'):
            raise ApiError(400, 'Некорректная команда сценария')
        company_id = data.get('company_id')
        if not isinstance(company_id, str) or company_id not in self.companies:
            raise ApiError(404, 'Компания не найдена')
        if data['action'] != 'start' and (not isinstance(data.get('demo_id'), str) or not re.fullmatch(r'[a-f0-9]{32}', data['demo_id'])):
            raise ApiError(400, 'Некорректный идентификатор сценария')
        try:
            if data['action'] == 'stop':
                return self.expert_demo.stop(data.get('demo_id'), company_id)
            self.refresh_database()
            if not os.environ.get('LLM_API_KEY') or not os.environ.get('EXPERT_DATABASE_URL'):
                raise ApiError(503, 'Для сценария нужны ключ моделей и EXPERT_DATABASE_URL')
            if self.database_status != 'connected' or not self.links_initialized:
                raise ApiError(503, 'Дождитесь подключения базы и подготовки хранилища связей')
            if data['action'] == 'retry':
                return self.expert_demo.retry(data['demo_id'], company_id)
            return self.expert_demo.start(list(self.companies.values()), company_id)
        except ValueError as error:
            raise ApiError(409, str(error)) from None

    def process_expert(self, event, company_id, progress, cancelled):
        self.expert_pipeline.links = self.links
        return self.expert_pipeline(event, company_id, progress, cancelled)

    def feed(self, company_id, demo_id=None):
        self.refresh_database()
        if company_id not in self.companies:
            raise ApiError(404, 'Компания не найдена')
        self.reload_links()
        candidates = {r['id']: r for r in self.matches.get(company_id, [])}
        with self.lock:
            cards = [self.card(company_id, event, candidates.get(event['id'])) for event in self.events.values()]
        importance_order = {'high': 3, 'medium': 2, 'low': 1}
        cards.sort(key=lambda c: (c['id'] in candidates, importance_order.get(c['classification'].get('importance'), 0), c['has_analysis'],
                                  candidates.get(c['id'], {}).get('retrieval_score', 0), c['published_at']), reverse=True)
        demo = None
        if demo_id:
            try:
                demo = self.expert_demo.view(demo_id, company_id)
            except ValueError as error:
                raise ApiError(409, str(error)) from None
            cards = demo['items'] + cards
            candidates.update({c['id']: c for c in demo['items'] if c.get('link') is not None})
            demo = {key: value for key, value in demo.items() if key != 'items'}
        return {'company_id': company_id, 'demo': demo, 'items': cards, 'matched_ids': list(candidates),
                'matching_as_of': (self.links_sync.get('updated_at') or now())[:10] if self.links_initialized else '2026-10-22',
                'sync': dict(self.links_sync), 'links_available': self.links_initialized,
                'pending_importance': sum(r['active'] and r['importance_status'] == 'pending' for r in self.link_rows.values()),
                'matching_note': 'Связи хранятся в базе; сходство не является доказанным влиянием.' if self.links_initialized else 'Сохранённый набор сопоставлений.'}

    def analysis(self, company_id, news_id, demo_id=None):
        from bank_context import describe_bank_context
        from app.modules.feedback.repository import analysis_version
        if demo_id and news_id.startswith('demo:'):
            try:
                value = self.expert_demo.analysis(demo_id, company_id, news_id)
            except ValueError as error:
                raise ApiError(409, str(error)) from None
            pair = next((row for row in value['matches'] if row['company_id'] == company_id), None)
            return {**value, 'company': self.companies[company_id], 'link': pair,
                    'analysis_version': analysis_version(value['state']) if value['state'] else None,
                    'bank_context': describe_bank_context(value['state'])}
        key = self.pair(company_id, news_id)
        self.reload_links()
        with self.lock:
            state = self.analyses.get(key)
        return {'state': state, 'event': self.events[news_id], 'company': self.companies[company_id],
                'analysis_version': analysis_version(state) if state else None,
                'bank_context': describe_bank_context(state), 'link': self.link_rows.get(key)}

    def feedback(self, data, reviewer_id, *, write=False):
        from app.modules.feedback.repository import analysis_version
        if set(data) - {'company_id', 'news_id', 'analysis_version', 'vote', 'demo_id'}:
            raise ApiError(400, 'Некорректные поля оценки')
        if not isinstance(data.get('company_id'), str) or not isinstance(data.get('news_id'), str):
            raise ApiError(400, 'Укажите компанию и новость')
        if data.get('demo_id') is not None and not isinstance(data['demo_id'], str):
            raise ApiError(400, 'Некорректный сценарий')
        detail = self.analysis(data['company_id'], data['news_id'], data.get('demo_id'))
        state = detail['state']
        if not state:
            raise ApiError(409, 'Сначала дождитесь готового разбора')
        version = analysis_version(state)
        if data.get('analysis_version') != version:
            raise ApiError(409, 'Разбор обновился. Откройте его заново перед оценкой.')
        if not self.feedback_repository:
            raise ApiError(503, 'Хранилище оценок недоступно. Проверьте подключение к базе.')
        if write and ('vote' not in data or (data['vote'] is not None and (type(data['vote']) is not int or data['vote'] not in (-1, 1)))):
            raise ApiError(400, 'Оценка должна быть 1, -1 или null')
        if not detail.get('is_demo') and data.get('demo_id'):
            raise ApiError(400, 'Сценарий указан для обычной новости')
        try:
            result = self.feedback_repository.save(state, reviewer_id, data['vote'], demo_id=data.get('demo_id')) if write else \
                self.feedback_repository.read(data['company_id'], data['news_id'], version, reviewer_id)
        except Exception as error:
            LOG.warning('Feedback storage unavailable (%s)', type(error).__name__)
            raise ApiError(503, 'Не удалось сохранить или прочитать оценку. Попробуйте ещё раз.') from None
        return {**result, 'analysis_version': version, 'is_demo': bool(detail.get('is_demo'))}

    def bank_sources(self):
        with self.lock:
            sources = {s['source_id']: s for state in self.analyses.values() for s in state.get('retrieved_sources', []) if s['kind'] == 'bank'}
        return list(sources.values())

    def bank_document(self, document_id):
        document = next((d for d in self.documents if d['id'] == document_id), None)
        if not document:
            raise ApiError(404, 'Материал не найден')
        if self.database_status != 'connected':
            return {'document': document, 'chunks': [], 'available': False}
        try:
            from sqlalchemy import select
            from app.shared.db.session import get_session_factory
            from app.modules.analytics.models import AnalyticsDocument, AnalyticsChunk
            factory = get_session_factory(os.environ.get('BANK_DATABASE_URL') or os.environ['NEWS_DATABASE_URL'])
            with factory() as session:
                exists = session.scalar(select(AnalyticsDocument.id).where(AnalyticsDocument.id == document_id,
                    AnalyticsDocument.published_at <= datetime.now(timezone.utc)))
                rows = list(session.scalars(select(AnalyticsChunk).where(AnalyticsChunk.document_id == exists)
                    .order_by(AnalyticsChunk.ordinal).limit(500))) if exists else []
                return {'document': document, 'available': bool(rows),
                        'chunks': [{'id': r.id, 'text': r.text, 'pages': r.pages, 'section_path': r.section_path} for r in rows]}
        except Exception:
            raise ApiError(503, 'Не удалось прочитать материал из базы. Попробуйте позже') from None

    def start_job(self, data, kind='analysis'):
        demo_state = None
        if isinstance(data.get('news_id'), str) and data['news_id'].startswith('demo:'):
            if kind != 'chat' or not isinstance(data.get('demo_id'), str):
                raise ApiError(400, 'Тестовая новость обрабатывается автоматически; после разбора доступен чат')
            value = self.analysis(data.get('company_id'), data['news_id'], data['demo_id'])
            demo_state = value['state']
            if not demo_state:
                raise ApiError(409, 'Дождитесь готового тестового разбора')
            company_id, news_id = data['company_id'], data['news_id']
        else:
            company_id, news_id = self.pair(data.get('company_id'), data.get('news_id'))
        if kind == 'matching' and not self.links_initialized:
            raise ApiError(503, 'Хранилище связей ещё не готово')
        if not os.environ.get('LLM_API_KEY') and self.runner == self.run_analysis:
            raise ApiError(503, 'Для новых разборов нужен ключ LLM_API_KEY на сервере')
        if kind in ('analysis', 'matching') and self.runner == self.run_analysis and self.database_status != 'connected':
            raise ApiError(503, 'Для нового разбора нужна доступная база данных')
        with self.lock:
            active = [j for j in self.jobs.values() if j['status'] in ('queued', 'running')]
            for job in active:
                if kind == 'analysis' and job['kind'] == kind and (job['company_id'], job['news_id']) == (company_id, news_id):
                    return dict(job)
            if len(active) >= 2:
                raise ApiError(429, 'Сейчас выполняются другие запросы. Попробуйте чуть позже')
            if len(self.jobs) >= 200:
                for key in list(self.jobs):
                    if self.jobs[key]['status'] in ('done', 'failed'):
                        self.jobs.pop(key)
                        break
            question, conversation_id = None, None
            if kind == 'chat':
                question = data.get('question', '')
                if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1500:
                    raise ApiError(400, 'Вопрос должен содержать от 1 до 1500 символов')
                if not demo_state and (company_id, news_id) not in self.analyses:
                    raise ApiError(409, 'Сначала подготовьте разбор этой новости')
                conversation_id = data.get('conversation_id') or uuid4().hex
                if not isinstance(conversation_id, str) or not re.fullmatch(r'[a-f0-9]{32}', conversation_id):
                    raise ApiError(400, 'Некорректный идентификатор диалога')
                if conversation_id in self.conversations:
                    conversation = self.conversations[conversation_id]
                    if conversation['pair'] != (company_id, news_id) or conversation.get('demo_id') != (data.get('demo_id') if demo_state else None):
                        raise ApiError(409, 'Этот диалог относится к другой компании и новости')
                    if len(conversation['turns']) >= 10:
                        raise ApiError(409, 'Достигнут лимит диалога. Откройте новость заново')
                    if any(j.get('conversation_id') == conversation_id for j in active):
                        raise ApiError(409, 'Дождитесь предыдущего ответа')
                else:
                    if len(self.conversations) >= 100:
                        raise ApiError(429, 'Достигнут лимит диалогов. Перезапустите сервер')
                    self.conversations[conversation_id] = {'pair': (company_id, news_id), 'turns': [],
                        'state': demo_state or self.analyses[(company_id, news_id)],
                        'demo_id': data.get('demo_id') if demo_state else None}
            job = {'id': uuid4().hex, 'kind': kind, 'company_id': company_id, 'news_id': news_id,
                   'is_demo': bool(demo_state),
                   'status': 'queued', 'stage': 'В очереди', 'created_at': now(), 'conversation_id': conversation_id}
            self.jobs[job['id']] = job
            self.executor.submit(self.execute, job['id'], question)
            return dict(job)

    def execute(self, job_id, question):
        with self.lock:
            job = self.jobs[job_id]
            job.update(status='running', stage='Подготовка контекста')
        def progress(stage):
            with self.lock:
                job['stage'] = stage
        pair = None
        try:
            if job['kind'] == 'analysis':
                if self.links:
                    pair = self.links.ensure(job['company_id'], job['news_id'])
                    self.links.claim_analysis(pair, job_id)
                state = self.runner(job['company_id'], job['news_id'], progress)
                if (state['company_id'], state['news_id']) != (job['company_id'], job['news_id']):
                    raise ValueError('Analysis identity mismatch')
                if pair and not self.links.analysis(pair, state, run_id=job_id):
                    raise ValueError('Source records changed while analysis was running')
                path = self.runtime / ('analysis-' + job['id'] + '.json')
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
                temporary.replace(path)
                with self.lock:
                    self.analyses[(job['company_id'], job['news_id'])] = state
                self.reload_links()
            elif job['kind'] == 'matching':
                if not self.links or not self.links_initialized:
                    raise ValueError('Link storage unavailable')
                from app.modules.links.service import LinkService
                service = LinkService(self.links, self.classifications, progress)
                try:
                    service.match_news(job['news_id'])
                    self.classifications.update(service.classifications)
                finally:
                    service.close()
                self.reload_links()
                job['matches'] = self.news_companies(job['news_id'])
            else:
                with self.lock:
                    state = self.conversations[job['conversation_id']]['state']
                    history = list(self.conversations[job['conversation_id']]['turns'])
                response = self.chat_runner(state, question, history, progress)
                # Test/custom runners may still return an Insight directly.
                answer = response.get('answer', response)
                sources = response.get('retrieved_sources', [])
                retrieval = response.get('retrieval', {})
                with self.lock:
                    self.conversations[job['conversation_id']]['turns'].append({'question': question, 'answer': answer,
                        'retrieved_sources': sources, 'retrieval': retrieval})
                    job['answer'] = answer
                    job['retrieved_sources'] = sources
                    job['retrieval'] = retrieval
            with self.lock:
                job.update(status='done', stage='Готово', finished_at=now())
        except Exception as exc:
            if pair:
                try:
                    self.links.analysis_failed(pair, job_id)
                except Exception:
                    LOG.warning('Could not persist analysis failure')
            LOG.warning('Job %s failed (%s)', job_id, type(exc).__name__)
            with self.lock:
                job.update(status='failed', stage='Запрос не выполнен', finished_at=now(),
                           error='Не удалось получить проверенный результат. Проверьте доступность моделей и базы, затем повторите запрос.')

    @staticmethod
    def run_analysis(company_id, news_id, progress):
        from database import DatabaseSettings, PostgresRepository
        from database_agent import DatabaseResearchAgent
        from news_repository import NewsReader
        from company_repository import CompanyReader
        from bank_repository import BankReader
        from provider import LangChainClient
        class ProgressClient(LangChainClient):
            def prepare(self, *args, **kwargs):
                progress('Классификация и факты новости')
                return super().prepare(*args, **kwargs)
            def research_step(self, *args, **kwargs):
                progress('Поиск по компании, новостям и материалам банка')
                return super().research_step(*args, **kwargs)
            def analyze(self, *args, **kwargs):
                progress('Анализ влияния и проверка оснований')
                return super().analyze(*args, **kwargs)
            def brief(self, *args, **kwargs):
                progress('Короткая сводка и оценка важности')
                return super().brief(*args, **kwargs)
        client = ProgressClient()
        try:
            cutoff = datetime.now(timezone.utc)
            repository = PostgresRepository(DatabaseSettings.from_env(), news_reader=NewsReader.from_env(),
                company_reader=CompanyReader.from_env(), bank_reader=BankReader.from_env(), as_of=cutoff)
            state = DatabaseResearchAgent(repository, client, as_of=cutoff).run(company_id, news_id)
            state['telemetry'] = client.telemetry
            return state
        finally:
            client.close()

    @staticmethod
    def run_chat(state, question, history, progress):
        from bank_repository import BankReader
        from company_repository import CompanyReader
        from database import DatabaseSettings, PostgresRepository
        from chat_agent import DatabaseChatAgent
        from news_repository import NewsReader
        from provider import LangChainClient
        client = LangChainClient()
        try:
            cutoff = datetime.now(timezone.utc)
            repository = PostgresRepository(DatabaseSettings.from_env(), news_reader=NewsReader.from_env(),
                company_reader=CompanyReader.from_env(), bank_reader=BankReader.from_env(), as_of=cutoff)
            return DatabaseChatAgent(repository, client, as_of=cutoff, progress=progress).run(state, question, history)
        finally:
            client.close()


def make_handler(application, static_root):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AlfaBusiness'

        def log_message(self, *args):
            pass

        def send(self, status, data, content_type='application/json; charset=utf-8', headers=None):
            payload = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store' if content_type.startswith('application/json') else 'no-cache')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
            self.end_headers()
            self.wfile.write(payload)

        def reviewer(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                reviewer = cookie['alfa_feedback'].value if 'alfa_feedback' in cookie else ''
            except CookieError:
                reviewer = ''
            if re.fullmatch(r'[a-f0-9]{32}', reviewer):
                return reviewer, {}
            reviewer = uuid4().hex
            return reviewer, {'Set-Cookie': 'alfa_feedback=' + reviewer + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000'}

        def do_GET(self):
            try:
                url = urlparse(self.path)
                query = parse_qs(url.query)
                company_id, news_id = query.get('company_id', [''])[0], query.get('news_id', [''])[0]
                if url.path == '/api/bootstrap':
                    return self.send(200, application.bootstrap())
                if url.path == '/api/feed':
                    return self.send(200, application.feed(company_id, query.get('demo_id', [None])[0]))
                if url.path == '/api/analysis':
                    return self.send(200, application.analysis(company_id, news_id, query.get('demo_id', [None])[0]))
                if url.path == '/api/feedback':
                    reviewer, headers = self.reviewer()
                    data = {'company_id': company_id, 'news_id': news_id, 'analysis_version': query.get('analysis_version', [''])[0]}
                    if query.get('demo_id'):
                        data['demo_id'] = query['demo_id'][0]
                    return self.send(200, application.feedback(data, reviewer), headers=headers)
                if url.path == '/api/news-companies':
                    if news_id.startswith('demo:'):
                        value = application.analysis(company_id, news_id, query.get('demo_id', [None])[0])
                        rows = [{**row, 'company': application.companies[row['company_id']]}
                                for row in value['matches'] if row['company_id'] in application.companies]
                        return self.send(200, {'items': rows, 'available': False, 'is_demo': True})
                    return self.send(200, application.news_companies(news_id))
                if url.path == '/api/bank-sources':
                    return self.send(200, application.bank_sources())
                if url.path == '/api/bank-document':
                    return self.send(200, application.bank_document(query.get('id', [''])[0]))
                if url.path.startswith('/api/jobs/'):
                    with application.lock:
                        job = application.jobs.get(url.path.rsplit('/', 1)[-1])
                        if not job:
                            raise ApiError(404, 'Запрос не найден')
                        return self.send(200, dict(job))
                if url.path.startswith('/api/'):
                    raise ApiError(404, 'Маршрут не найден')
                path = (static_root / url.path.lstrip('/')).resolve()
                if not path.is_relative_to(static_root.resolve()):
                    raise ApiError(404, 'Файл не найден')
                if not path.is_file():
                    if '.' in path.name:
                        raise ApiError(404, 'Файл не найден')
                    path = static_root / 'index.html'
                if not path.is_file():
                    raise ApiError(503, 'Интерфейс ещё не собран. Выполните сборку frontend')
                import mimetypes
                return self.send(200, path.read_bytes(), mimetypes.guess_type(path)[0] or 'application/octet-stream')
            except ApiError as exc:
                self.send(exc.status, {'error': exc.message})
            except Exception as exc:
                LOG.warning('Read request failed (%s)', type(exc).__name__)
                self.send(500, {'error': 'Не удалось загрузить данные'})

        def do_POST(self):
            try:
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'):
                    raise ApiError(403, 'Запрос должен быть отправлен из приложения')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ApiError(415, 'Ожидается application/json')
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    raise ApiError(400, 'Некорректный размер запроса')
                if not 0 < size <= 16000:
                    raise ApiError(413, 'Слишком большой или пустой запрос')
                try:
                    data = json.loads(self.rfile.read(size))
                except (ValueError, UnicodeDecodeError):
                    raise ApiError(400, 'Некорректный JSON')
                if not isinstance(data, dict):
                    raise ApiError(400, 'Ожидается объект запроса')
                if self.path == '/api/expert-demo':
                    return self.send(200, application.demo_control(data))
                if self.path == '/api/feedback':
                    reviewer, headers = self.reviewer()
                    return self.send(200, application.feedback(data, reviewer, write=True), headers=headers)
                if set(data) - {'company_id', 'news_id', 'question', 'conversation_id', 'demo_id'}:
                    raise ApiError(400, 'Некорректные поля запроса')
                if not isinstance(data.get('company_id'), str) or not isinstance(data.get('news_id'), str):
                    raise ApiError(400, 'Укажите компанию и новость')
                if self.path not in ('/api/analysis', '/api/chat', '/api/matches'):
                    raise ApiError(404, 'Маршрут не найден')
                kind = {'/api/chat': 'chat', '/api/matches': 'matching', '/api/analysis': 'analysis'}[self.path]
                return self.send(202, application.start_job(data, kind))
            except ApiError as exc:
                self.send(exc.status, {'error': exc.message})
            except Exception as exc:
                LOG.warning('Write request failed (%s)', type(exc).__name__)
                self.send(500, {'error': 'Не удалось запустить запрос'})
    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from model_config import load_environment
    load_environment()
    application = Application()
    application.start_links_worker()
    static_root = Path(os.environ.get('WEB_STATIC_DIR', ROOT / 'frontend' / 'dist'))
    server = ThreadingHTTPServer((os.environ.get('WEB_HOST', '127.0.0.1'), int(os.environ.get('WEB_PORT', '8080'))), make_handler(application, static_root))
    LOG.info('Web application is listening on port %s', server.server_port)
    try:
        server.serve_forever()
    finally:
        application.links_stop.set()
        server.server_close()
        application.executor.shutdown(wait=False, cancel_futures=True)
        application.expert_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
