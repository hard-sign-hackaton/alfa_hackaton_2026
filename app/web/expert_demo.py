"""Bounded, company-scoped playback. Test publications never enter source storage."""
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
import time
from uuid import uuid4

from .profiles import profile_id


SECTOR = {
    'automotive': ('автозапчастей', 'automotive', 'Поставщики автозапчастей объявили об увеличении отпускных цен',
                   'проверить условия закупок автозапчастей и сроки пересмотра цен'),
    'appliances': ('бытовой техники', 'electronics', 'Дистрибьюторы бытовой техники сообщили о новых условиях поставок',
                   'проверить закупочные контракты и график поставок техники'),
    'logistics': ('перевозок', 'logistics', 'Перевозчики объявили об изменении топливных надбавок',
                  'проверить топливные расходы и условия транспортных договоров'),
    'real_estate': ('недвижимости', 'real_estate', 'Арендаторы коммерческих помещений запросили пересмотр условий',
                    'проверить условия аренды и сроки пересмотра договоров'),
    'other': ('торговли', 'wholesale_trade', 'Поставщики сообщили об изменении условий закупок',
              'проверить закупочные договоры и структуру расходов'),
}


def build_state(company, event, explanation, topic, importance, bank_sources):
    from brief import CompactResult, Classification, CompactEvidence
    from contracts import CompanyProfile, NewsEvent, Insight, Claim, Evidence, evidence_sources, validate_evidence
    from tasks import NewsPreparation, TopicClassification, EventExtraction
    profile = CompanyProfile(id=company['id'], provenance='dataset', source_ref='expert-demo:company-profile',
        okved_codes=[company['okved']], okved_names=[company['industry']], registration_region=company.get('region'),
        ownership_form=None, annual_revenue_rub=float(company['revenue_rub']) if company.get('revenue_rub') is not None else None,
        banking_services=company.get('services', []), trade_countries=company.get('countries'), development_stage=company.get('stage'))
    news = NewsEvent.model_validate({key: event[key] for key in ('id', 'title', 'text', 'url', 'published_at', 'topics')})
    primary = Evidence(source_id='news:' + news.id, quote=news.title)
    own_id = 'company:' + profile.id + ':okved_names'
    own = Evidence(source_id=own_id, quote=evidence_sources(profile, news)[own_id])
    fact = Claim(kind='fact', text=news.title, evidence=[primary])
    hypothesis = Claim(kind='hypothesis', text=explanation, evidence=[primary, own])
    preparation = NewsPreparation(classification=TopicClassification(news_id=news.id, business_relevant=True,
        topics=[topic], evidence=[primary]), extraction=EventExtraction(news_id=news.id, facts=[fact], missing_data=[]))
    limitation = 'Тестовые новости и заранее подготовленные результаты. Событие не является реальной публикацией.'
    insight = Insight(company_id=profile.id, news_id=news.id, status='supported', summary=explanation,
        claims=[fact, hypothesis], missing_data=[limitation, 'Количественный эффект для компании не рассчитывается.'], follow_up_answer=None)
    sources = [s for s in bank_sources if s['published_at'] <= news.published_at][:2]
    validate_evidence(insight, profile, news, sources)
    brief = CompactResult(company_id=profile.id, news_id=news.id, status='ready', news_summary=news.title,
        short_answer=explanation, classification=Classification(business_relevant=True, topics=[topic],
            importance=importance, importance_method='rules', importance_reason='Иллюстрация связи с деятельностью выбранной компании.'),
        evidence=CompactEvidence(news_summary=[primary], short_answer=[primary, own], importance=[primary, own]))
    return {'mode': 'expert_demo', 'is_demo': True, 'company_id': profile.id, 'news_id': news.id,
        'as_of': news.published_at, 'company': profile.model_dump(), 'event': news.model_dump(),
        'preparation': preparation.model_dump(), 'result': insight.model_dump(), 'brief': brief.model_dump(),
        'retrieved_sources': sources, 'trace': [], 'history': [], 'research_stop': 'prepared_demo'}


class ExpertDemo:
    TTL = 900
    MAX_SESSIONS = 16
    OFFSETS = (2, 10, 18, 26)

    def __init__(self, clock=time.monotonic):
        self.clock, self.sessions, self.lock = clock, {}, RLock()

    def start(self, company, bank_sources=()):
        with self.lock:
            self.sessions = {key: s for key, s in self.sessions.items() if self.clock() - s['started'] < self.TTL}
            if len(self.sessions) >= self.MAX_SESSIONS:
                self.sessions.pop(next(iter(self.sessions)))
            session_id = uuid4().hex
            sector, topic, headline, check = SECTOR[profile_id(company['okved'])]
            definitions = [
                ('ТЕСТ: Ключевая ставка снижена на один процентный пункт', 'financial_markets', 'medium',
                 'В тестовом сценарии изменение ставки может повлиять на условия финансирования и спрос. Для компании нужно проверить кредитные договоры и условия расчётов.'),
                ('ТЕСТ: ' + headline, topic, 'high',
                 'Для компании из отрасли ' + sector + ' в этом сценарии стоит ' + check + '. Размер эффекта зависит от её договоров.'),
                ('ТЕСТ: Новая программа поддержки отрасли ' + sector, topic, 'medium',
                 'В тестовом сценарии поддержка отрасли может изменить спрос. Участие компании в программе и доступность поддержки требуют отдельной проверки.'),
            ]
            timestamp = datetime.now(timezone.utc).isoformat()
            entries = []
            for index, (title, event_topic, level, explanation) in enumerate(definitions):
                event = {'id': 'demo:' + session_id + ':' + str(index), 'title': title,
                    'text': title + '. Это вымышленная публикация для демонстрации обновления ленты.',
                    'url': '', 'published_at': timestamp, 'publisher': 'Тестовый сценарий', 'topics': [event_topic], 'is_demo': True}
                state = build_state(company, event, explanation, event_topic, level, list(bank_sources))
                entries.append({'event': event, 'state': state, 'offset': self.OFFSETS[index]})
            self.sessions[session_id] = {'id': session_id, 'company_id': company['id'], 'started': self.clock(), 'entries': entries}
            return self.view(session_id, company['id'])

    def _session(self, session_id, company_id):
        session = self.sessions.get(session_id)
        if not session or self.clock() - session['started'] >= self.TTL:
            raise ValueError('Тестовый сценарий завершён. Запустите его заново.')
        if session['company_id'] != company_id:
            raise ValueError('Сценарий относится к другой компании. Запустите новый сценарий.')
        return session

    def view(self, session_id, company_id):
        with self.lock:
            session = self._session(session_id, company_id)
            elapsed = self.clock() - session['started']
            cards, timeline = [], []
            for index, entry in enumerate(session['entries']):
                age = elapsed - entry['offset']
                phase = 'scheduled' if age < 0 else 'received' if age < 2 else 'matched' if age < 5 else 'ready'
                timeline.append({'title': entry['event']['title'], 'phase': phase})
                if age < 0:
                    continue
                state = entry['state']
                ready = phase == 'ready'
                cards.append({**entry['event'], 'classification': {'topics': entry['event']['topics'],
                    'importance': state['brief']['classification']['importance'] if age >= 2 else None},
                    'has_analysis': ready, 'brief': state['brief'] if ready else None,
                    'short_answer': state['brief']['short_answer'] if ready else None,
                    'analysis_status': 'ready' if ready else 'running', 'demo_phase': phase,
                    'demo_order': index, 'match_reasons': [], 'retrieval_channels': ['expert_demo'],
                    'link': {'importance_status': 'ready' if age >= 2 else 'pending', 'analysis_status': 'ready' if ready else 'running'}})
            duplicate = elapsed >= self.OFFSETS[3]
            # Exercise the same exact-content identity used by source ingestion.
            from app.modules.news.identity import input_hash
            original = session['entries'][0]['event']
            fingerprints = {input_hash(e['event']['title'], e['event']['text']) for e in session['entries']}
            duplicate = duplicate and input_hash(original['title'], original['text']) in fingerprints
            timeline.append({'title': 'Повтор первой публикации из второго источника', 'phase': 'duplicate' if duplicate else 'scheduled'})
            done = duplicate and all(t['phase'] == 'ready' for t in timeline[:3])
            return {'id': session_id, 'company_id': company_id, 'status': 'done' if done else 'running',
                'elapsed_seconds': int(elapsed), 'duration_seconds': self.OFFSETS[3],
                'received': len(cards) + int(duplicate), 'unique': len(cards),
                'ready': sum(c['has_analysis'] for c in cards), 'duplicates': int(duplicate),
                'timeline': timeline, 'items': list(reversed(cards)), 'is_demo': True}

    def analysis(self, session_id, company_id, news_id):
        with self.lock:
            session = self._session(session_id, company_id)
            entry = next((e for e in session['entries'] if e['event']['id'] == news_id), None)
            if not entry or self.clock() - session['started'] < entry['offset']:
                raise ValueError('Тестовая новость ещё не поступила')
            ready = self.clock() - session['started'] >= entry['offset'] + 5
            return {'state': deepcopy(entry['state']) if ready else None, 'event': dict(entry['event']),
                    'is_demo': True, 'ready': ready,
                    'matched': self.clock() - session['started'] >= entry['offset'] + 2}

    def stop(self, session_id, company_id):
        with self.lock:
            self._session(session_id, company_id)
            self.sessions.pop(session_id)
            return {'status': 'stopped'}
