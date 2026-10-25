import { Radio, Play, RefreshCw, X, CheckCheck, CopyCheck } from 'lucide-react';

type Props = { session?: Record<string, any>; busy: boolean; error: string; onStart: () => void; onStop: () => void };
const phases: Record<string, string> = {
  scheduled: 'Ожидает поступления', received: 'Получена · в очереди', ingesting: 'Проверка дублей и сохранение',
  embedding: 'Расчёт эмбеддинга', classifying: 'Классификация моделью', matching: 'Подбор компаний',
  matched: 'Компании подобраны', assessing: 'Оценка важности моделью', analyzing: 'Полный разбор моделью',
  ready: 'Разбор сохранён в БД', not_matched: 'Не подобрана к текущей компании',
  not_business: 'Не относится к деловым новостям', failed: 'Ошибка обработки', duplicate: 'Дубль пропущен',
};

export function ExpertScenario({ session, busy, error, onStart, onStop }: Props) {
  return <section className="expert-scenario" aria-label="Сценарий для эксперта">
    <div className="expert-heading"><div><Radio size={20}/><h2>Лента в реальном времени</h2></div><span className="demo-label">Тестовый сценарий</span></div>
    <p>За 26 секунд поступят три вымышленные новости и один повтор. Дедупликация, эмбеддинги, подбор компаний, оценка важности и полный разбор выполняются реально. Результаты сохраняются в БД; обработка моделями может занять несколько минут.</p>
    {session && <><div className="expert-counters" aria-live="polite"><span>Поступило <b>{session.received || 0}/4</b></span><span>Обработано <b>{session.processed || 0}/3</b></span><span>Разборов в БД <b>{session.analyses || 0}</b></span><span>Дублей <b>{session.duplicates || 0}</b></span><strong>{session.status === 'done' ? 'Сценарий завершён' : session.status === 'failed' ? 'Есть ошибки обработки' : `${session.elapsed_seconds || 0} с · идёт обработка`}</strong></div>
      <ol className="expert-timeline">{session.timeline?.map((entry: Record<string, any>, i: number) => <li className={entry.phase} key={i}><span>{entry.phase === 'ready' ? <CheckCheck size={16}/> : entry.phase === 'duplicate' ? <CopyCheck size={16}/> : <i/>}</span><div><b>{entry.title.replace(/^ТЕСТ: /, '')}</b><small>{entry.stage || phases[entry.phase]}</small></div></li>)}</ol></>}
    {error && <p className="expert-error" role="alert">{error}</p>}
    <div className="expert-actions"><button className="expert-start" disabled={busy} onClick={onStart}>{session ? <RefreshCw size={16}/> : <Play size={16}/>} {busy ? 'Подготовка…' : session ? 'Повторить сценарий' : 'Запустить сценарий'}</button><button disabled={busy} onClick={onStop}><X size={16}/>{session ? 'Завершить и убрать тестовые новости' : 'Закрыть'}</button></div>
  </section>;
}
