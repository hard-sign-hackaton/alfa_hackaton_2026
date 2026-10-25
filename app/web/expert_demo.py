"""Schedule synthetic arrivals; every subsequent stage runs in the normal pipeline."""
from copy import deepcopy
from datetime import datetime, timezone
import logging
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from .profiles import profile_id

LOG = logging.getLogger('expert-demo')
SECTOR = {
    'automotive': ('автозапчастей', 'Поставщики автозапчастей объявили об увеличении отпускных цен'),
    'appliances': ('бытовой техники', 'Дистрибьюторы бытовой техники сообщили о новых условиях поставок'),
    'logistics': ('перевозок', 'Перевозчики объявили об изменении топливных надбавок'),
    'real_estate': ('недвижимости', 'Арендаторы коммерческих помещений запросили пересмотр условий'),
    'other': ('торговли', 'Поставщики сообщили об изменении условий закупок'),
}
TERMINAL = {'ready', 'not_matched', 'not_business', 'duplicate', 'failed', 'cancelled'}


def public_pair(row):
    return deepcopy({key: value for key, value in row.items() if key != 'analysis_result'})


class ExpertDemo:
    TTL = 3600
    MAX_SESSIONS = 16
    OFFSETS = (2, 10, 18, 26)

    def __init__(self, processor=None, executor=None, clock=time.monotonic, auto_schedule=True):
        self.clock, self.sessions, self.lock = clock, {}, RLock()
        self.processor, self.executor, self.auto_schedule = processor, executor, auto_schedule

    def start(self, company):
        if self.processor is None or self.executor is None:
            raise ValueError('Реальный обработчик сценария не подключён')
        with self.lock:
            for key, session in list(self.sessions.items()):
                if self.clock() - session['started'] >= self.TTL:
                    session['stop'].set()
                    self.sessions.pop(key)
            if len(self.sessions) >= self.MAX_SESSIONS:
                raise ValueError('Достигнут лимит сценариев. Завершите предыдущий.')
            if any(s['company_id'] == company['id'] and not s['stop'].is_set()
                   and any(e['phase'] not in TERMINAL for e in s['entries']) for s in self.sessions.values()):
                raise ValueError('Для компании уже запущен сценарий')
            sid = uuid4().hex
            sector, headline = SECTOR[profile_id(company['okved'])]
            titles = ['ТЕСТ: Ключевая ставка снижена на один процентный пункт', 'ТЕСТ: ' + headline,
                      'ТЕСТ: Новая программа поддержки отрасли ' + sector]
            bodies = [
                'В вымышленном событии регулятор снизил ключевую ставку на один процентный пункт. '
                'Новые условия действуют со следующего рабочего дня. Банки пересматривают ставки по новым '
                'кредитам; условия действующих договоров автоматически не меняются. Объём изменения спроса неизвестен.',
                'В вымышленной публикации участники рынка ' + sector + ' объявили о пересмотре цен по новым '
                'договорам со следующего месяца из-за роста транспортных расходов. Размер изменения и перечень '
                'затронутых организаций не раскрыты. Действующие договоры сохраняют прежние условия до пересмотра.',
                'В вымышленном событии объявлен проект программы поддержки отрасли ' + sector + '. '
                'Планируется субсидировать часть расходов компаний. Критерии участия, бюджет и дата начала '
                'приёма заявок пока не утверждены. Принадлежность к отрасли не гарантирует доступность поддержки.',
            ]
            stamp = datetime.now(timezone.utc).isoformat()
            entries = []
            for index in range(4):
                original = index if index < 3 else 0
                event = {'id': 'demo:' + sid + ':' + str(index), 'title': titles[original],
                         'text': titles[original] + '. ' + bodies[original] + ' Это тестовый сценарий, не реальная новость.',
                         'url': 'https://expert-demo.invalid/' + sid + '/' + str(index),
                         'published_at': stamp, 'publisher': 'Тестовый сценарий', 'topics': [], 'is_demo': True}
                entries.append({'event': event, 'offset': self.OFFSETS[index], 'phase': 'scheduled',
                                'stage': 'Ожидает поступления', 'state': None, 'matches': []})
            self.sessions[sid] = {'id': sid, 'company_id': company['id'], 'started': self.clock(),
                                  'entries': entries, 'stop': Event()}
        if self.auto_schedule:
            Thread(target=self._schedule, args=(sid, company['id']), daemon=True, name='expert-arrivals').start()
        return self.view(sid, company['id'])

    def _session(self, sid, company_id):
        session = self.sessions.get(sid)
        if not session or session['stop'].is_set() or self.clock() - session['started'] >= self.TTL:
            raise ValueError('Сценарий завершён. Запустите его заново.')
        if session['company_id'] != company_id:
            raise ValueError('Сценарий относится к другой компании. Запустите новый сценарий.')
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
        if cancelled():
            return
        try:
            result = self.processor(deepcopy(entry['event']), company_id, progress, cancelled)
            if cancelled():
                return
            if result.get('duplicate'):
                progress('duplicate', 'Дубль отклонён при сохранении в БД', duplicate_of=result['duplicate_of'])
            else:
                state = result.get('state')
                phase = 'ready' if state else 'not_business' if result.get('not_business') else 'not_matched'
                progress(phase, 'Обработка завершена' if state else 'Для выбранной компании связь не найдена',
                         state=state, matches=result.get('matches', []), telemetry=result.get('telemetry', []))
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
                phase, state = entry['phase'], entry['state']
                timeline.append({'title': 'Повтор первой публикации' if index == 3 else entry['event']['title'], 'phase': phase, 'stage': entry['stage'],
                                 'duplicate_of': entry.get('duplicate_of')})
                if phase in ('scheduled', 'duplicate') or index == 3:
                    continue
                pair = next((row for row in entry['matches'] if row['company_id'] == company_id), None)
                classification = deepcopy((state or {}).get('brief', {}).get('classification', {}))
                if pair:
                    classification.update({key: pair.get(key) for key in ('importance', 'importance_reason', 'topics')})
                cards.append({**entry['event'], 'classification': classification,
                              'has_analysis': bool(state), 'brief': (state or {}).get('brief'),
                              'short_answer': (state or {}).get('brief', {}).get('short_answer'),
                              'analysis_status': 'ready' if state else 'failed' if phase == 'failed' else 'running' if phase not in TERMINAL else 'not_matched',
                              'demo_phase': phase, 'demo_stage': entry['stage'], 'demo_order': index,
                              'match_reasons': (pair or {}).get('match_reasons', []),
                              'retrieval_channels': ['expert_pipeline'], 'link': public_pair(pair) if pair else None})
            done = all(e['phase'] in TERMINAL for e in session['entries'])
            return {'id': sid, 'company_id': company_id, 'status': ('failed' if any(e['phase'] == 'failed' for e in session['entries']) else 'done') if done else 'running',
                    'elapsed_seconds': int(elapsed), 'duration_seconds': self.OFFSETS[-1],
                    'received': sum(e['phase'] != 'scheduled' for e in session['entries']),
                    'unique': len(cards), 'ready': sum(bool(e['state']) for e in session['entries']),
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
            return {'state': deepcopy(entry['state']), 'event': deepcopy(entry['event']), 'is_demo': True,
                    'ready': bool(entry['state']), 'phase': entry['phase'], 'stage': entry['stage'],
                    'matched': any(row['company_id'] == company_id for row in entry['matches']),
                    'matches': [public_pair(row) for row in entry['matches']]}

    def stop(self, sid, company_id):
        with self.lock:
            session = self._session(sid, company_id)
            session['stop'].set()
            self.sessions.pop(sid)
            return {'status': 'stopped'}
