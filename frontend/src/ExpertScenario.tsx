import { Radio, Play, RefreshCw, X, CheckCheck, CopyCheck } from 'lucide-react';

type Props = { companyCount: number; session?: Record<string, any>; busy: boolean; error: string; onStart: () => void; onStop: () => void; onRetry: () => void };
const phases: Record<string, string> = {
  scheduled: 'Ожидает поступления', received: 'Получена · в очереди', ingesting: 'Проверка дублей и сохранение',
  embedding: 'Расчёт эмбеддинга', classifying: 'Классификация моделью', matching: 'Подбор компаний',
  matched: 'Компании подобраны', assessing: 'Оценка важности моделью', analyzing: 'Полный разбор моделью',
  ready: 'Разбор сохранён в БД', not_matched: 'Не подобрана к текущей компании',
  not_business: 'Не относится к деловым новостям', failed: 'Ошибка обработки', duplicate: 'Дубль пропущен',
};

export function ExpertScenario({ companyCount, session, busy, error, onStart, onStop, onRetry }: Props) {
  return <section className="expert-scenario" aria-label="Сценарий для эксперта">
    <div className="expert-heading"><div><Radio size={20}/><h2>Лента в реальном времени</h2></div><span className="demo-label">Тестовый сценарий</span></div>
    <p>Общий сценарий для всех {companyCount} компаний: по две вымышленные новости о каждой, контрольная публикация и один повтор. Можно переключать профили — поток продолжает работать. Дедупликация, подбор, важность и разбор рассчитываются моделями и сохраняются в БД.</p>
    {session && <><div className="expert-counters" aria-live="polite"><span>Поступило <b>{session.received || 0}/{session.expected_received || 0}</b></span><span>Обработано <b>{session.processed || 0}/{session.expected_unique || 0}</b></span><span>Разборов в БД <b>{session.analyses || 0}</b></span><span>Дублей <b>{session.duplicates || 0}</b></span><strong>{session.status === 'done' ? 'Сценарий завершён' : session.status === 'failed' ? 'Есть ошибки обработки' : `${session.elapsed_seconds || 0} с · идёт обработка`}</strong></div>
      <ol className="expert-timeline">{session.timeline?.map((entry: Record<string, any>, i: number) => <li className={entry.phase} key={i}><span>{entry.phase === 'ready' ? <CheckCheck size={16}/> : entry.phase === 'duplicate' ? <CopyCheck size={16}/> : <i/>}</span><div><b>{entry.title.replace(/^ТЕСТ: /, '')}</b><small>{entry.stage || phases[entry.phase]}</small></div></li>)}</ol></>}
    {error && <p className="expert-error" role="alert">{error}</p>}
    <div className="expert-actions"><button className="expert-start" disabled={busy} onClick={onStart}>{session ? <RefreshCw size={16}/> : <Play size={16}/>} {busy ? 'Подготовка…' : session ? 'Повторить общий сценарий' : 'Запустить сценарий'}</button>{!!session?.failed && <button disabled={busy} onClick={onRetry}><RefreshCw size={16}/>Повторить ошибки · {session.failed}</button>}<button disabled={busy} onClick={onStop}><X size={16}/>{session ? 'Завершить общий сценарий' : 'Закрыть'}</button></div>
  </section>;
}
