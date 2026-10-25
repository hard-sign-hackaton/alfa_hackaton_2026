"""Schedule synthetic arrivals; every subsequent stage runs in the normal pipeline."""
from copy import deepcopy
from datetime import datetime, timezone
import logging
import json
from pathlib import Path
import re
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from .expert_news import scenario_publications

LOG = logging.getLogger('expert-demo')
TERMINAL = {'ready', 'not_matched', 'not_business', 'duplicate', 'failed', 'cancelled'}


def public_pair(row):
    return deepcopy({key: value for key, value in row.items() if key != 'analysis_result'})


class ExpertDemo:
    TTL = 3600
    MAX_SESSIONS = 16

    def __init__(self, processor=None, executor=None, clock=time.monotonic, auto_schedule=True, runtime=None):
        self.clock, self.sessions, self.lock = clock, {}, RLock()
        self.processor, self.executor, self.auto_schedule = processor, executor, auto_schedule
        self.active_id = None
        self.runtime = Path(runtime) if runtime else None
        self._restored = False
        self._restore()

    def _save(self, session):
        if not self.runtime:
            return
        self.runtime.mkdir(parents=True, exist_ok=True)
        payload = {key: value for key, value in session.items() if key not in ('started', 'stop')}
        path = self.runtime / ('expert-demo-' + session['id'] + '.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    def _restore(self):
        if not self.runtime:
            return
        for path in sorted(self.runtime.glob('expert-demo-*.json'), reverse=True):
            try:
                session = json.loads(path.read_text(encoding='utf-8'))
                sid = session['id']
                elapsed = time.time() - session['started_at']
                if not re.fullmatch(r'[a-f0-9]{32}', sid) or session.get('stopped') or not 0 <= elapsed < self.TTL:
                    continue
                members = session['company_ids']
                if not members or session['company_id'] not in members:
                    raise ValueError('Invalid restored company scope')
                for entry in session['entries']:
                    if not entry['event']['id'].startswith('demo:' + sid + ':'):
                        raise ValueError('Restored publication has a different session')
                    for cid, state in entry.get('states', {}).items():
                        if cid not in members or state['company_id'] != cid or state['news_id'] != entry['event']['id']:
                            raise ValueError('Restored analysis identity mismatch')
                    if entry['phase'] not in TERMINAL or entry['phase'] == 'failed':
                        entry.update(phase='scheduled', stage='Восстановлено · в очереди обработки')
                session.update(started=self.clock() - elapsed, stop=Event())
                self.sessions[sid] = session
                self.active_id = sid
                return
            except (ValueError, KeyError, TypeError):
                LOG.warning('Skipped invalid expert session snapshot')

    def resume(self):
        with self.lock:
            if self._restored or self.active_id not in self.sessions:
                return
            self._restored = True
            session = self.sessions[self.active_id]
            Thread(target=self._schedule, args=(session['id'], session['company_id']), daemon=True, name='expert-resume').start()

    def start(self, companies, company_id=None):
        companies = [companies] if isinstance(companies, dict) else companies
        company_id = company_id or companies[0]['id']
        companies = sorted(companies, key=lambda company: company['id'] != company_id)
        company_ids = [company['id'] for company in companies]
        if company_id not in company_ids:
            raise ValueError('Компания не входит в сценарий')
        if self.processor is None or self.executor is None:
            raise ValueError('Реальный обработчик сценария не подключён')
        with self.lock:
            for key, session in list(self.sessions.items()):
                if self.clock() - session['started'] >= self.TTL:
                    session['stop'].set()
                    self.sessions.pop(key)
            if len(self.sessions) >= self.MAX_SESSIONS:
                raise ValueError('Достигнут лимит сценариев. Завершите предыдущий.')
            if self.active_id in self.sessions:
                return self.view(self.active_id, company_id)
            sid = uuid4().hex
            definitions = scenario_publications(companies)
            definitions.append({**deepcopy(definitions[0]), 'is_repeat': True})
            stamp = datetime.now(timezone.utc).isoformat()
            entries = []
            for index, definition in enumerate(definitions):
                event = {**definition, 'id': 'demo:' + sid + ':' + str(index),
                         'url': 'https://expert-demo.invalid/' + sid + '/' + str(index),
                         'published_at': stamp, 'publisher': 'Тестовый сценарий', 'topics': [], 'is_demo': True}
                entries.append({'event': event, 'offset': 2 + index, 'phase': 'scheduled',
                                'stage': 'Ожидает поступления', 'state': None, 'states': {}, 'matches': []})
            self.sessions[sid] = {'id': sid, 'company_id': company_id, 'company_ids': company_ids,
                                  'started': self.clock(), 'started_at': time.time(), 'entries': entries, 'stop': Event()}
            self.active_id = sid
            self._save(self.sessions[sid])
        if self.auto_schedule:
            Thread(target=self._schedule, args=(sid, company_id), daemon=True, name='expert-arrivals').start()
        return self.view(sid, company_id)

    def _session(self, sid, company_id):
        session = self.sessions.get(sid)
        if not session or session['stop'].is_set() or self.clock() - session['started'] >= self.TTL:
            raise ValueError('Сценарий завершён. Запустите его заново.')
        if company_id not in session['company_ids']:
            raise ValueError('Компания не входит в глобальный сценарий.')
        return session

    def _schedule(self, sid, company_id):
        while True:
            with self.lock:
                try:
                    session = self._session(sid, company_id)
                except ValueError:
                    return
                self._advance(session)
                if all(e['phase'] != 'scheduled' for e in session['entries']):
                    return
                stop = session['stop']
            stop.wait(.5)

    def _advance(self, session):
        for entry in session['entries']:
            if entry['phase'] == 'scheduled' and self.clock() - session['started'] >= entry['offset']:
                entry.update(phase='received', stage='Получена · в очереди обработки')
                self._save(session)
                self.executor.submit(self._process, session['id'], session['company_id'], entry)

    def _process(self, sid, company_id, entry):
        def cancelled():
            with self.lock:
                try:
                    self._session(sid, company_id)
                    return False
                except ValueError:
                    return True
        def progress(phase, stage, **values):
            with self.lock:
                if cancelled():
                    raise ValueError('Scenario stopped')
                entry.update(phase=phase, stage=stage, **deepcopy(values))
                self._save(self.sessions[sid])
        if cancelled():
            return
        try:
            result = self.processor(deepcopy(entry['event']), company_id, progress, cancelled)
            if cancelled():
                return
            if result.get('duplicate'):
                progress('duplicate', 'Дубль отклонён при сохранении в БД', duplicate_of=result['duplicate_of'])
            else:
                states = result.get('states', {})
                state = result.get('state')
                if state:
                    states = {**states, state['company_id']: state}
                phase = 'ready' if states else 'not_business' if result.get('not_business') else 'not_matched'
                progress(phase, 'Обработка завершена' if states else 'Подходящие компании не найдены',
                         state=state, states=states, matches=result.get('matches', []), telemetry=result.get('telemetry', []))
        except Exception as exc:
            LOG.warning('Expert processing failed (%s)', type(exc).__name__)
            if not cancelled():
                progress('failed', 'Ошибка обработки. Проверьте доступность моделей и БД.')

    def view(self, sid, company_id):
        with self.lock:
            session = self._session(sid, company_id)
            self._advance(session)
            elapsed = self.clock() - session['started']
            cards, timeline = [], []
            for index, entry in enumerate(session['entries']):
                phase = entry['phase']
                states = {**entry.get('states', {})}
                if entry.get('state'):
                    states[entry['state']['company_id']] = entry['state']
                state = states.get(company_id)
                timeline.append({'title': 'Повтор первой публикации' if entry['event'].get('is_repeat') else entry['event']['title'], 'phase': phase, 'stage': entry['stage'],
                                 'duplicate_of': entry.get('duplicate_of')})
                if phase in ('scheduled', 'duplicate') or entry['event'].get('is_repeat'):
                    continue
                pair = next((row for row in entry['matches'] if row['company_id'] == company_id), None)
                target = entry['event'].get('target_company_id')
                if target and target != company_id and not pair:
                    continue
                display_phase = 'not_matched' if phase == 'ready' and not pair else phase
                display_stage = 'Для выбранной компании связь не найдена' if display_phase == 'not_matched' else entry['stage']
                classification = deepcopy((state or {}).get('brief', {}).get('classification', {}))
                if pair:
                    classification.update({key: pair.get(key) for key in ('importance', 'importance_reason', 'topics')})
                cards.append({**entry['event'], 'classification': classification,
                              'has_analysis': bool(state), 'brief': (state or {}).get('brief'),
                              'short_answer': (state or {}).get('brief', {}).get('short_answer'),
                              'analysis_status': 'ready' if state else 'failed' if phase == 'failed' else 'running' if phase not in TERMINAL else 'not_matched',
                              'demo_phase': display_phase, 'demo_stage': display_stage, 'demo_order': index,
                              'match_reasons': (pair or {}).get('match_reasons', []),
                              'retrieval_channels': ['expert_pipeline'], 'link': public_pair(pair) if pair else None})
            done = all(e['phase'] in TERMINAL for e in session['entries'])
            return {'id': sid, 'company_id': company_id, 'status': ('failed' if any(e['phase'] == 'failed' for e in session['entries']) else 'done') if done else 'running',
                    'elapsed_seconds': int(elapsed), 'duration_seconds': session['entries'][-1]['offset'],
                    'expected_unique': len(session['entries']) - 1, 'expected_received': len(session['entries']),
                    'company_count': len(session['company_ids']), 'global': True,
                    'received': sum(e['phase'] != 'scheduled' for e in session['entries']),
                    'unique': sum(e['phase'] not in ('scheduled', 'duplicate') and not e['event'].get('is_repeat') for e in session['entries']),
                    'ready': sum(bool(e.get('states', {}).get(company_id) or (e.get('state') if (e.get('state') or {}).get('company_id') == company_id else None)) for e in session['entries']),
                    'processed': sum(e['phase'] in ('ready', 'not_matched', 'not_business') for e in session['entries']),
                    'analyses': sum(bool(row.get('analysis_result')) for e in session['entries'] for row in e['matches']),
                    'failed': sum(e['phase'] == 'failed' for e in session['entries']),
                    'duplicates': sum(e['phase'] == 'duplicate' for e in session['entries']),
                    'timeline': timeline, 'items': list(reversed(cards)), 'is_demo': True}

    def analysis(self, sid, company_id, news_id):
        with self.lock:
            session = self._session(sid, company_id)
            entry = next((e for e in session['entries'] if e['event']['id'] == news_id), None)
            if not entry or entry['phase'] == 'scheduled':
                raise ValueError('Тестовая новость ещё не поступила')
            states = dict(entry.get('states', {}))
            if entry.get('state'):
                states[entry['state']['company_id']] = entry['state']
            state = states.get(company_id)
            matched = any(row['company_id'] == company_id for row in entry['matches'])
            phase = 'not_matched' if entry['phase'] == 'ready' and not matched else entry['phase']
            return {'state': deepcopy(state), 'event': deepcopy(entry['event']), 'is_demo': True,
                    'ready': bool(state), 'phase': phase, 'stage': entry['stage'],
                    'matched': any(row['company_id'] == company_id for row in entry['matches']),
                    'matches': [public_pair(row) for row in entry['matches']]}

    def retry(self, sid, company_id):
        with self.lock:
            session = self._session(sid, company_id)
            for entry in session['entries']:
                if entry['phase'] == 'failed':
                    entry.update(phase='scheduled', stage='Повтор обработки')
            self._advance(session)
            self._save(session)
            return self.view(sid, company_id)

    def stop(self, sid, company_id):
        with self.lock:
            session = self._session(sid, company_id)
            session['stop'].set()
            session['stopped'] = True
            self._save(session)
            self.sessions.pop(sid)
            if self.active_id == sid:
                self.active_id = None
            return {'status': 'stopped'}
