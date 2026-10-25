import { useEffect, useRef, useState } from 'react';
import { ThumbsDown, ThumbsUp, Loader2 } from 'lucide-react';

type Props = { companyId: string; newsId: string; version: string; demoId?: string; isDemo?: boolean };

export function AnalysisFeedback({ companyId, newsId, version, demoId, isDemo }: Props) {
  const [vote, setVote] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [retry, setRetry] = useState(0);
  const identity = `${companyId}:${newsId}:${version}:${demoId || ''}`;
  const current = useRef(identity);
  current.current = identity;
  useEffect(() => {
    const controller = new AbortController();
    setVote(null); setMessage(''); setError(''); setLoading(true); setSaving(false);
    const query = new URLSearchParams({ company_id: companyId, news_id: newsId, analysis_version: version });
    if (demoId) query.set('demo_id', demoId);
    fetch('/api/feedback?' + query, { signal: controller.signal }).then(async response => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Оценки временно недоступны');
      if (!controller.signal.aborted) setVote(body.vote);
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [companyId, newsId, version, demoId, retry]);

  async function save(value: number) {
    if (loading || saving || error) return;
    const requestIdentity = identity;
    const next = vote === value ? null : value;
    setSaving(true); setError(''); setMessage('');
    try {
      const response = await fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: companyId, news_id: newsId, analysis_version: version, vote: next, ...(demoId ? { demo_id: demoId } : {}) }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Не удалось сохранить оценку');
      if (current.current !== requestIdentity) return;
      setVote(body.vote); setMessage(body.vote === null ? 'Оценка удалена.' : 'Спасибо! Оценка сохранена.');
    } catch (e: any) { if (current.current === requestIdentity) setError(e.message); }
    finally { if (current.current === requestIdentity) setSaving(false); }
  }
  return <section className="panel analysis-feedback" aria-label="Оценка разбора">
    <div><h2>Был ли разбор полезен?</h2><p>{isDemo ? 'Оценка тестового сценария учитывается отдельно.' : 'Ваш отзыв помогает оценивать качество разборов.'}</p></div>
    <div className="feedback-actions"><button aria-pressed={vote === 1} disabled={loading || saving || !!error} onClick={() => save(1)}><ThumbsUp size={18}/>Полезно</button><button aria-pressed={vote === -1} disabled={loading || saving || !!error} onClick={() => save(-1)}><ThumbsDown size={18}/>Не полезно</button>{(loading || saving) && <Loader2 className="spin" size={16} aria-label="Сохранение оценки"/>}</div>
    <div className="feedback-status" aria-live="polite">{error ? <span role="alert">{error} <button onClick={() => setRetry(v => v + 1)}>Повторить</button></span> : message || (vote !== null ? 'Ваша оценка сохранена. Нажмите ещё раз, чтобы убрать её.' : '')}</div>
  </section>;
}
