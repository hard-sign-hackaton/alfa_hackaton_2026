"""Analysis workflow with checkpoints and a bounded search."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

from contracts import Claim, Evidence, Insight, validate_evidence
from ranking import industry_topics, rank_pair


def offline_insight(company, event, question=None):
    """Template-based offline analysis."""
    sector_source = f'company:{company.id}:okved_names'
    claims = [Claim(kind='fact', text=event.title,
                    evidence=[Evidence(source_id=f'news:{event.id}', quote=event.title)])]
    if company.okved_names:
        claims.append(Claim(kind='fact', text='Заявленный ОКВЭД: ' + company.okved_names[0],
                            evidence=[Evidence(source_id=sector_source, quote=company.okved_names[0])]))
    matches = industry_topics(company).intersection(event.topics)
    if matches and company.okved_names:
        claims.append(Claim(kind='hypothesis',
                            text='Отраслевое событие может повлиять на спрос в заявленном виде деятельности. '
                                 'Эффект для конкретной компании не измерен.',
                            evidence=[Evidence(source_id=f'news:{event.id}', quote=event.title),
                                      Evidence(source_id=sector_source, quote=company.okved_names[0])]))
    result = Insight(company_id=company.id, news_id=event.id,
                     status='supported' if matches else 'insufficient_data',
                     summary='Есть совпадение отрасли; влияние остаётся гипотезой.' if matches else
                             'Прямой канал влияния по имеющимся полям не подтверждён.',
                     claims=claims,
                     missing_data=['Фактические продажи, клиенты и структура затрат'] if matches else
                                  ['Подтверждённая связь деятельности или контрагентов с событием'],
                     follow_up_answer=('Количественный эффект неизвестен: нужны фактические продажи, '
                                       'клиенты и структура затрат.') if question else None)
    return validate_evidence(result, company, event)


class ResearchAgent:
    """Planner is a deterministic state machine; LLM is only the analysis step.

    Tools receive current company explicitly. No model-generated executable code or URLs.
    The checkpoint is private application state and must not be accepted from users.
    """
    def __init__(self, companies, events, *, client=None, as_of, checkpoint=None):
        self.companies = {company.id: company for company in companies}
        self.events = {event.id: event for event in events}
        self.client = client
        self.as_of = as_of
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.state = None

    def _record(self, tool, **result):
        self.state['trace'].append({'step': len(self.state['trace']) + 1,
                                    'tool': tool, **result})
        if self.checkpoint:
            self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.checkpoint.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.checkpoint)

    def run(self, company_id, news_id, *, question=None, resume=False):
        company, event = self.companies[company_id], self.events[news_id]
        digest = hashlib.sha256(json.dumps({
            'version': 1, 'company': company.model_dump(),
            'corpus': [item.model_dump() for item in self.events.values()],
            'news_id': news_id, 'question': question, 'as_of': self.as_of.isoformat(),
            'mode': 'live' if self.client else 'offline_baseline',
            'model': getattr(self.client, 'model', None),
        }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if resume and self.checkpoint and self.checkpoint.exists():
            saved = json.loads(self.checkpoint.read_text(encoding='utf-8'))
            if saved.get('fingerprint') != digest:
                raise ValueError('Checkpoint belongs to a different context')
            if saved.get('result'):
                insight = Insight.model_validate(saved['result'])
                validate_evidence(insight, company, event)
                self.state = saved
                return self.state
            self.state = saved
            self._record('resume', policy='Restart bounded plan after incomplete checkpoint')
        else:
            self.state = {'fingerprint': digest, 'company_id': company_id, 'news_id': news_id,
                          'mode': 'live' if self.client else 'offline_baseline',
                          'trace': [], 'history': [], 'result': None}
        self._record('plan', steps=['load_profile', 'rank', 'search_news',
                                   'check_payment_exposure', 'analyze', 'verify'])
        self._record('load_profile', provenance=company.provenance,
                     unknown_fields=[key for key, value in company.model_dump().items() if value is None])
        rank = rank_pair(company, event, as_of=self.as_of)
        self._record('rank', result=rank)
        if not rank['eligible']:
            raise ValueError('Future publication cannot enter analysis')
        # Narrow topic search, followed by exactly one broader search if nothing found.
        topics = industry_topics(company)
        found = [item.id for item in self.events.values() if item.id != news_id
                 and topics.intersection(item.topics)
                 and datetime.fromisoformat(item.published_at.replace('Z', '+00:00')) <= self.as_of]
        self._record('search_news', attempt=1, query=sorted(topics), source_ids=found)
        if not found:
            found = [item.id for item in self.events.values() if item.id != news_id
                     and datetime.fromisoformat(item.published_at.replace('Z', '+00:00')) <= self.as_of][:3]
            self._record('search_news', attempt=2, query='broader local business news', source_ids=found,
                         limitation='Broad results are discovery candidates, not evidence of company exposure')
        self._record('check_payment_exposure', available=False,
                     reason='Payment dataset unavailable')
        # Search candidates remain separate from the selected publication.
        self._record('assemble_context', source_scope=[f'news:{event.id}', f'company:{company.id}'],
                     discovered_not_used=found, bank_analytics_available=False)
        if self.client:
            insight = self.client.analyze(company, event)
            if question:
                self.state['history'] = [insight.model_dump()]
                insight = self.client.analyze(company, event, question=question, history=self.state['history'])
        else:
            insight = offline_insight(company, event, question)
        validate_evidence(insight, company, event)
        self.state['result'] = insight.model_dump()
        self._record('verify', schema=True, references=True, semantic_entailment='requires_human_review')
        return self.state
