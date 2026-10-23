import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button } from '@alfalab/core-components-button';
import '@alfalab/core-components-vars/index.css';
import { ArrowLeft, ArrowRight, ArrowUpRight, Bookmark, Building2, Check, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clock3, ExternalLink, FileText, Layers3, Loader2, MapPin, MessageSquare, Newspaper, RefreshCw, Search, Send, ShieldCheck, SlidersHorizontal, Sparkles, TrendingUp, Wallet, X } from 'lucide-react';
import './style.css';

type Obj = Record<string, any>;
type Company = { id: string; industry: string; okved: string; region: string; revenue_rub: number; services: string[]; countries: string[]; stage: string; payments: Obj };
type Card = { id: string; title: string; text: string; url: string; published_at: string; publisher: string; classification: Obj; has_analysis: boolean; brief?: Obj; analysis_status?: string; match_reasons: Obj[]; retrieval_channels: string[] };
type Bootstrap = { companies: Company[]; documents: Obj[]; status: Obj };
type Message = { role: 'user' | 'assistant'; text: string; claims?: Obj[] };
const topics: Record<string, string> = { financial_markets: 'Финансы', regulation: 'Регулирование', automotive: 'Автобизнес', energy: 'Энергетика', logistics: 'Логистика', retail_ecommerce: 'Торговля', metallurgy: 'Металлургия', other_business: 'Экономика', not_business: 'Вне бизнеса', real_estate: 'Недвижимость', construction: 'Строительство', agriculture: 'Сельское хозяйство', technology: 'Технологии' };
const serviceNames: Record<string, string> = { cash_settlement_rko: 'Расчётный счёт', bank_guarantees: 'Банковские гарантии', loans: 'Кредитование', credit: 'Кредитование', leasing: 'Лизинг', deposits: 'Депозиты', deposit: 'Депозиты', salary_project: 'Зарплатный проект', payroll: 'Зарплатный проект', factoring: 'Факторинг', cash_register: 'Эквайринг' };
const importance: Record<string, string> = { high: 'Высокая важность', medium: 'Средняя важность', low: 'Низкая важность' };
const shortIndustry = (c?: Company) => c ? c.okved.startsWith('45') ? 'Автозапчасти' : c.okved.startsWith('46.43') ? 'Бытовая техника' : c.okved.startsWith('52') ? 'Логистика' : c.okved.startsWith('68') ? 'Недвижимость' : 'Торговля' : '';
const date = (value?: string, long = false) => value ? new Date(value).toLocaleDateString('ru-RU', { day: 'numeric', month: long ? 'long' : 'short', ...(long ? { year: 'numeric' } : {}) }) : 'Дата не указана';
const money = (n: number) => new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 2 }).format(n) + ' ₽';
const safeUrl = (url: string) => { try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } };
const limitationText = (value: string) => value.includes('model_unavailable') ? 'Модель дополнительного поиска не завершила запрос. Разбор основан на материалах, полученных до остановки.' : value.startsWith('Сбор контекста остановлен:') ? 'Дополнительный контекст собран в пределах доступного лимита. Часть вопросов может требовать отдельной проверки.' : value.startsWith('Ограничение получения контекста:') ? 'Не все дополнительные материалы удалось получить. Это ограничивает полноту разбора.' : value;
async function api<T = Obj>(path: string, data?: Obj, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api' + path, { signal, ...(data ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) } : {}) });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Не удалось выполнить запрос');
  return body;
}
function useBookmarks() {
  const [saved, setSaved] = useState<string[]>(() => { try { const value = JSON.parse(localStorage.getItem('alfa-saved-v1') || '[]'); return Array.isArray(value) ? value.filter(v => typeof v === 'string') : []; } catch { return []; } });
  const toggle = (id: string) => setSaved(old => { const next = old.includes(id) ? old.filter(v => v !== id) : [...old, id]; try { localStorage.setItem('alfa-saved-v1', JSON.stringify(next)); } catch {} return next; });
  return { saved, toggle };
}
function Badge({ value }: { value?: string }) { return <span className={'badge ' + (value || 'unknown')}><i/>{importance[value || ''] || 'Важность не оценена'}</span>; }
function Logo() { return <div className="brand"><div className="alfa-mark" aria-hidden="true">A<span/></div><div>Альфа-Бизнес<small>Аналитика для бизнеса</small></div></div>; }
function ErrorBox({ message, retry }: { message: string; retry?: () => void }) { return <div className="error-box" role="alert"><CircleHelp size={20}/><div>{message}{retry && <button onClick={retry}>Повторить</button>}</div></div>; }
function Skeleton() { return <div className="skeleton-list" aria-label="Загрузка новостей">{[0, 1, 2, 3].map(i => <div className="skeleton" key={i}><i/><i/><i/><i/></div>)}</div>; }
function Evidence({ items, sources }: { items: Obj[]; sources: Record<string, Obj> }) {
  if (!items?.length) return null;
  return <details className="evidence"><summary><ShieldCheck size={14}/> Основания · {items.length}<ChevronDown size={14}/></summary><div>{items.map((e, i) => <blockquote key={i}><p>«{e.quote}»</p><small>{sources[e.source_id]?.title || (e.source_id.startsWith('company:') ? 'Профиль компании' : e.source_id.startsWith('metric:') ? 'Агрегаты платежей' : 'Исходная новость')}</small></blockquote>)}</div></details>;
}

function Payments({ company, compact = false }: { company: Company; compact?: boolean }) {
  const payments = company.payments;
  const totals = payments?.totals;
  if (!totals) return null;
  return <section className={'panel payments-panel ' + (compact ? 'compact-payments' : '')}><div className="section-icon"><Wallet size={19}/><h2>Платёжные связи</h2><span className="period-label">Период не указан</span></div>
    {!compact && <div className="payment-stats"><div><span>Входящие платежи</span><b>{money(totals.incoming_amount_rub)}</b></div><div><span>Исходящие платежи</span><b>{money(totals.outgoing_amount_rub)}</b></div><div><span>Контрагентов</span><b>{totals.unique_counterparties_count}</b></div></div>}
    <p className="muted small">Основные отрасли контрагентов · доля в платёжном обороте</p><div className="industry-bars">{(payments.top_okved || []).slice(0, 3).map((row: Obj, i: number) => <div key={row.okved_class}><div><span>{row.okved_name}</span><b>{row.share_pct.toLocaleString('ru-RU')}%</b></div><div className="bar-track"><i style={{ width: Math.min(100, row.share_pct) + '%', background: ['#ef3124', '#a5a9b2', '#d7d9df'][i] }}/></div></div>)}</div>
    {!compact && !!payments.counterparties?.top_3?.length && <details className="counterparty-details"><summary>Крупнейшие контрагенты<ChevronDown size={16}/></summary>{payments.counterparties.top_3.map((row: Obj) => <div className="counterparty-row" key={row.company_id}><div><b>{row.company_id}</b><span>{row.okved_name}</span><small>{row.region}</small></div><strong>{row.share_pct.toLocaleString('ru-RU')}%<small>оборота</small></strong></div>)}</details>}
    <p className="muted small payment-note">Оборот не равен выручке. Роли контрагентов, динамика и сезонность не установлены; перечень отраслей неполный.</p></section>;
}

function App() {
  const [boot, setBoot] = useState<Bootstrap>();
  const [bootError, setBootError] = useState('');
  const [companyId, setCompanyId] = useState(() => { try { return localStorage.getItem('alfa-company') || 'U_37452'; } catch { return 'U_37452'; } });
  const [section, setSection] = useState<'feed' | 'bank' | 'company'>('feed');
  const [mode, setMode] = useState('personal');
  const [feed, setFeed] = useState<{ items: Card[]; matched_ids: string[]; matching_as_of: string }>();
  const [loading, setLoading] = useState(true);
  const [feedError, setFeedError] = useState('');
  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState('all');
  const [level, setLevel] = useState('all');
  const [visibleCount, setVisibleCount] = useState(8);
  const [selectedId, setSelectedId] = useState<string>();
  const [detail, setDetail] = useState<Obj>();
  const [detailError, setDetailError] = useState('');
  const [detailTab, setDetailTab] = useState('analysis');
  const [job, setJob] = useState<Obj>();
  const [jobError, setJobError] = useState('');
  const [jobStarting, setJobStarting] = useState(false);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [chatOpen, setChatOpen] = useState(false);
  const [bankSources, setBankSources] = useState<Obj[]>([]);
  const [bankQuery, setBankQuery] = useState('');
  const [bankError, setBankError] = useState('');
  const [expandedDoc, setExpandedDoc] = useState<string>();
  const [documentData, setDocumentData] = useState<Obj>();
  const [documentError, setDocumentError] = useState('');
  const [reload, setReload] = useState(0);
  const { saved, toggle } = useBookmarks();
  const chatEnd = useRef<HTMLDivElement>(null);
  const company = boot?.companies.find(c => c.id === companyId);
  const state = detail?.state;
  const selectedCard = feed?.items.find(c => c.id === selectedId);
  const busy = jobStarting || (job && ['running', 'queued'].includes(job.status));
  const mountedPair = useRef('');
  mountedPair.current = companyId + ':' + selectedId;

  const loadBoot = () => { setBootError(''); api<Bootstrap>('/bootstrap').then(data => { setBoot(data); if (!data.companies.some(c => c.id === companyId) && data.companies[0]) setCompanyId(data.companies[0].id); }).catch(e => setBootError(e.message)); };
  useEffect(loadBoot, []);
  useEffect(() => {
    if (!boot) return;
    const controller = new AbortController();
    setLoading(true); setFeedError(''); setFeed(undefined); setVisibleCount(8);
    api<typeof feed>('/feed?company_id=' + encodeURIComponent(companyId), undefined, controller.signal).then(setFeed).catch(e => { if (e.name !== 'AbortError') setFeedError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [boot, companyId, reload]);
  useEffect(() => {
    setDetail(undefined); setDetailError(''); setMessages([]); setConversationId(undefined); setJob(undefined); setJobError(''); setQuestion(''); setChatOpen(false); setDetailTab('analysis');
    if (!selectedId) return;
    const controller = new AbortController();
    api('/analysis?company_id=' + encodeURIComponent(companyId) + '&news_id=' + encodeURIComponent(selectedId), undefined, controller.signal).then(setDetail).catch(e => { if (e.name !== 'AbortError') setDetailError(e.message); });
    return () => controller.abort();
  }, [companyId, selectedId]);
  useEffect(() => {
    if (!job || !['running', 'queued'].includes(job.status)) return;
    const pair = mountedPair.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const value = await api('/jobs/' + job.id, undefined, controller.signal);
        if (mountedPair.current !== pair) return;
        setJob(value);
        if (value.status === 'done') {
          if (value.kind === 'analysis') {
            const next = await api('/analysis?company_id=' + encodeURIComponent(companyId) + '&news_id=' + encodeURIComponent(selectedId!));
            if (mountedPair.current === pair) { setDetail(next); setMessages([]); setConversationId(undefined); setReload(v => v + 1); }
          } else { setMessages(old => [...old, { role: 'assistant', text: value.answer.follow_up_answer || value.answer.summary, claims: value.answer.claims }]); }
        }
        if (value.status === 'failed') setJobError(value.error);
      } catch (e: any) { if (e.name !== 'AbortError') { setJobError('Потеряно соединение. Откройте разбор заново, чтобы проверить результат.'); setJob(undefined); } }
    }, 1800);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [job]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages, job]);
  useEffect(() => { if (section === 'bank') { setBankError(''); api<Obj[]>('/bank-sources').then(setBankSources).catch(e => setBankError(e.message)); } }, [section, reload]);
  useEffect(() => {
    setDocumentData(undefined); setDocumentError('');
    if (!expandedDoc) return;
    const controller = new AbortController();
    api('/bank-document?id=' + encodeURIComponent(expandedDoc), undefined, controller.signal).then(setDocumentData).catch(e => { if (e.name !== 'AbortError') setDocumentError(e.message); });
    return () => controller.abort();
  }, [expandedDoc]);
  useEffect(() => { setVisibleCount(8); }, [query, topic, level, mode]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { if (chatOpen) setChatOpen(false); else setSelectedId(undefined); } };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, [chatOpen]);

  function changeCompany(id: string) { setCompanyId(id); setSelectedId(undefined); try { localStorage.setItem('alfa-company', id); } catch {} }
  function navigate(next: typeof section) { setSection(next); setSelectedId(undefined); setQuery(''); }
  async function start(kind: 'analysis' | 'chat', prompted?: string) {
    if (busy || !selectedId) return;
    const pair = mountedPair.current;
    const text = (prompted || question).trim();
    if (kind === 'chat' && !text) return;
    setJobStarting(true); setJobError('');
    try {
      const value = await api(kind === 'chat' ? '/chat' : '/analysis', { company_id: companyId, news_id: selectedId, ...(kind === 'chat' ? { question: text, conversation_id: conversationId } : {}) });
      if (mountedPair.current !== pair) return;
      setJob(value);
      if (kind === 'chat') { setConversationId(value.conversation_id); setMessages(old => [...old, { role: 'user', text }]); setQuestion(''); }
    } catch (e: any) { if (mountedPair.current === pair) setJobError(e.message); }
    finally { setJobStarting(false); }
  }

  const matched = new Set(feed?.matched_ids || []);
  const filtered = (feed?.items || []).filter(c => {
    if (mode === 'personal' && !matched.has(c.id) && !c.has_analysis) return false;
    if (mode === 'saved' && !saved.includes(companyId + ':' + c.id)) return false;
    if (topic !== 'all' && !c.classification.topics?.includes(topic)) return false;
    if (level !== 'all' && (level === 'ready' ? !c.has_analysis : c.classification.importance !== level)) return false;
    return !query || (c.title + ' ' + c.text + ' ' + (c.brief?.short_answer || '')).toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru'));
  });
  const availableTopics = [...new Set((feed?.items || []).flatMap(c => c.classification.topics || []))] as string[];
  const featured = feed?.items.find(c => c.brief);
  const pairSaved = (id: string) => saved.includes(companyId + ':' + id);
  const sources = Object.fromEntries((state?.retrieved_sources || []).map((s: Obj) => [s.source_id, s])) as Record<string, Obj>;
  const citedBank = new Set<string>((state?.result?.claims || []).flatMap((c: Obj) => c.evidence || []).map((e: Obj) => e.source_id).filter((id: string) => id.startsWith('bank:')));
  const news = detail?.event || selectedCard;
  const detailClassification = state?.brief?.classification || state?.preparation?.classification || selectedCard?.classification || {};
  const primaryTopic = (card: Card) => (card.classification.topics || []).map((t: string) => topics[t] || t)[0] || 'Новости';
  const docSources = (doc: Obj) => bankSources.filter(s => s.locator?.includes('/' + doc.id + '#') || s.title?.includes(doc.title));

  if (bootError) return <main className="startup"><Logo/><ErrorBox message={bootError} retry={loadBoot}/></main>;
  if (!boot) return <main className="startup"><Logo/><Loader2 className="spin"/><p>Собираем вашу ленту…</p></main>;
  return <div className="app-shell">
    <aside className="sidebar"><Logo/><div className="workspace-label">БИЗНЕС · ОБЗОР</div><nav aria-label="Основная навигация">
      <button className={section === 'feed' ? 'active' : ''} onClick={() => navigate('feed')}><Newspaper size={21}/>Моя лента<span>{feed?.matched_ids.length || '—'}</span></button>
      <button className={section === 'bank' ? 'active' : ''} onClick={() => navigate('bank')}><Layers3 size={21}/>Аналитика банка</button>
      <button className={section === 'company' ? 'active' : ''} onClick={() => navigate('company')}><Building2 size={21}/>Моя компания</button>
    </nav><div className="sidebar-note"><div className="note-symbol"><ShieldCheck size={23}/></div><b>Выводы с основаниями</b><p>У каждого разбора есть факты, источники и ограничения.</p></div><div className="sidebar-bottom"><span className={'status-dot ' + (boot.status.database === 'connected' ? 'green' : 'amber')}/>{boot.status.database === 'connected' ? 'Данные подключены' : 'Сохранённый набор'}<small>{boot.status.news_count} новостей · {boot.status.company_count} компаний</small></div></aside>
    <div className="workspace"><header className="topbar"><div className="mobile-brand"><Logo/></div><div className="breadcrumb">Бизнес <ChevronRight size={14}/><span>{section === 'bank' ? 'Аналитика банка' : section === 'company' ? 'Профиль компании' : 'Персональная аналитика'}</span></div><div className="company-switch"><span className="company-avatar"><Building2 size={18}/></span><label><span>Ваша компания</span><select aria-label="Выбрать компанию" value={companyId} onChange={e => changeCompany(e.target.value)}>{boot.companies.map(c => <option key={c.id} value={c.id}>{shortIndustry(c)} · {c.id}</option>)}</select></label><ChevronDown size={16}/></div><div className="user-avatar" aria-label="Бизнес-профиль">Б</div></header>
      <nav className="mobile-nav" aria-label="Разделы"><button className={section === 'feed' ? 'active' : ''} onClick={() => navigate('feed')}>Моя лента</button><button className={section === 'bank' ? 'active' : ''} onClick={() => navigate('bank')}>Аналитика банка</button><button className={section === 'company' ? 'active' : ''} onClick={() => navigate('company')}>Компания</button></nav>
      <main className={'main-content ' + (selectedId ? 'detail-content' : '')}>
      {selectedId ? <>
        <div className="detail-toolbar"><button className="back-link" onClick={() => setSelectedId(undefined)}><ArrowLeft size={17}/>К ленте</button><button className={'icon-button ' + (pairSaved(selectedId) ? 'saved' : '')} aria-label={pairSaved(selectedId) ? 'Убрать из сохранённого' : 'Сохранить новость'} onClick={() => toggle(companyId + ':' + selectedId)}><Bookmark size={20} fill={pairSaved(selectedId) ? 'currentColor' : 'none'}/></button></div>
        {detailError ? <ErrorBox message={detailError}/> : !detail ? <Skeleton/> : <>
        <div className="detail-heading"><div className="eyebrow">РАЗБОР ДЛЯ {companyId}</div><Badge value={detailClassification.importance}/><h1>{news.title}</h1><div className="news-meta"><span className="publisher-dot">{(selectedCard?.publisher || 'Н')[0]}</span>{selectedCard?.publisher || 'Публикация'}<span>·</span>{date(news.published_at, true)}<a href={safeUrl(news.url)} target="_blank" rel="noreferrer">Оригинал <ArrowUpRight size={14}/></a></div></div>
        <div className="detail-layout"><div className="detail-main"><div className="detail-tabs" role="tablist" aria-label="Содержание новости">{[['analysis', 'Разбор'], ['original', 'Исходная новость'], ['sources', 'Источники']].map(([key, title]) => <button key={key} role="tab" aria-selected={detailTab === key} onClick={() => setDetailTab(key)}>{title}</button>)}</div>
        {detailTab === 'original' ? <section className="panel original-text"><div className="eyebrow">ТЕКСТ ИСТОЧНИКА</div><h2>{news.title}</h2>{news.text.split('\n').filter(Boolean).map((p: string, i: number) => <p key={i}>{p}</p>)}<a className="text-link" href={safeUrl(news.url)} target="_blank" rel="noreferrer">Открыть публикацию <ExternalLink size={15}/></a></section> : detailTab === 'sources' ? <section className="panel"><h2>Источники разбора</h2><div className="source-item"><FileText/><div><b>Исходная новость</b><p>{news.title}</p><a className="text-link" href={safeUrl(news.url)} target="_blank" rel="noreferrer">Читать оригинал <ExternalLink size={14}/></a></div></div><div className="source-item"><Building2/><div><b>Профиль и агрегаты компании {companyId}</b><p>{company?.industry}</p><small>Период платежей не указан. Регион отражает регистрацию.</small></div></div>{(state?.retrieved_sources || []).map((source: Obj) => <details className="source-detail" key={source.source_id}><summary><span>{source.kind === 'bank' ? 'Альфа-Банк' : source.kind === 'metric' ? 'Платежи' : 'Новость'}</span><b>{source.title}</b><ChevronDown size={16}/></summary><small>{date(source.published_at, true)} · {source.kind === 'bank' && !citedBank.has(source.source_id) ? 'Найден при поиске, не использован в выводе' : 'Материал контекста'}</small><pre>{source.text}</pre>{safeUrl(source.url || '') && <a className="text-link" href={safeUrl(source.url)} target="_blank" rel="noreferrer">Открыть источник <ExternalLink size={14}/></a>}</details>)}</section> : !state ? <section className="panel empty-analysis"><div className="empty-icon"><Sparkles/></div><h2>Как эта новость влияет на вас?</h2><p>Подготовим разбор с учётом профиля компании, платежных связей и материалов банка. Вы получите короткий вывод и ссылки на основания.</p><Button view="primary" size={48} loading={!!busy} disabled={!boot.status.live_available} onClick={() => start('analysis')}>Подготовить разбор</Button><small>Анализ может занять несколько минут.</small>{!boot.status.live_available && <p className="muted">Новые разборы доступны после подключения базы и ключа моделей на сервере.</p>}</section> : <>
          <section className="brief-panel"><div className="eyebrow"><Sparkles size={15}/> КОРОТКО ДЛЯ ВАШЕГО БИЗНЕСА</div><p>{state.brief?.short_answer || state.result.summary}</p><div className="brief-foot"><ShieldCheck size={15}/>{state.result.status === 'supported' ? 'Есть подтверждённые основания' : 'Для персонального вывода нужны данные'}<span>{date(state.as_of)}</span></div></section>
          <section className="panel"><div className="section-icon"><Newspaper size={18}/><h2>Что произошло</h2></div><p>{state.brief?.news_summary || state.preparation?.extraction?.facts?.[0]?.text || news.text.slice(0, 350)}</p><Evidence items={state.brief?.evidence?.news_summary || state.preparation?.extraction?.facts?.[0]?.evidence} sources={sources}/></section>
          <section className="panel"><div className="section-icon"><Building2 size={18}/><h2>Почему это касается вас</h2></div><div className="context-row"><span>Основная деятельность</span><b>{company?.industry}</b></div><div className="context-row"><span>Регион регистрации</span><b>{company?.region}</b></div><div className="context-row"><span>Годовая выручка</span><b>{company && money(company.revenue_rub)}</b></div><p className="muted small">Год выручки и период платежей не указаны. Банковские услуги сами по себе не подтверждают долговую нагрузку.</p>{state.brief?.classification?.importance_reason && <div className="importance-explanation"><Badge value={state.brief.classification.importance}/><p>{state.brief.classification.importance_reason}</p><Evidence items={state.brief.evidence?.importance} sources={sources}/></div>}</section>
          {company && <Payments company={company} compact/>}<section className="panel"><div className="section-icon"><TrendingUp size={19}/><h2>Факты и возможное влияние</h2></div>{state.result.claims.map((claim: Obj, i: number) => <div className="claim" key={i}><span className={'claim-type ' + claim.kind}>{claim.kind === 'fact' ? 'ФАКТ' : 'ГИПОТЕЗА'}</span><p>{claim.text}</p><Evidence items={claim.evidence} sources={sources}/></div>)}</section>
          <section className="panel bank-panel"><div className="section-icon"><span className="mini-alfa">A</span><h2>Контекст Альфа-Банка</h2></div>{citedBank.size ? <><p className="muted">Материалы, использованные в этом разборе. Дата обзора важна: исторические выводы могут не описывать текущую ситуацию.</p>{[...citedBank].map(id => sources[id] && <details className="bank-citation" key={id}><summary><div><b>{sources[id].title}</b><small>{date(sources[id].published_at, true)}</small></div><ChevronDown size={18}/></summary>{state.result.claims.flatMap((c: Obj) => c.evidence).filter((e: Obj) => e.source_id === id).map((e: Obj, i: number) => <blockquote key={i}>«{e.quote}»</blockquote>)}</details>)}</> : <p>В выводах этого разбора нет ссылок на материалы банка. Найденные при поиске фрагменты можно проверить во вкладке «Источники».</p>}</section>
          {!!state.result.missing_data?.length && <section className="panel limitations"><div className="section-icon"><CircleHelp size={19}/><h2>Что ещё нужно уточнить</h2></div><ul>{[...new Set<string>(state.result.missing_data.map(limitationText))].map((item: string, i: number) => <li key={i}>{item}</li>)}</ul></section>}
          <div className="analysis-bottom"><span><Clock3 size={14}/> Разбор от {date(state.as_of, true)}</span><Button view="transparent" size={40} disabled={!!busy || !boot.status.live_available} onClick={() => start('analysis')} leftAddons={<RefreshCw size={15}/>}>Обновить разбор</Button></div>
        </>}
        {(busy && job?.kind !== 'chat') && <div className="progress-box" role="status"><Loader2 className="spin"/><div><b>{job?.stage || 'Запускаем анализ'}</b><p>Можно дождаться результата здесь. Разбор продолжится и при переходе в ленту.</p></div></div>}
        {jobError && <ErrorBox message={jobError}/>}
        </div><aside className={'chat-panel ' + (chatOpen ? 'chat-open' : '')}><div className="chat-heading"><div className="chat-symbol"><MessageSquare size={19}/></div><div><b>Обсудим новость</b><small>В контексте вашей компании</small></div><button className="icon-button chat-close" aria-label="Закрыть чат" onClick={() => setChatOpen(false)}><X size={20}/></button></div><div className="chat-body"><div className="chat-intro"><div className="eyebrow">{shortIndustry(company)} · {companyId}</div><h3>От события — к пониманию</h3><p>Уточните, что новость означает для бизнеса. Ответ будет опираться на материалы этого разбора.</p></div>{messages.map((message, i) => <div key={i} className={'message ' + message.role}><small>{message.role === 'user' ? 'Вы' : 'Аналитик'}</small><p>{message.text}</p>{message.claims && <Evidence items={message.claims.flatMap(c => c.evidence)} sources={sources}/>}</div>)}{busy && job?.kind === 'chat' && <div className="chat-thinking" role="status"><Loader2 className="spin" size={16}/>Проверяем основания…</div>}{jobError && <ErrorBox message={jobError}/>}<div ref={chatEnd}/></div>{!messages.length && <div className="suggestions">{['Почему это касается нашей компании?', 'Какие данные стоит проверить?', 'Что говорят материалы банка?'].map(text => <button key={text} disabled={!state || !!busy || !boot.status.live_available} onClick={() => { setChatOpen(true); start('chat', text); }}>{text}<ArrowUpRight size={15}/></button>)}</div>}<form className="chat-form" onSubmit={e => { e.preventDefault(); start('chat'); }}><label className="sr-only" htmlFor="question">Вопрос по новости</label><textarea id="question" placeholder={state ? 'Спросите об этой новости…' : 'Сначала подготовьте разбор'} value={question} onChange={e => setQuestion(e.target.value)} maxLength={1500} disabled={!state || !boot.status.live_available} rows={2} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start('chat'); } }}/><button type="submit" aria-label="Отправить вопрос" disabled={!question.trim() || !!busy || !state || !boot.status.live_available}><Send size={18}/></button></form><small className="chat-disclaimer">Ответы требуют проверки перед принятием решений.</small></aside></div>
        <button className="mobile-chat-button" onClick={() => setChatOpen(true)}><MessageSquare size={19}/>Обсудить новость<ArrowUpRight size={18}/></button>
        </>}
      </> : section === 'feed' ? <>
        <div className="page-kicker"><span><span className="status-dot green"/>ПЕРСОНАЛЬНАЯ ЛЕНТА</span><span>Набор на {date(boot.status.updated_at, true)}</span></div>
        <div className="hero"><div className="hero-copy"><h1>События рынка.<br/><span>Контекст вашего бизнеса.</span></h1><p>Важные новости, их влияние на вашу компанию<br className="desktop-break"/> и основания для решений — в одном месте.</p><div className="hero-profile"><span><Building2 size={15}/>{shortIndustry(company)}</span><i/><span><MapPin size={15}/>{company?.region}</span></div></div><button className="hero-insight" onClick={() => featured && setSelectedId(featured.id)} disabled={!featured}><div className="hero-insight-top"><span className="insight-symbol"><Sparkles size={21}/></span><span>СЕЙЧАС В ФОКУСЕ</span><ArrowUpRight size={22}/></div><h2>{featured ? primaryTopic(featured) : 'Персональная аналитика'}</h2><p>{featured?.brief?.short_answer || 'Откройте новость, чтобы подготовить разбор влияния на ваш бизнес.'}</p><div className="hero-insight-bottom"><span>Читать разбор</span><ArrowRight size={18}/></div></button></div>
        <div className="section-heading"><div><h2>Ваша новостная повестка</h2><p>Подбор с учётом деятельности и связей компании</p></div><button aria-label="Обновить ленту" className="refresh-button" onClick={() => { loadBoot(); setReload(v => v + 1); }} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''}/><span>Обновить</span></button></div>
        <div className="feed-controls"><div className="segmented" role="tablist" aria-label="Лента новостей">{[['personal', 'Для вас'], ['all', 'Все новости'], ['saved', 'Сохранённое']].map(([key, label]) => <button key={key} role="tab" aria-selected={mode === key} onClick={() => setMode(key)}>{key === 'saved' && <Bookmark size={14}/>} {label}{key === 'all' && <span>{feed?.items.length || '—'}</span>}</button>)}</div><label className="search-field"><Search size={18}/><input placeholder="Поиск по новостям" aria-label="Поиск по новостям" value={query} onChange={e => setQuery(e.target.value)}/>{query && <button aria-label="Очистить поиск" onClick={() => setQuery('')}><X size={16}/></button>}</label></div>
        <div className="filter-row"><SlidersHorizontal size={16}/><select aria-label="Фильтр по теме" value={topic} onChange={e => setTopic(e.target.value)}><option value="all">Все темы</option>{availableTopics.map(t => <option key={t} value={t}>{topics[t] || t}</option>)}</select><select aria-label="Фильтр по важности" value={level} onChange={e => setLevel(e.target.value)}><option value="all">Любая важность</option><option value="high">Высокая</option><option value="medium">Средняя</option><option value="low">Низкая</option><option value="ready">С готовым разбором</option></select>{(topic !== 'all' || level !== 'all' || query) && <button className="reset" onClick={() => { setTopic('all'); setLevel('all'); setQuery(''); }}>Сбросить <X size={12}/></button>}<span className="result-count">{filtered.length} публикаций</span></div>
        {feedError ? <ErrorBox message={feedError} retry={() => setReload(v => v + 1)}/> : loading ? <Skeleton/> : !filtered.length ? <div className="empty-state"><Search size={28}/><h3>{mode === 'saved' ? 'Здесь будут сохранённые новости' : 'По вашему запросу ничего не найдено'}</h3><p>{mode === 'saved' ? 'Нажмите на закладку у новости, чтобы вернуться к ней позже.' : 'Попробуйте другие слова или сбросьте фильтры.'}</p><Button view="secondary" size={40} onClick={() => { setQuery(''); setTopic('all'); setLevel('all'); setMode('personal'); }}>Вернуться к подборке</Button></div> : <div className="news-grid">{filtered.slice(0, visibleCount).map((card, i) => <article className={'news-card ' + (i === 0 && mode === 'personal' ? 'lead-card' : '')} key={card.id}><div className="card-top"><Badge value={card.classification.importance}/><button className={'icon-button ' + (pairSaved(card.id) ? 'saved' : '')} aria-label={pairSaved(card.id) ? 'Убрать из сохранённого' : 'Сохранить новость'} onClick={() => toggle(companyId + ':' + card.id)}><Bookmark size={18} fill={pairSaved(card.id) ? 'currentColor' : 'none'}/></button></div><div className="card-topic">{primaryTopic(card)}{card.has_analysis && <span><CheckCheck size={13}/>Разбор готов</span>}</div><h3><button onClick={() => setSelectedId(card.id)}>{card.title}</button></h3><p className="card-summary">{card.brief?.news_summary || card.text}</p>{card.brief?.short_answer && <div className="card-effect"><span>ДЛЯ ВАШЕГО БИЗНЕСА</span><p>{card.brief.short_answer}</p></div>}<div className="card-bottom"><div className="news-meta"><span className="publisher-dot">{card.publisher[0]}</span><span>{card.publisher}</span><span>·</span><span>{date(card.published_at)}</span></div><button className="card-link" onClick={() => setSelectedId(card.id)}>{card.has_analysis ? 'Открыть разбор' : 'Подробнее'}<ArrowRight size={17}/></button></div></article>)}</div>}
        {filtered.length > visibleCount && <div className="show-more"><Button view="secondary" size={48} onClick={() => setVisibleCount(n => n + 8)}>Показать ещё {Math.min(8, filtered.length - visibleCount)} <ChevronDown size={16}/></Button></div>}
        <div className="feed-footnote"><ShieldCheck size={16}/><p>Подбор на {feed?.matching_as_of || '22.10.2026'}. Важность оценивается для выбранной компании после разбора; до него метка отсутствует. Сходство публикаций само по себе не доказывает влияние.</p></div>
      </> : section === 'bank' ? <>
        <div className="page-kicker"><span>ИССЛЕДОВАНИЯ И ОБЗОРЫ</span><span>Альфа-Банк</span></div><div className="page-heading"><h1>Больше контекста.<br/><span>Точнее решения.</span></h1><p>Материалы банка, которые помогают понять события рынка.</p></div><div className="bank-summary"><div><b>{boot.documents.length}</b><span>материалов в базе</span></div><div><b>{bankSources.length}</b><span>фрагментов в готовых разборах</span></div><div className="bank-summary-note"><ShieldCheck size={23}/><p>В разбор попадают только найденные основания. Дата и источник сохраняются.</p></div></div><label className="search-field bank-search"><Search size={18}/><input aria-label="Поиск материалов банка" placeholder="Найти обзор: ставка, потребление, инфляция…" value={bankQuery} onChange={e => setBankQuery(e.target.value)}/>{bankQuery && <button aria-label="Очистить поиск материалов" onClick={() => setBankQuery('')}><X size={16}/></button>}</label>{bankError && <ErrorBox message={bankError}/>}
        <div className="document-grid">{boot.documents.filter(d => (d.title + ' ' + (d.subtitle || '') + ' ' + d.tags.join(' ')).toLowerCase().includes(bankQuery.toLowerCase())).map(doc => <article className="document-card" key={doc.id}><div className="document-top"><div className="document-icon"><FileText size={24}/></div><span>{date(doc.published_at, true)}</span></div><div className="document-tags">{doc.tags.slice(0, 2).map((t: string) => <span key={t}>{t}</span>)}</div><h2>{doc.title}</h2><p>{doc.subtitle || 'Аналитический обзор Альфа-Банка'}</p><div className="document-footer"><span>{docSources(doc).length ? 'Есть фрагменты в разборах' : 'Включён в поисковую базу'}</span><button className="icon-button" aria-label={'Подробнее: ' + doc.title} aria-expanded={expandedDoc === doc.id} onClick={() => setExpandedDoc(expandedDoc === doc.id ? undefined : doc.id)}>{expandedDoc === doc.id ? <X size={18}/> : <ArrowUpRight size={20}/>}</button></div>{expandedDoc === doc.id && <div className="document-excerpts"><small>{doc.source_name}</small>{documentError ? <ErrorBox message={documentError}/> : !documentData ? <p className="document-loading"><Loader2 className="spin" size={15}/>Загружаем текст…</p> : documentData.chunks.length ? <><p>{documentData.chunks.length} текстовых фрагментов · извлечено из PDF</p><div className="document-scroll">{documentData.chunks.map((chunk: Obj, i: number) => <details key={chunk.id}><summary><span>{chunk.section_path?.filter(Boolean).join(" / ") || "Фрагмент " + (i + 1)}{chunk.pages?.length ? " · стр. " + chunk.pages.join(", ") : ""}</span><ChevronDown size={14}/></summary><pre>{chunk.text}</pre></details>)}</div><p className="small muted">Распознанный текст может содержать ошибки OCR. Данные графиков и таблиц требуют сверки с оригиналом.</p></> : docSources(doc).length ? docSources(doc).map(source => <details key={source.source_id}><summary>{source.title}<ChevronDown size={14}/></summary><pre>{source.text}</pre></details>) : <p>Текст материала сейчас недоступен. Проверьте подключение базы.</p>}</div>}</article>)}</div>{!boot.documents.some(d => (d.title + ' ' + (d.subtitle || '') + ' ' + d.tags.join(' ')).toLowerCase().includes(bankQuery.toLowerCase())) && <div className="empty-state"><Search/><h3>Материал не найден</h3><p>Попробуйте другую тему.</p></div>}<div className="feed-footnote"><CircleHelp size={17}/><p>Обзоры отражают позицию на дату публикации. Поиск здесь фильтрует каталог; новые разборы ищут контекст по всей загруженной базе фрагментов.</p></div>
      </> : <>
        <div className="page-kicker"><span>ПРОФИЛЬ ДЛЯ ПЕРСОНАЛИЗАЦИИ</span><span>{companyId}</span></div><div className="page-heading"><h1>Контекст<br/><span>вашей компании.</span></h1><p>Эти данные используются при подборе и разборе новостей.</p></div>{company && <div className="profile-grid"><section className="panel company-profile"><div className="company-big-icon"><Building2 size={30}/></div><span className="eyebrow">КОМПАНИЯ {company.id}</span><h2>{shortIndustry(company)}</h2><p>{company.industry}</p><div className="context-row"><span>ОКВЭД</span><b>{company.okved}</b></div><div className="context-row"><span>Регион регистрации</span><b>{company.region}</b></div><div className="context-row"><span>Годовая выручка</span><b>{money(company.revenue_rub)}</b></div><div className="context-row"><span>Стадия бизнеса</span><b>{company.stage || 'Не указана'}</b></div><p className="muted small">Юридические названия не переданы. Для выбора используется идентификатор из набора компаний.</p></section><div><section className="panel"><div className="section-icon"><Wallet size={20}/><h2>Банковские сервисы</h2></div><div className="service-tags">{company.services.map(s => <span key={s}><Check size={14}/>{serviceNames[s] || s}</span>)}</div></section><section className="panel"><div className="section-icon"><MapPin size={20}/><h2>Внешнеторговые связи</h2></div><p>{company.countries.length ? company.countries.map(s => s.charAt(0) + s.slice(1).toLowerCase()).join(' · ') : 'Страны не указаны'}</p><p className="muted small">Направление торговли и объёмы не установлены.</p></section><section className="panel profile-limits"><h2>Что учитывать</h2><p>Год выручки и период агрегатов платежей не указаны. Регистрация не определяет место деятельности. Платежная связь не доказывает роль поставщика или покупателя.</p></section></div><Payments company={company}/></div>}
      </>}
      </main><footer className="site-footer"><span>Альфа-Бизнес · Персональная аналитика</span><span>Факты. Контекст. Решения.</span></footer>
    </div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
