"""Build a self-contained research report from saved, verifiable model runs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

from contracts import Insight, validate_evidence, evidence_sources
from dataset import CompanyDataset
from evaluate_dataset import PairAssessment
from tasks import TopicClassification
from retrieval import RetrievedSource
from contracts import NewsEvent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load(folder):
    return [read(path) for path in sorted(folder.glob('*.json'))]


def build(raw, dataset_path):
    dataset = CompanyDataset(dataset_path)
    manifest, events = read(raw / 'manifest.json'), read(raw / 'corpus.json')
    by_id = {event['id']: NewsEvent.model_validate(event) for event in events}
    classifications, reviews, analyses = load(raw / 'classification'), load(raw / 'reviews'), load(raw / 'analyses')
    # Revalidate saved outputs rather than relying on a stored success flag.
    for row in classifications:
        if 'result' in row:
            result = TopicClassification.model_validate(row['result'])
            event = by_id[row['news_id']]
            body = event.title + '\n' + event.text
            if result.news_id != event.id or any(e.source_id != 'news:' + event.id or e.quote not in body for e in result.evidence):
                raise ValueError('Saved classification evidence failed')
    for row in reviews:
        if 'result' not in row:
            continue
        value = PairAssessment.model_validate(row['result'])
        sources = evidence_sources(dataset.profile(row['company_id']), by_id[row['news_id']], dataset.metrics(row['company_id'], as_of=manifest['as_of']))
        if value.company_id != row['company_id'] or value.news_id != row['news_id']:
            raise ValueError('Saved review identity failed')
        if any(e.source_id not in sources or e.quote not in sources[e.source_id] for e in value.evidence):
            raise ValueError('Saved review evidence failed')
    for row in analyses:
        if 'result' not in row:
            continue
        state = row['result']
        validate_evidence(Insight.model_validate(state['result']), dataset.profile(row['company_id']), by_id[row['news_id']],
                          [RetrievedSource.model_validate(s) for s in state['retrieved_sources']])
    telemetry = [metric for row in classifications + reviews + analyses for metric in row.get('telemetry', [])]
    per_model = defaultdict(list)
    for metric in telemetry:
        per_model[metric['model']].append(metric)
    model_stats = []
    for model, metrics in per_model.items():
        latency = sorted(metric['latency_ms'] for metric in metrics if metric.get('latency_ms') is not None)
        model_stats.append({'model': model, 'attempts': len(metrics),
            'validated': sum(m['status'] in ('validated_references', 'tool_calls', 'finished') for m in metrics),
            'statuses': dict(Counter(m['status'] for m in metrics)),
            'tokens': sum((m.get('usage') or {}).get('total_tokens', 0) or 0 for m in metrics),
            'cost_usd': round(sum((m.get('usage') or {}).get('cost', 0) or 0 for m in metrics), 6),
            'median_seconds': round(statistics.median(latency) / 1000, 2) if latency else None,
            'p95_seconds': round(latency[min(len(latency) - 1, int(len(latency) * .95))] / 1000, 2) if latency else None})
    ranking = read(raw / 'baseline-ranking.json')
    retrieval = read(raw / 'retrieval.json')
    cases = read(raw / 'cases.json')
    review_map = {(r['company_id'], r['news_id']): r['result'] for r in reviews if 'result' in r}
    comparison = []
    for company_id in cases['representatives']:
        for variant in ('profile', 'payments'):
            query = next(row for row in retrieval['queries'] if row['company_id'] == company_id and row['variant'] == variant)
            top = query['hits'][:5]
            labels = [review_map.get((company_id, row['id'])) for row in top]
            judged = [label for label in labels if label is not None]
            comparison.append({'company_id': company_id, 'variant': variant, 'k': 5, 'judged': len(judged),
                'model_positive': sum(label['relevance'] in ('direct', 'indirect') for label in judged),
                'unjudged': len(top) - len(judged), 'labels': [label['relevance'] if label else 'not_reviewed' for label in labels]})
    baseline_by_company = []
    for company_id in dataset.rows:
        rows = [row for row in ranking if row['company_id'] == company_id]
        baseline_by_company.append({'company_id': company_id, 'evaluated': len(rows), 'nonzero': sum(row['score'] > 0 for row in rows),
                                    'at_least_50': sum(row['score'] >= 50 for row in rows), 'max_score': max((row['score'] for row in rows), default=0)})
    topic_counts = Counter(topic for row in classifications if 'result' in row for topic in row['result']['topics'])
    citation_count = sum(len(claim['evidence']) for row in analyses if 'result' in row for claim in row['result']['result']['claims'])
    qualitative_audit = []
    for row in analyses:
        if 'result' not in row:
            continue
        result = row['result']['result']
        phrase = 'годовые поступления от депозитов'
        if phrase in result['summary']:
            qualitative_audit.append({'company_id': row['company_id'], 'news_id': row['news_id'],
                'field': 'result.summary', 'observed': phrase, 'severity': 'requires_review',
                'finding': 'Summary превращает годовую выручку и наличие услуги «Депозиты» в годовые поступления от депозитов. В источниках такого показателя нет.',
                'source_fields': {'annual_revenue_rub': row['result']['company']['annual_revenue_rub'],
                                  'banking_services': row['result']['company']['banking_services']},
                'interpretation': 'Качественный разбор конкретного сохранённого ответа. Это не независимая оценка частоты галлюцинаций.'})
    diagnostic_failures = []
    for row in classifications:
        if 'result' not in row:
            path = raw / 'diagnostics' / (row['news_id'] + '.json')
            diagnostics = read(path) if path.exists() else []
            diagnostic_failures.append({'news_id': row['news_id'], 'title': row['title'], 'error': row['error'],
                'attempts': len(row['telemetry']), 'validation': [d['validation'] for d in diagnostics],
                'cause': 'Цитата не совпала с исходным текстом' if any('Invalid publication evidence' in d['validation'] for d in diagnostics) else 'См. журнал попыток'})
    company_rows = []
    for company_id in dataset.rows:
        row = dataset.rows[company_id]
        company_rows.append({'company_id': company_id, 'group_id': row['main']['group_id'], 'code': row['main']['okved']['code'],
            'industry': row['main']['okved']['name'], 'region': row['main']['location']['region'],
            'revenue_rub': row['main']['annual_revenue_rub'], 'top3_share': row['payments']['counterparties']['top_3_share_pct'],
            'counterparty_industries': [{'code': i['okved_class'], 'name': i['okved_name'], 'share_pct': i['share_pct']} for i in row['payments']['top_okved']]})
    summary = {'manifest': manifest, 'base_commit': '1881ea0',
        'corpus': {'news': len(events), 'companies': len(dataset.rows), 'groups': len(dataset.groups), 'possible_pairs': len(events) * len(dataset.rows),
                   'news_min': min(e['published_at'] for e in events), 'news_max': max(e['published_at'] for e in events),
                   'embedding_profile': retrieval['profile'], 'bank_documents_loaded': 0},
        'classification': {'success': sum('result' in row for row in classifications), 'failed': sum('result' not in row for row in classifications),
                           'first_pass_success': sum(not row.get('previous_errors') and 'result' in row for row in classifications),
                           'business': sum(row.get('result', {}).get('business_relevant', False) for row in classifications), 'topics': dict(topic_counts)},
        'reviews': {'planned': len(cases['pairs']), 'success': len(review_map), 'failed': len(reviews) - len(review_map),
                    'labels': dict(Counter(value['relevance'] for value in review_map.values())), 'selection': cases['selection']},
        'analyses': {'planned': len(read(raw / 'analysis-cases.json')) if (raw / 'analysis-cases.json').exists() else 0,
                     'success': sum('result' in row for row in analyses), 'failed': sum('result' not in row for row in analyses),
                     'citations_checked': citation_count,
                     'metric_context_runs': sum(any(s['kind'] == 'metric' for s in row['result']['retrieved_sources']) for row in analyses if 'result' in row)},
        'baseline': baseline_by_company, 'comparison': comparison, 'models': model_stats,
        'qualitative_audit': qualitative_audit, 'classification_failures': diagnostic_failures,
        'attempts': len(telemetry), 'reported_cost_usd': round(sum(row['cost_usd'] for row in model_stats), 6),
        'usage_missing_attempts': sum(not m.get('usage') for m in telemetry),
        'limitations': ['Модельные оценки не являются независимой экспертной разметкой или измеренной точностью.',
            'Выборка пар целевая: лучшие E5-кандидаты и контроли; она не случайная и не отложенная.',
            'Новости покрывают только один неполный день. Результат нельзя переносить на весь поток.',
            'Дат и периода платежей нет; текущая экспозиция, динамика и причинный эффект не установлены.',
            'Проверка цитат подтверждает наличие текста в источнике, но не истинность вывода и не логическое следование.',
            'Полные банковские документы не загружены: интеграция этого корпуса в исследовании не проверена.',
            'Cosine similarity E5 не является вероятностью релевантности. Платежное расширение запроса может вносить шум.',
            'Расход — сумма cost в ответах шлюза; для попыток без usage стоимость неизвестна.']}
    return {'summary': summary, 'companies': company_rows, 'events': events, 'rankings': ranking,
            'retrieval': [{**row, 'hits': row['hits'][:10]} for row in retrieval['queries']], 'cases': cases, 'reviews': reviews, 'analyses': analyses,
            'classifications': [{key: value for key, value in row.items() if key not in ('telemetry',)} for row in classifications]}


STYLE = '''
:root{--ink:#172126;--muted:#657477;--red:#e73530;--paper:#f5f4ef;--line:#dddeda;--green:#17765b}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,Segoe UI,sans-serif}main{max-width:1340px;padding:44px 32px 80px;margin:auto}header{border-top:5px solid var(--red);padding-top:22px}.eyebrow{letter-spacing:.14em;font-size:12px;text-transform:uppercase;color:var(--muted)}h1{font-size:clamp(36px,5vw,64px);line-height:1.05;letter-spacing:-.05em;margin:16px 0 22px}h2{font-size:28px;letter-spacing:-.025em;margin:0 0 12px}h3{margin:0 0 10px;font-size:18px}p{margin:8px 0 14px}.intro{max-width:870px;font-size:19px}.muted,.note{color:var(--muted)}.note{font-size:13px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:28px 0}.stat{padding:20px;background:white;border:1px solid var(--line);border-radius:12px}.stat strong{display:block;font-size:36px;letter-spacing:-.04em}.stat span{color:var(--muted);font-size:13px}section{margin-top:44px}.panel{background:white;padding:24px;border:1px solid var(--line);border-radius:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.alert{border-left:4px solid var(--red);background:#fff4ef;padding:18px 22px}.flow{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}.flow span{padding:9px 13px;border:1px solid var(--line);background:white;border-radius:7px}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-weight:500}td,th{padding:12px 10px;border-bottom:1px solid var(--line);vertical-align:top}.scroll{overflow:auto}a{color:#195b79;text-decoration:none}a:hover{text-decoration:underline}.badge{display:inline-block;padding:4px 8px;border-radius:5px;font-size:12px;white-space:nowrap}.direct{background:#c6e8d8;color:#135d41}.indirect{background:#e3efde;color:#426128}.weak{background:#fff0c5;color:#8c6b12}.unrelated{background:#eef0ef;color:#6c7676}.not_reviewed{background:#f8f8f6;color:#929a9a}.matrix td:first-child{min-width:390px;max-width:530px}.matrix th:not(:first-child),.matrix td:not(:first-child){min-width:140px}.matrix button{border:0;cursor:pointer;font:inherit}.matrix button:hover{outline:2px solid var(--ink)}.bar{height:7px;background:#eef0ed;border-radius:5px;margin-top:6px;overflow:hidden}.bar i{display:block;height:100%;background:var(--red)}.topic{display:grid;grid-template-columns:160px 1fr 35px;align-items:center;gap:12px;margin:10px 0;font-size:13px}select,input{padding:10px 12px;border:1px solid var(--line);border-radius:6px;background:white;font:inherit;max-width:100%}.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.case{margin-top:18px}.case summary{cursor:pointer;font-weight:650;font-size:16px}.case details{margin-top:12px}.case blockquote{margin:12px 0;padding:12px 16px;background:#f6f6f2;border-left:3px solid var(--line);font-size:13px;overflow-wrap:anywhere}.case .source{display:block;color:var(--muted);font-size:11px;margin-bottom:6px}.result{font-size:16px}.claim{padding:12px 0;border-top:1px solid var(--line)}.pill{display:inline-block;border:1px solid var(--line);padding:3px 7px;font-size:11px;border-radius:20px;margin-right:6px}.checks li{margin:8px 0}dialog{border:1px solid var(--line);border-radius:14px;max-width:820px;width:90%;max-height:85vh;padding:26px;color:var(--ink)}dialog::backdrop{background:#10242888}dialog button{float:right;background:white;border:1px solid var(--line);padding:6px 12px;border-radius:5px;cursor:pointer}footer{border-top:1px solid var(--line);margin-top:50px;padding-top:18px;font-size:12px;color:var(--muted)}.cost{font-variant-numeric:tabular-nums}.zero{color:var(--red);font-weight:700}ul{padding-left:20px}@media(max-width:850px){main{padding:24px 18px 60px}.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.panel{padding:16px}.stat strong{font-size:30px}.topic{grid-template-columns:130px 1fr 30px}}
'''

SCRIPT = r'''
const D=JSON.parse(document.getElementById('data').textContent), S=D.summary;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf=new Intl.NumberFormat('ru-RU'), labels={direct:'Прямая',indirect:'Косвенная',weak:'Слабая',unrelated:'Не подтверждена',not_reviewed:'Не проверено'};
const ev=Object.fromEntries(D.events.map(e=>[e.id,e])), co=Object.fromEntries(D.companies.map(c=>[c.company_id,c]));
const badge=x=>`<span class="badge ${esc(x)}">${esc(labels[x]||x)}</span>`;
const safeUrl=u=>(String(u||'').startsWith('https://')||String(u||'').startsWith('http://'))?esc(u):'';
const link=e=>`<a href="${safeUrl(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)}</a>`;
const stats=[['Публикации',S.corpus.news],['Компании / группы',`${S.corpus.companies} / ${S.corpus.groups}`],['Пары в базовом ранжировании',nf.format(D.rankings.length)],['Проверено моделью',`${S.reviews.success} / ${S.reviews.planned}`],['Полные разборы',`${S.analyses.success} / ${S.analyses.planned}`]];
document.getElementById('stats').innerHTML=stats.map(([label,value])=>`<div class="stat"><strong>${value}</strong><span>${label}</span></div>`).join('');
document.getElementById('topics').innerHTML=Object.entries(S.classification.topics).sort((a,b)=>b[1]-a[1]).map(([topic,n])=>`<div class="topic"><span>${esc(topic)}</span><div class="bar"><i style="width:${100*n/S.corpus.news}%"></i></div><b>${n}</b></div>`).join('');
document.getElementById('class-summary').textContent=`${S.classification.success} валидных ответов, ${S.classification.failed} незавершённых. Деловые: ${S.classification.business}. У новости может быть несколько тем.`;
document.getElementById('coverage').innerHTML='<table><thead><tr><th>Компания / ОКВЭД</th><th>Ненулевой балл</th><th>Балл ≥ 50</th></tr></thead><tbody>'+S.baseline.map(r=>`<tr><td>${esc(r.company_id)} · ${esc(co[r.company_id].code)}</td><td class="${r.nonzero?'':'zero'}">${r.nonzero} / ${r.evaluated}</td><td>${r.at_least_50}</td></tr>`).join('')+'</tbody></table>';
document.getElementById('model-stats').innerHTML='<table><thead><tr><th>Модель</th><th>Попытки</th><th>Медиана / p95, с</th><th>Токены</th><th>Стоимость, $</th></tr></thead><tbody>'+S.models.map(m=>`<tr><td>${esc(m.model)}<br><small>${esc(JSON.stringify(m.statuses))}</small></td><td>${m.attempts}</td><td>${m.median_seconds} / ${m.p95_seconds}</td><td>${nf.format(m.tokens)}</td><td class="cost">${m.cost_usd.toFixed(4)}</td></tr>`).join('')+'</tbody></table>';
document.getElementById('cost').textContent=`Всего ${S.attempts} попыток. Подтверждённая ответами стоимость: $${S.reported_cost_usd.toFixed(4)}. У ${S.usage_missing_attempts} попыток нет usage; их стоимость неизвестна.`;
document.getElementById('failure-audit').innerHTML='<h3>Отклонённые классификации</h3>'+S.classification_failures.map(r=>`<p><b>${esc(r.title)}</b><br>${esc(r.cause)} · попыток: ${r.attempts}.</p>`).join('')+`<p class="note">С первой полной серии без повторных запусков успешно завершились ${S.classification.first_pass_success} из ${S.corpus.news} классификаций. Одна серия уже включает до двух попыток встроенного retry.</p>`+'<h3>Смысловая проверка готовых разборов</h3>'+S.qualitative_audit.map(r=>`<div class="alert"><b>${esc(r.company_id)} · требуется проверка</b><p>Найденная формулировка: «${esc(r.observed)}».</p><p>${esc(r.finding)}</p><p class="note">${esc(r.interpretation)}</p></div>`).join('');
document.getElementById('matrix').innerHTML='<table class="matrix"><thead><tr><th>Одна новость — разные компании</th>'+D.cases.representatives.map(id=>`<th>${esc(id)}<br>${esc(co[id].code)}</th>`).join('')+'</tr></thead><tbody>'+D.cases.selected_news.map(id=>'<tr><td>'+link(ev[id])+'</td>'+D.cases.representatives.map(cid=>{const r=D.reviews.find(r=>r.company_id===cid&&r.news_id===id);return `<td><button data-company="${esc(cid)}" data-news="${esc(id)}" class="badge ${esc(r?.result?.relevance||'not_reviewed')}">${esc(labels[r?.result?.relevance||'not_reviewed'])}</button></td>`}).join('')+'</tr>').join('')+'</tbody></table>';
document.getElementById('matrix').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const r=D.reviews.find(r=>r.company_id===b.dataset.company&&r.news_id===b.dataset.news);if(!r?.result)return;const x=r.result;document.getElementById('dialog-content').innerHTML=`<h3>${esc(r.company_id)} · ${esc(ev[r.news_id].title)}</h3>${badge(x.relevance)}<p>${esc(x.mechanism)}</p>`+x.evidence.map(q=>`<blockquote><span class="source">${esc(q.source_id)}</span>${esc(q.quote)}</blockquote>`).join('')+'<h3>Ограничения</h3><ul>'+x.limitations.map(s=>`<li>${esc(s)}</li>`).join('')+'</ul>';document.getElementById('detail').showModal()});
const selector=document.getElementById('company');selector.innerHTML=D.companies.map(c=>`<option value="${esc(c.company_id)}">${esc(c.company_id)} · ${esc(c.code)} · ${esc(c.region)}</option>`).join('');
function renderRank(){const id=selector.value,c=co[id];document.getElementById('company-info').innerHTML=`<h3>${esc(c.industry)}</h3><p>Регион регистрации: ${esc(c.region)}. Доля трёх крупнейших контрагентов в обороте: <b>${c.top3_share}%</b>.</p><p class="note">Отрасли контрагентов: ${c.counterparty_industries.map(x=>`${esc(x.code)} — ${x.share_pct}%`).join('; ')}. Период агрегатов неизвестен.</p>`;document.getElementById('rankings').innerHTML=['profile','payments'].map(variant=>{const q=D.retrieval.find(r=>r.company_id===id&&r.variant===variant);return `<div class="panel"><h3>${variant==='profile'?'Запрос по профилю':'Профиль + отрасли контрагентов'}</h3><p class="note">${esc(q.query)}</p><table><thead><tr><th>Новость</th><th>E5</th><th>Базовый балл</th><th>Оценка модели</th></tr></thead><tbody>`+q.hits.slice(0,5).map(h=>{const r=D.reviews.find(r=>r.company_id===id&&r.news_id===h.id),base=D.rankings.find(r=>r.company_id===id&&r.news_id===h.id);return `<tr><td>${link(ev[h.id])}</td><td>${h.similarity.toFixed(3)}</td><td>${base?base.score:'—'}</td><td>${badge(r?.result?.relevance||'not_reviewed')}</td></tr>`}).join('')+'</tbody></table></div>'}).join('')};selector.onchange=renderRank;renderRank();
const caselist=document.getElementById('case-list');function renderCases(){const filter=document.getElementById('case-search').value.toLowerCase();caselist.innerHTML=D.analyses.filter(r=>r.result&&(`${r.company_id} ${ev[r.news_id].title}`).toLowerCase().includes(filter)).map(r=>{const state=r.result,x=state.result;return `<details class="panel case"><summary>${esc(r.company_id)} · ${esc(ev[r.news_id].title)}</summary><p class="result">${esc(x.summary)}</p><p class="note">Статус ${esc(x.status)} означает наличие цитируемых оснований; он не доказывает влияние на компанию. Вызовов инструментов: ${state.trace.length}, получено источников: ${state.retrieved_sources.length}.</p>`+x.claims.map(cl=>`<div class="claim"><span class="pill">${cl.kind==='fact'?'Факт источника':'Гипотеза'}</span>${esc(cl.text)}<details><summary>Основания</summary>`+cl.evidence.map(q=>`<blockquote><span class="source">${esc(q.source_id)}</span>${esc(q.quote)}</blockquote>`).join('')+'</details></div>').join('')+'<h3>Что неизвестно</h3><ul>'+x.missing_data.map(s=>`<li>${esc(s)}</li>`).join('')+'</ul><details><summary>Работа инструментов</summary><table><tbody>'+state.trace.map(t=>`<tr><td>${esc(t.tool)}</td><td>${esc(t.status)}</td><td>${esc(JSON.stringify(t.arguments))}</td></tr>`).join('')+'</tbody></table></details></details>'}).join('')};document.getElementById('case-search').oninput=renderCases;renderCases();
document.getElementById('limits').innerHTML=S.limitations.map(x=>`<li>${esc(x)}</li>`).join('');
document.getElementById('technical').textContent=JSON.stringify({as_of:S.manifest.as_of,base_commit:S.base_commit,dataset_sha256:S.manifest.dataset_sha256,news_embedding_profile:S.corpus.embedding_profile},null,2);
'''


def html(data):
    serialized = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Новости × компании — исследование пайплайна</title><style>''' + STYLE + '''</style><main>
<header><div class="eyebrow">Исследование пайплайна · 22 октября 2026 · dev 1881ea0</div><h1>Новости × компании</h1><p class="intro">Проверка на реальных профилях и платежных агрегатах: что находит поиск, где возникают ложные совпадения и какие выводы удаётся обосновать источниками.</p><div id="stats" class="stats"></div></header>
<div class="alert"><b>Главный вывод: пайплайн умеет собирать проверяемые разборы, но отбор новостей требует доработки.</b><br>У базового ранжировщика нет соответствий для ОКВЭД 45, 46 и 68. Широкие E5-запросы поднимают общие экономические новости. Смысловое сходство нужно проверять по конкретному каналу влияния.</div>
<section><h2>Как устроена проверка</h2><div class="flow"><span>153 новости</span><span>Gemma: деловая тема</span><span>E5: кандидаты</span><span>DeepSeek: связь с компанией</span><span>Qwen: факты</span><span>Агент + DeepSeek: разбор</span></div><p class="note">Готовые векторы прочитаны из отдельной копии дампа; корпус не переиндексирован. Все 12 компаний участвуют в поиске и базовом ранжировании. Углублённая выборка охватывает четыре вида деятельности, включая смешанный состав одной из групп. Классы связи ниже — диагностические оценки модели, а не независимая экспертная разметка.</p></section>
<section class="grid"><div class="panel"><h2>Классификация потока</h2><p id="class-summary" class="note"></p><div id="topics"></div></div><div class="panel"><h2>Покрытие базового ранжирования</h2><p class="note">ОКВЭД → тема, регион и страна торговли, затем поправка на возраст новости. Здесь регионы и страны в новостях не заполнены; балл не равен важности или вероятности.</p><div id="coverage"></div></div></section>
<section><h2>Одна новость для разных компаний</h2><p>Нажмите на ячейку, чтобы увидеть экономический канал, цитаты и ограничения. Контроли включают футбол и военный «логистический центр»: совпадение слов не должно превращаться в деловую рекомендацию.</p><p class="note">Целевая выборка: объединение top-2 E5-кандидатов по двум запросам и заранее выбранных отраслевых/отрицательных примеров. Полученную долю положительных оценок нельзя считать точностью всего поиска.</p><div class="panel scroll" id="matrix"></div></section>
<section><h2>Что попадает в выдачу</h2><div class="toolbar"><select id="company" aria-label="Компания"></select></div><div id="company-info"></div><div class="grid" id="rankings"></div><p class="note">E5 показывает cosine similarity: 0,8 не означает 80% вероятности релевантности. «Не проверено» означает отсутствие углублённой оценки этой пары. Добавление отраслей контрагентов — абляция запроса, а не доказанное улучшение.</p></section>
<section><h2>Полные разборы агента</h2><p>Отдельные факты и гипотезы, точные цитаты, недостающие данные и журнал обращений к инструментам. Банковский корпус не загружен: его отсутствие явно фиксируется, а не подменяется выдуманными выдержками.</p><p class="note">До двух модельно положительных и одного слабого/отрицательного случая на вид деятельности; модельные оценки используются для подбора диагностических примеров.</p><input id="case-search" placeholder="Найти компанию или новость" aria-label="Поиск по разборам"><div id="case-list"></div></section>
<section><h2>Надёжность и стоимость</h2><div class="panel scroll" id="model-stats"></div><p class="note" id="cost"></p><p class="note">Попытки включают сетевые ошибки, повторные запросы и ответы, отклонённые валидацией. В таблице задержки отдельного обращения, а не полного исследования. Классификация и извлечение фактов повторно используются для одной новости.</p><div class="panel" id="failure-audit"></div></section>
<section class="grid"><div class="panel"><h2>Что доработать</h2><ol class="checks"><li>Добавить отраслевые соответствия ОКВЭД 45, 46, 68 и точную тему недвижимости.</li><li>Разделить отраслевую связь, масштаб события и срочность: нынешний балл оценивает только совпадения.</li><li>Проверять E5-кандидатов по экономическому каналу; не использовать единый cosine-порог как вероятность.</li><li>Объединять публикации об одном событии: поток содержит повторы заголовков и сюжеты нескольких изданий.</li><li>Подключить полный корпус банковских чанков и проверить его отдельной абляцией.</li><li>Собрать независимую разметку и новые дни новостей перед измерением precision/recall.</li></ol></div><div class="panel"><h2>Границы исследования</h2><ul id="limits"></ul></div></section>
<section><details class="panel"><summary>Параметры воспроизводимости</summary><pre id="technical" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details></section><footer>Локальный исследовательский отчёт. Полные машиночитаемые результаты — evaluation.json; краткое описание — findings.md. Все числа получены из сохранённых ответов и повторно проверенных источников.</footer>
<dialog id="detail"><button onclick="document.getElementById('detail').close()">Закрыть</button><div id="dialog-content"></div></dialog>
<script type="application/json" id="data">''' + serialized + '''</script><script>''' + SCRIPT + '''</script></main></html>'''


def markdown(data):
    s = data['summary']
    lines = ['# Проверка сопоставления новостей и компаний', '', 'Снимок dev `1881ea0`, 22.10.2026.', '',
        f"Корпус: {s['corpus']['news']} новостей, {s['corpus']['companies']} компаний, {s['corpus']['groups']} группы. Базовый ранжировщик проверен на {len(data['rankings'])} парах.", '',
        f"Классификация: {s['classification']['success']} успешных, {s['classification']['failed']} незавершённых. Оценка связи: {s['reviews']['success']}/{s['reviews']['planned']} пар. Полный агент: {s['analyses']['success']}/{s['analyses']['planned']} разборов.", '',
        '## Выводы', '',
        '- В базовом словаре нет ОКВЭД 45, 46, 68. Компании этих классов теряют отраслевой сигнал; география в NewsEvent не заполнена.',
        '- E5 по широкому описанию компании поднимает общие новости о продаже активов ЛУКОЙЛа, валюте и налогах. Cosine не является вероятностью применимости.',
        '- Платежные агрегаты доступны агенту как отдельные цитируемые источники. Они показывают структуру связей и концентрацию, но не текущую динамику.',
        '- В группе с основным ОКВЭД 52 есть компания ОКВЭД 46.43: использовать один профиль на всю группу нельзя.',
        f"- Проверено {s['analyses']['citations_checked']} ссылок в утверждениях полных разборов. Наличие цитаты не гарантирует истинность и логическую корректность вывода.",
        '- Банковские документы не загружены в исследовательскую копию. Работа по этому корпусу не проверена.',
        f"- Без повторного запуска полной серии успешно завершились {s['classification']['first_pass_success']}/{s['corpus']['news']} классификаций (внутри серии уже есть встроенный retry).", '',
        '## Обнаруженные ошибки', '']
    lines += [f"- {r['title']}: {r['cause']}, попыток {r['attempts']}." for r in s['classification_failures']]
    lines += [f"- {r['company_id']}, {r['field']}: «{r['observed']}». {r['finding']}" for r in s['qualitative_audit']]
    lines += ['',
        '## Оценки связей моделью', '',
        '| Класс | Количество |', '|---|---:|']
    lines += [f'| {label} | {count} |' for label, count in s['reviews']['labels'].items()]
    lines += ['', 'Это целевая диагностическая выборка, а не независимая разметка. Accuracy, precision и recall по ней не измерялись.', '',
        '## Попытки моделей', '', '| Модель | Попытки | Токены | Медиана, с | Стоимость по ответам, $ |', '|---|---:|---:|---:|---:|']
    lines += [f"| {m['model']} | {m['attempts']} | {m['tokens']} | {m['median_seconds']} | {m['cost_usd']:.4f} |" for m in s['models']]
    lines += ['', f"Суммарно по usage.cost: ${s['reported_cost_usd']:.4f}. Попыток без usage: {s['usage_missing_attempts']}; их стоимость неизвестна.", '',
        '## Примеры полных разборов', '']
    events = {event['id']: event for event in data['events']}
    for row in data['analyses']:
        if 'result' not in row:
            lines += [f"- {row['company_id']} / {row['news_id']}: ошибка {row['error']}"]
            continue
        state = row['result']
        lines += [f"### {row['company_id']}: {events[row['news_id']]['title']}", '', state['result']['summary'], '',
                  f"Источников контекста: {len(state['retrieved_sources'])}; обращений к инструментам: {len(state['trace'])}.", '',
                  'Неизвестно: ' + '; '.join(state['result']['missing_data']), '']
    lines += ['## Воспроизведение', '',
        'Дамп восстановлен в отдельную БД `alfa_research_20261022`; роль `analysis_news_reader` имеет только SELECT. SHA-256 дампа: `7629377c97f13782ee5a991c5368b05c2456b7e1db4260b686f6df99c94f4936`.', '',
        'Запуск в Docker из корня репозитория: базы должны быть запущены, дамп восстановлен, роль чтения настроена, образ ai-agent-semantic собран.', '',
        '```sh', 'python scripts/run_dataset_evaluation.py classify --database alfa_research_20261022',
        'python scripts/run_dataset_evaluation.py retrieve --database alfa_research_20261022',
        'python scripts/run_dataset_evaluation.py select --database alfa_research_20261022',
        'python scripts/run_dataset_evaluation.py review --database alfa_research_20261022',
        'python scripts/run_dataset_evaluation.py analyze --database alfa_research_20261022',
        'python scripts/run_dataset_evaluation.py report --database alfa_research_20261022 --report-name 2026-10-22', '```', '',
        'Исходники: `research/ai/evaluate_dataset.py`, `dataset.py`, `build_evaluation_report.py`.', '',
        'Требуются актуальные зависимости проекта, LLM_API_KEY/LLM_BASE_URL, NEWS_DATABASE_URL с правами чтения восстановленного дампа и кеш E5. Для поиска используется семантический образ Docker и volume news-models.', '',
        '```sh', 'python research/ai/evaluate_dataset.py classify', 'python research/ai/evaluate_dataset.py retrieve',
        'python research/ai/evaluate_dataset.py select', 'python research/ai/evaluate_dataset.py review',
        'python research/ai/evaluate_dataset.py analyze',
        'python research/ai/build_evaluation_report.py --raw research/ai/live_results/dataset-20261022 --output research/evaluation/2026-10-22', '```', '',
        'Рабочий каталог — корень репозитория, PYTHONPATH должен включать корень проекта и research/ai. Выходной каталог сохраняет as_of и хеш исходного JSON. Успешные ответы классификации кешируются по содержимому и конфигурации моделей; неудачные повторяются. Перед изменением протокола или моделей выбирайте новый выходной каталог.', '',
        '## Ограничения', '']
    lines += ['- ' + value for value in s['limitations']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[2] / 'docs/companies/companies_analytics.json')
    args = parser.parse_args()
    data = build(args.raw, args.dataset)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'evaluation.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output / 'summary.json').write_text(json.dumps(data['summary'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output / 'report.html').write_text(html(data), encoding='utf-8')
    (args.output / 'findings.md').write_text(markdown(data), encoding='utf-8')
    print(json.dumps(data['summary'], ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
