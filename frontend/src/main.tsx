import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button } from "@alfalab/core-components-button";
import "@alfalab/core-components-vars/index.css";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  ExternalLink,
  FileText,
  Layers3,
  Loader2,
  MapPin,
  MessageSquare,
  Newspaper,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TrendingUp,
  Wallet,
  X,
} from "lucide-react";
import "./style.css";
import { ExpertScenario } from "./ExpertScenario";
import { AnalysisFeedback } from "./AnalysisFeedback";

type Obj = Record<string, any>;
type Company = {
  id: string;
  industry: string;
  okved: string;
  region: string;
  revenue_rub: number;
  services: string[];
  countries: string[];
  stage: string;
  payments: Obj;
  profile_id: string;
};
type BusinessProfile = {
  id: string;
  title: string;
  description: string;
  initial: string;
  color: string;
  company_ids: string[];
  analysis_count?: number;
};
type Card = {
  id: string;
  title: string;
  text: string;
  url: string;
  published_at: string;
  publisher: string;
  classification: Obj;
  has_analysis: boolean;
  brief?: Obj;
  short_answer?: string;
  analysis_status?: string;
  match_reasons: Obj[];
  retrieval_channels: string[];
  link?: Obj;
  is_demo?: boolean;
  demo_phase?: string;
  demo_stage?: string;
};
type Bootstrap = {
  companies: Company[];
  profiles: BusinessProfile[];
  documents: Obj[];
  status: Obj;
};
type Message = {
  role: "user" | "assistant";
  text: string;
  claims?: Obj[];
  sources?: Obj[];
  retrieval?: Obj;
};
const topics: Record<string, string> = {
  electronics: "Электроника",
  wholesale_trade: "Оптовая торговля",
  financial_markets: "Финансы",
  regulation: "Регулирование",
  automotive: "Автобизнес",
  energy: "Энергетика",
  logistics: "Логистика",
  retail_ecommerce: "Торговля",
  metallurgy: "Металлургия",
  other_business: "Экономика",
  not_business: "Вне бизнеса",
  real_estate: "Недвижимость",
  construction: "Строительство",
  agriculture: "Сельское хозяйство",
  technology: "Технологии",
};
const serviceNames: Record<string, string> = {
  cash_settlement_rko: "Расчётный счёт",
  bank_guarantees: "Банковские гарантии",
  loans: "Кредитование",
  credit: "Кредитование",
  leasing: "Лизинг",
  deposits: "Депозиты",
  deposit: "Депозиты",
  salary_project: "Зарплатный проект",
  payroll: "Зарплатный проект",
  factoring: "Факторинг",
  cash_register: "Эквайринг",
};
const importance: Record<string, string> = {
  high: "Высокая важность",
  medium: "Средняя важность",
  low: "Низкая важность",
};
const shortIndustry = (c?: Company) =>
  c
    ? c.okved.startsWith("45")
      ? "Автозапчасти"
      : c.okved.startsWith("46.43")
        ? "Бытовая техника"
        : c.okved.startsWith("52")
          ? "Логистика"
          : c.okved.startsWith("68")
            ? "Недвижимость"
            : "Торговля"
    : "";
const date = (value?: string, long = false) =>
  value
    ? new Date(value).toLocaleDateString("ru-RU", {
        day: "numeric",
        month: long ? "long" : "short",
        ...(long ? { year: "numeric" } : {}),
      })
    : "Дата не указана";
const money = (n: number) =>
  new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(n) + " ₽";
const safeUrl = (url: string) => {
  try {
    const u = new URL(url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
};
const limitationText = (value: string) =>
  value.includes("model_unavailable")
    ? "Модель дополнительного поиска не завершила запрос. Разбор основан на материалах, полученных до остановки."
    : value.startsWith("Сбор контекста остановлен:")
      ? "Дополнительный контекст собран в пределах доступного лимита. Часть вопросов может требовать отдельной проверки."
      : value.startsWith("Ограничение получения контекста:")
        ? "Не все дополнительные материалы удалось получить. Это ограничивает полноту разбора."
        : value;
async function api<T = Obj>(
  path: string,
  data?: Obj,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api" + path, {
    signal,
    ...(data
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }
      : {}),
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(body.error || "Не удалось выполнить запрос");
  return body;
}
function useBookmarks() {
  const [saved, setSaved] = useState<string[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem("alfa-saved-v1") || "[]");
      return Array.isArray(value)
        ? value.filter((v) => typeof v === "string")
        : [];
    } catch {
      return [];
    }
  });
  const toggle = (id: string) =>
    setSaved((old) => {
      const next = old.includes(id)
        ? old.filter((v) => v !== id)
        : [...old, id];
      try {
        localStorage.setItem("alfa-saved-v1", JSON.stringify(next));
      } catch {}
      return next;
    });
  return { saved, toggle };
}
function Badge({ value, status }: { value?: string; status?: string }) {
  return (
    <span className={"badge " + (value || "unknown")}>
      <i />
      {importance[value || ""] ||
        (status === "pending"
          ? "Оцениваем важность…"
          : status === "failed"
            ? "Оценка временно недоступна"
            : "Не оценено для компании")}
    </span>
  );
}
function Logo() {
  return (
    <div className="brand">
      <div className="alfa-mark" aria-hidden="true">
        A<span />
      </div>
      <div>
        Альфа-Бизнес<small>Аналитика для бизнеса</small>
      </div>
    </div>
  );
}
function ErrorBox({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <CircleHelp size={20} />
      <div>
        {message}
        {retry && <button onClick={retry}>Повторить</button>}
      </div>
    </div>
  );
}
function Skeleton() {
  return (
    <div className="skeleton-list" aria-label="Загрузка новостей">
      {[0, 1, 2, 3].map((i) => (
        <div className="skeleton" key={i}>
          <i />
          <i />
          <i />
          <i />
        </div>
      ))}
    </div>
  );
}
const evidenceFieldLabels: Record<string, string> = {
  okved_class: "ОКВЭД",
  okved_code: "ОКВЭД",
  okved_name: "Вид деятельности",
  counterparties_count: "Контрагентов",
  amount_rub: "Сумма",
  share_pct: "Доля",
  unique_count: "Уникальных контрагентов",
  top_1_share_pct: "Доля крупнейшего",
  top_3_share_pct: "Доля топ-3",
  hhi: "Индекс HHI",
  incoming_amount_rub: "Поступления",
  outgoing_amount_rub: "Списания",
  turnover_rub: "Оборот",
  incoming_payments_count: "Входящих платежей",
  outgoing_payments_count: "Исходящих платежей",
  edges_count: "Связей",
  unique_counterparties_count: "Уникальных контрагентов",
  external_counterparties_count: "Внешних контрагентов",
  intragroup_counterparties_count: "Внутригрупповых контрагентов",
  intragroup_amount_rub: "Сумма внутри группы",
  intragroup_share_pct: "Доля внутри группы",
  average_edge_amount_rub: "Средний платёж",
  region: "Регион",
  city: "Город",
  is_intragroup: "Внутригрупповая",
};
function formatEvidenceQuote(quote: string, sourceId: string): string {
  const text = String(quote ?? "").trim();
  if (!text) return text;
  const field = sourceId.split(":").slice(2).join(":");

  if (field === "banking_services") {
    const tokens = text
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (tokens.length && tokens.every((item) => serviceNames[item]))
      return tokens.map((item) => serviceNames[item]).join(", ");
  }

  const formatValue = (key: string, value: unknown): string | null => {
    if (value === null || value === undefined) return null;
    if (Array.isArray(value)) {
      return value
        .map((item) => {
          if (typeof item === "string")
            return field === "banking_services"
              ? serviceNames[item] || item
              : item;
          if (typeof item === "object" && item !== null)
            return Object.values(item as Record<string, unknown>)
              .filter((part) => typeof part === "string")
              .join(" ");
          return String(item);
        })
        .join(", ");
    }
    if (typeof value === "boolean") return value ? "да" : "нет";
    const isMoney = key.endsWith("_rub") || field === "annual_revenue_rub";
    const isPercent = key.endsWith("_pct");
    const isOkved = key.startsWith("okved") || field.startsWith("okved");
    if (typeof value === "number") {
      if (isOkved) return String(value);
      if (isMoney) return money(value);
      if (isPercent) return `${value.toLocaleString("ru-RU")}%`;
      return value.toLocaleString("ru-RU");
    }
    if (typeof value === "string") {
      if (isOkved) return value;
      if (isMoney && value.trim() !== "" && Number.isFinite(Number(value)))
        return money(Number(value));
      if (isPercent && value.trim() !== "" && Number.isFinite(Number(value)))
        return `${Number(value).toLocaleString("ru-RU")}%`;
      return field === "banking_services" ? serviceNames[value] || value : value;
    }
    return null;
  };

  const formatEntries = (entries: Array<[string, unknown]>): string => {
    const seen = new Set<string>();
    const parts: string[] = [];
    for (const [key, value] of entries) {
      const label = evidenceFieldLabels[key];
      if (!label) continue;
      const formatted = formatValue(key, value);
      if (formatted === null) continue;
      const part = `${label}: ${formatted}`;
      if (!seen.has(part)) {
        seen.add(part);
        parts.push(part);
      }
    }
    return parts.join(" · ");
  };

  // Extract scalar key/value pairs. This works for broken and deeply nested
  // fragments such as `{"top_okved": [{"okved_class": "56", ...` that the
  // backend can produce when a quote is truncated.
  const pairs: Array<[string, unknown]> = [];
  const pairPattern =
    /([a-z0-9_]+)"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)/gi;
  for (const match of text.matchAll(pairPattern)) {
    const key = match[1];
    if (!evidenceFieldLabels[key]) continue;
    const raw = match[2];
    let value: unknown = raw;
    try {
      value = JSON.parse(raw);
    } catch {
      if (/^-?\d+(?:\.\d+)?$/.test(raw)) value = Number(raw);
      else if (raw === "true") value = true;
      else if (raw === "false") value = false;
      else if (raw === "null") value = null;
    }
    pairs.push([key, value]);
  }
  const pairText = formatEntries(pairs);
  if (pairText) return pairText;

  let parsed: unknown;
  for (const candidate of [text, `{${text}}`, `{"${text}}`]) {
    try {
      parsed = JSON.parse(candidate);
      break;
    } catch {
      parsed = undefined;
    }
  }
  if (parsed === undefined) return text;
  if (Array.isArray(parsed)) return formatValue(field, parsed) ?? text;
  if (parsed !== null && typeof parsed === "object")
    return (
      formatEntries(Object.entries(parsed as Record<string, unknown>)) || text
    );
  return formatValue(field, parsed) ?? text;
}
function Evidence({
  items,
  sources,
}: {
  items: Obj[];
  sources: Record<string, Obj>;
}) {
  if (!items?.length) return null;
  return (
    <details className="evidence">
      <summary>
        <ShieldCheck size={14} /> Основания · {items.length}
        <ChevronDown size={14} />
      </summary>
      <div>
        {items.map((e, i) => {
          const source = sources[e.source_id];
          const isNews =
            e.source_id.startsWith("news:") || source?.kind === "news";
          const isData =
            e.source_id.startsWith("company:") ||
            e.source_id.startsWith("metric:");
          const quote = isData
            ? formatEvidenceQuote(e.quote, e.source_id)
            : e.quote;
          const href =
            source && source.kind === "news"
              ? safeUrl(source.url || "")
              : undefined;
          const label = isNews
            ? "Текст новости"
            : e.source_id.startsWith("company:")
              ? "Профиль компании"
              : e.source_id.startsWith("metric:")
                ? "Агрегаты платежей"
                : source?.title || "Исходная новость";
          return (
            <blockquote key={i}>
              <p>«{quote}»</p>
              <small>
                {href ? (
                  <a
                    className="evidence-link"
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {label}
                    <ExternalLink size={12} />
                  </a>
                ) : (
                  label
                )}
              </small>
            </blockquote>
          );
        })}
      </div>
    </details>
  );
}

function ChatSources({
  message,
  sources,
}: {
  message: Message;
  sources: Record<string, Obj>;
}) {
  const registry = {
    ...sources,
    ...Object.fromEntries((message.sources || []).map((s) => [s.source_id, s])),
  };
  const fresh = new Set<string>(message.retrieval?.fresh_source_ids || []);
  const found = (message.sources || []).filter(
    (s) => fresh.has(s.source_id) && s.kind !== "metric",
  );
  const unavailable = message.retrieval?.trace?.some(
    (entry: Obj) => entry.status === "unavailable",
  );
  return (
    <>
      <Evidence
        items={message.claims?.flatMap((c) => c.evidence) || []}
        sources={registry}
      />
      {message.retrieval && (
        <div className="chat-retrieval">
          <small>
            <Search size={12} />
            {found.length
              ? `Найдено материалов: ${found.length}`
              : "Новых материалов по вопросу не найдено"}
          </small>
          {unavailable && <p>Часть источников поиска сейчас недоступна.</p>}
          {message.retrieval.stop &&
            message.retrieval.stop !== "model_finished" && (
              <p>
                Уточнение поиска завершено не полностью. Ответ опирается на
                доступные материалы.
              </p>
            )}
          {found.length > 0 && (
            <details>
              <summary>
                Материалы поиска
                <ChevronDown size={13} />
              </summary>
              {found.map((source) => (
                <div className="chat-source" key={source.source_id}>
                  <b>{source.title}</b>
                  <small>
                    {source.kind === "bank"
                      ? "Материал банка"
                      : source.publisher || "Новость"}{" "}
                    · {date(source.published_at, true)}
                  </small>
                  <details>
                    <summary>Посмотреть фрагмент</summary>
                    <pre>{source.text}</pre>
                  </details>
                  {safeUrl(source.url || "") && (
                    <a
                      className="text-link"
                      href={safeUrl(source.url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Открыть публикацию <ExternalLink size={12} />
                    </a>
                  )}
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </>
  );
}

function BankDigestText({ item }: { item: Obj }) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = item.full_text && item.full_text !== item.text;
  return (
    <div className="bank-digest-text">
      <p>{expanded && canExpand ? item.full_text : item.text}</p>
      {canExpand && (
        <button type="button" className="bank-digest-toggle" aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}>
          {expanded ? "Свернуть" : "Показать полностью"}
        </button>
      )}
    </div>
  );
}

function BankDigest({
  summary,
  sources,
}: {
  summary?: Obj;
  sources: Record<string, Obj>;
}) {
  if (!summary?.highlights?.length) return null;
  const attribution = (item: Obj) =>
    item.source_ids
      .map((id: string) =>
        sources[id]
          ? `${sources[id].title} · ${date(sources[id].published_at, true)}`
          : "",
      )
      .filter(Boolean)
      .join(" · ");
  return (
    <div className="bank-digest">
      <div className="eyebrow">КРАТКАЯ ВЫЖИМКА</div>
      {summary.highlights.map((item: Obj, index: number) => (
        <div className="bank-digest-point" key={index}>
          <BankDigestText key={item.full_text || item.text} item={item} />
          <small>
            {item.method === "excerpt"
              ? "Выдержка из материала"
              : "Из выводов разбора"}{" "}
            · {attribution(item)}
          </small>
          <Evidence items={item.evidence || []} sources={sources} />
        </div>
      ))}
      {summary.impact ? (
        <div className="bank-digest-impact">
          <b>Возможное значение для компании</b>
          <BankDigestText key={summary.impact.full_text || summary.impact.text} item={summary.impact} />
          <Evidence items={summary.impact.evidence || []} sources={sources} />
        </div>
      ) : (
        <p className="muted small bank-digest-note">{summary.note}</p>
      )}
    </div>
  );
}

function BankContext({ state, context }: { state: Obj; context?: Obj }) {
  const cited = new Set<string>(
    (state.result?.claims || [])
      .flatMap((c: Obj) => c.evidence || [])
      .map((e: Obj) => e.source_id),
  );
  const found = (state.retrieved_sources || [])
    .filter((s: Obj) => s.kind === "bank")
    .sort(
      (a: Obj, b: Obj) =>
        Number(cited.has(b.source_id)) - Number(cited.has(a.source_id)),
    );
  const used = found.filter((s: Obj) => cited.has(s.source_id)).length;
  const registry = Object.fromEntries(
    found.map((source: Obj) => [source.source_id, source]),
  );
  const empty: Record<string, string> = {
    unavailable:
      "Не удалось получить материалы банка из базы. Обновите разбор после восстановления подключения.",
    incomplete:
      "Поиск банковского контекста не завершён. Обновите разбор, чтобы повторить поиск.",
    not_found:
      "По запросам этого разбора банковские материалы не найдены. Это не подтверждает отсутствие рисков для компании.",
    not_searched:
      "В сохранённом разборе банковский контекст не был получен. Обновите разбор, чтобы выполнить поиск.",
  };
  return (
    <section className="panel bank-panel">
      <div className="section-icon">
        <span className="mini-alfa">A</span>
        <h2>Контекст Альфа-Банка</h2>
      </div>
      {found.length ? (
        <>
          <BankDigest
            summary={context?.summary || state.bank_context?.summary}
            sources={registry}
          />
          <details className="bank-materials"><summary>Источники и полный контекст · {found.length}<ChevronDown size={16}/></summary>
          <p className="muted small">
            Найдено фрагментов: {found.length} · Использовано в выводах: {used}.
            Материалы без цитат показаны для проверки контекста.
          </p>
          {found.map((source: Obj) => (
            <details className="bank-citation" key={source.source_id}>
              <summary>
                <div>
                  <b>{source.title}</b>
                  <small>
                    {date(source.published_at, true)} ·{" "}
                    {cited.has(source.source_id)
                      ? "Использован в выводах"
                      : "Найден поиском"}
                  </small>
                </div>
                <ChevronDown size={18} />
              </summary>
              {state.bank_metadata?.[source.source_id]?.pages?.length > 0 && (
                <p className="muted small">
                  Страницы:{" "}
                  {state.bank_metadata[source.source_id].pages.join(", ")}
                </p>
              )}
              <pre>{source.text}</pre>
              {(state.result?.claims || [])
                .flatMap((c: Obj) => c.evidence || [])
                .filter((e: Obj) => e.source_id === source.source_id)
                .map((e: Obj, i: number) => (
                  <blockquote key={i}>«{e.quote}»</blockquote>
                ))}
            </details>
          ))}
          </details>
          <p className="muted small bank-date-note">
            Обзоры и прогнозы относятся к дате публикации; они не подтверждают
            текущие показатели конкретной компании.
          </p>
        </>
      ) : (
        <p>{empty[context?.status || "not_searched"] || empty.not_searched}</p>
      )}
    </section>
  );
}

function Payments({
  company,
  compact = false,
}: {
  company: Company;
  compact?: boolean;
}) {
  const payments = company.payments;
  const totals = payments?.totals;
  if (!totals) return null;
  return (
    <section
      className={"panel payments-panel " + (compact ? "compact-payments" : "")}
    >
      <div className="section-icon">
        <Wallet size={19} />
        <h2>Платёжные связи</h2>
        <span className="period-label">Период не указан</span>
      </div>
      {!compact && (
        <div className="payment-stats">
          <div>
            <span>Входящие платежи</span>
            <b>{money(totals.incoming_amount_rub)}</b>
          </div>
          <div>
            <span>Исходящие платежи</span>
            <b>{money(totals.outgoing_amount_rub)}</b>
          </div>
          <div>
            <span>Контрагентов</span>
            <b>{totals.unique_counterparties_count}</b>
          </div>
        </div>
      )}
      <p className="muted small">
        Основные отрасли контрагентов · доля в платёжном обороте
      </p>
      <div className="industry-bars">
        {(payments.top_okved || []).slice(0, 3).map((row: Obj, i: number) => (
          <div key={row.okved_class}>
            <div>
              <span>{row.okved_name}</span>
              <b>{row.share_pct.toLocaleString("ru-RU")}%</b>
            </div>
            <div className="bar-track">
              <i
                style={{
                  width: Math.min(100, row.share_pct) + "%",
                  background: ["#ef3124", "#a5a9b2", "#d7d9df"][i],
                }}
              />
            </div>
          </div>
        ))}
      </div>
      {!compact && !!payments.counterparties?.top_3?.length && (
        <details className="counterparty-details">
          <summary>
            Крупнейшие контрагенты
            <ChevronDown size={16} />
          </summary>
          {payments.counterparties.top_3.map((row: Obj) => (
            <div className="counterparty-row" key={row.company_id}>
              <div>
                <b>{row.company_id}</b>
                <span>{row.okved_name}</span>
                <small>{row.region}</small>
              </div>
              <strong>
                {row.share_pct.toLocaleString("ru-RU")}%<small>оборота</small>
              </strong>
            </div>
          ))}
        </details>
      )}
      <p className="muted small payment-note">
        Оборот не равен выручке. Роли контрагентов, динамика и сезонность не
        установлены; перечень отраслей неполный.
      </p>
    </section>
  );
}

function App() {
  const [boot, setBoot] = useState<Bootstrap>();
  const [bootError, setBootError] = useState("");
  const [companyId, setCompanyId] = useState(() => {
    try {
      return localStorage.getItem("alfa-company") || "U_37452";
    } catch {
      return "U_37452";
    }
  });
  const [profileOpen, setProfileOpen] = useState(false);
  const [expertOpen, setExpertOpen] = useState(false);
  const [demo, setDemo] = useState<Obj>();
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState("");
  const currentCompany = useRef(companyId);
  currentCompany.current = companyId;
  const demoSuffix = demo?.id ? "&demo_id=" + encodeURIComponent(demo.id) : "";
  const [section, setSection] = useState<"feed" | "bank" | "company">("feed");
  const [mode, setMode] = useState("personal");
  const [feed, setFeed] = useState<{
    company_id: string;
    demo?: Obj;
    items: Card[];
    matched_ids: string[];
    matching_as_of: string;
    sync?: Obj;
    pending_importance?: number;
    links_available?: boolean;
  }>();
  const [loading, setLoading] = useState(true);
  const [feedError, setFeedError] = useState("");
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("all");
  const [level, setLevel] = useState("all");
  const [visibleCount, setVisibleCount] = useState(8);
  const [selectedId, setSelectedId] = useState<string>();
  const [detail, setDetail] = useState<Obj>();
  const [detailError, setDetailError] = useState("");
  const [detailTab, setDetailTab] = useState("analysis");
  const [related, setRelated] = useState<Obj>();
  const [relatedError, setRelatedError] = useState("");
  const [job, setJob] = useState<Obj>();
  const [jobError, setJobError] = useState("");
  const [jobStarting, setJobStarting] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [chatOpen, setChatOpen] = useState(false);
  const [bankSources, setBankSources] = useState<Obj[]>([]);
  const [bankQuery, setBankQuery] = useState("");
  const [bankError, setBankError] = useState("");
  const [expandedDoc, setExpandedDoc] = useState<string>();
  const [documentData, setDocumentData] = useState<Obj>();
  const [documentError, setDocumentError] = useState("");
  const [reload, setReload] = useState(0);
  const { saved, toggle } = useBookmarks();
  const chatEnd = useRef<HTMLDivElement>(null);
  const company = boot?.companies.find((c) => c.id === companyId);
  const activeProfile = boot?.profiles.find((p) =>
    p.company_ids.includes(companyId),
  );
  const profileCompanies =
    boot?.companies.filter(
      (c) => !activeProfile || activeProfile.company_ids.includes(c.id),
    ) || [];
  const profileTrigger = useRef<HTMLButtonElement>(null);
  const profileClose = useRef<HTMLButtonElement>(null);
  const state = detail?.state;
  const selectedCard = feed?.items.find((c) => c.id === selectedId);
  const busy =
    jobStarting || (job && ["running", "queued"].includes(job.status));
  const mountedPair = useRef("");
  mountedPair.current = companyId + ":" + selectedId;

  const loadBoot = () => {
    setBootError("");
    api<Bootstrap>("/bootstrap")
      .then((data) => {
        setBoot(data);
        if (
          !data.companies.some((c) => c.id === companyId) &&
          data.companies[0]
        )
          setCompanyId(data.companies[0].id);
      })
      .catch((e) => setBootError(e.message));
  };
  useEffect(loadBoot, []);
  useEffect(() => {
    if (!boot) return;
    const controller = new AbortController();
    setLoading(true);
    setFeedError("");
    setFeed(undefined);
    setVisibleCount(8);
    api<typeof feed>(
      "/feed?company_id=" + encodeURIComponent(companyId) + demoSuffix,
      undefined,
      controller.signal,
    )
      .then((value) => { if (!controller.signal.aborted && value?.company_id === currentCompany.current) setFeed(value); })
      .catch((e) => {
        if (e.name !== "AbortError") setFeedError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [boot, companyId, reload, demo?.id]);
  useEffect(() => {
    setDetail(undefined);
    setDetailError("");
    setMessages([]);
    setConversationId(undefined);
    setJob(undefined);
    setJobError("");
    setQuestion("");
    setChatOpen(false);
    setDetailTab("analysis");
    if (!selectedId) return;
    const controller = new AbortController();
    api(
      "/analysis?company_id=" +
        encodeURIComponent(companyId) +
        "&news_id=" +
        encodeURIComponent(selectedId) + demoSuffix,
      undefined,
      controller.signal,
    )
      .then((value) => { if (!controller.signal.aborted) setDetail(value); })
      .catch((e) => {
        if (e.name !== "AbortError") setDetailError(e.message);
      });
    return () => controller.abort();
  }, [companyId, selectedId, demo?.id]);
  useEffect(() => {
    if (!job || !["running", "queued"].includes(job.status)) return;
    const pair = mountedPair.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const value = await api(
          "/jobs/" + job.id,
          undefined,
          controller.signal,
        );
        if (mountedPair.current !== pair) return;
        setJob(value);
        if (value.status === "done") {
          if (value.kind === "analysis") {
            const next = await api(
              "/analysis?company_id=" +
                encodeURIComponent(companyId) +
                "&news_id=" +
                encodeURIComponent(selectedId!),
            );
            if (mountedPair.current === pair) {
              setDetail(next);
              setMessages([]);
              setConversationId(undefined);
              setReload((v) => v + 1);
            }
          } else if (value.kind === "matching") {
            setRelated(value.matches);
            setReload((v) => v + 1);
          } else {
            setMessages((old) => [
              ...old,
              {
                role: "assistant",
                text: value.answer.follow_up_answer || value.answer.summary,
                claims: value.answer.claims,
                sources: value.retrieved_sources,
                retrieval: value.retrieval,
              },
            ]);
          }
        }
        if (value.status === "failed") setJobError(value.error);
      } catch (e: any) {
        if (e.name !== "AbortError") {
          setJobError(
            "Потеряно соединение. Откройте разбор заново, чтобы проверить результат.",
          );
          setJob(undefined);
        }
      }
    }, 1800);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [job]);
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, job]);
  useEffect(() => {
    if (section === "bank") {
      setBankError("");
      api<Obj[]>("/bank-sources")
        .then(setBankSources)
        .catch((e) => setBankError(e.message));
    }
  }, [section, reload]);
  useEffect(() => {
    setDocumentData(undefined);
    setDocumentError("");
    if (!expandedDoc) return;
    const controller = new AbortController();
    api(
      "/bank-document?id=" + encodeURIComponent(expandedDoc),
      undefined,
      controller.signal,
    )
      .then(setDocumentData)
      .catch((e) => {
        if (e.name !== "AbortError") setDocumentError(e.message);
      });
    return () => controller.abort();
  }, [expandedDoc]);
  useEffect(() => {
    setVisibleCount(8);
  }, [query, topic, level, mode]);
  useEffect(() => {
    setRelated(undefined);
    setRelatedError("");
    if (!selectedId) return;
    const controller = new AbortController();
    api(
      "/news-companies?news_id=" + encodeURIComponent(selectedId) + "&company_id=" + encodeURIComponent(companyId) + demoSuffix,
      undefined,
      controller.signal,
    )
      .then((value) => { if (!controller.signal.aborted) setRelated(value); })
      .catch((e) => {
        if (e.name !== "AbortError") setRelatedError(e.message);
      });
    return () => controller.abort();
  }, [selectedId, companyId, reload, demo?.id]);
  useEffect(() => {
    if (!boot) return;
    const controller = new AbortController();
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await api<typeof feed>("/feed?company_id=" + encodeURIComponent(companyId) + demoSuffix, undefined, controller.signal);
        if (!controller.signal.aborted && value?.company_id === currentCompany.current) setFeed(value);
        if (demo && selectedId?.startsWith("demo:")) {
          const detailValue = await api("/analysis?company_id=" + encodeURIComponent(companyId) + "&news_id=" + encodeURIComponent(selectedId) + demoSuffix, undefined, controller.signal);
          if (!controller.signal.aborted) setDetail(detailValue);
        }
      } catch (e: any) {
        if (e.name !== "AbortError" && demo) setDemoError(e.message);
      } finally { pending = false; }
    };
    const timer = window.setInterval(refresh, demo ? 1200 : 10000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [boot, companyId, demo?.id, selectedId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (profileOpen) {
          setProfileOpen(false);
          profileTrigger.current?.focus();
        } else if (chatOpen) setChatOpen(false);
        else setSelectedId(undefined);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chatOpen, profileOpen]);
  useEffect(() => {
    if (!profileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    profileClose.current?.focus();
    return () => {
      document.body.style.overflow = previous;
    };
  }, [profileOpen]);

  function rememberCompany(id: string) {
    try {
      localStorage.setItem("alfa-company", id);
      const profile = boot?.profiles.find((p) => p.company_ids.includes(id));
      if (profile)
        localStorage.setItem("alfa-profile-company-" + profile.id, id);
    } catch {}
  }
  function changeCompany(id: string) {
    if (demo) void api("/expert-demo", { action: "stop", company_id: companyId, demo_id: demo.id }).catch(() => {});
    setDemo(undefined); setDemoError(""); setExpertOpen(false);
    setFeed(undefined); setDetail(undefined); setMessages([]); setLoading(true);
    setQuery(""); setTopic("all"); setLevel("all"); setMode("personal");
    setCompanyId(id);
    setSelectedId(undefined);
    rememberCompany(id);
  }
  function changeProfile(profile: BusinessProfile) {
    let next = profile.company_ids.includes(companyId)
      ? companyId
      : profile.company_ids[0];
    try {
      const saved = localStorage.getItem("alfa-profile-company-" + profile.id);
      if (saved && profile.company_ids.includes(saved)) next = saved;
    } catch {}
    changeCompany(next);
    setProfileOpen(false);
    setQuery("");
    setTopic("all");
    setLevel("all");
    setMode("personal");
    profileTrigger.current?.focus();
  }
  async function startDemo() {
    if (demoBusy) return;
    const selectedCompany = companyId;
    setDemoBusy(true); setDemoError("");
    try {
      if (demo) await api("/expert-demo", { action: "stop", company_id: companyId, demo_id: demo.id }).catch(() => {});
      const value = await api("/expert-demo", { action: "start", company_id: selectedCompany });
      if (currentCompany.current !== selectedCompany) return;
      setDemo(value); setSelectedId(undefined); setMode("personal"); setTopic("all"); setLevel("all"); setQuery("");
    } catch (e: any) { if (currentCompany.current === selectedCompany) setDemoError(e.message); }
    finally { setDemoBusy(false); }
  }
  async function stopDemo() {
    if (demo) await api("/expert-demo", { action: "stop", company_id: companyId, demo_id: demo.id }).catch(() => {});
    setDemo(undefined); setSelectedId(undefined); setDemoError(""); setExpertOpen(false); setMode("personal");
  }
  function navigate(next: typeof section) {
    setSection(next);
    setSelectedId(undefined);
    setQuery("");
  }
  async function start(
    kind: "analysis" | "chat" | "matching",
    prompted?: string,
  ) {
    if (busy || !selectedId || (detail?.is_demo && kind !== "chat")) return;
    const pair = mountedPair.current;
    const text = (prompted || question).trim();
    if (kind === "chat" && !text) return;
    setJobStarting(true);
    setJobError("");
    try {
      const value = await api(
        kind === "chat"
          ? "/chat"
          : kind === "matching"
            ? "/matches"
            : "/analysis",
        {
          company_id: companyId,
          news_id: selectedId,
          ...(kind === "chat"
            ? { question: text, conversation_id: conversationId, ...(detail?.is_demo ? { demo_id: demo?.id } : {}) }
            : {}),
        },
      );
      if (mountedPair.current !== pair) return;
      setJob(value);
      if (kind === "chat") {
        setConversationId(value.conversation_id);
        setMessages((old) => [...old, { role: "user", text }]);
        setQuestion("");
      }
    } catch (e: any) {
      if (mountedPair.current === pair) setJobError(e.message);
    } finally {
      setJobStarting(false);
    }
  }

  const matched = new Set(feed?.matched_ids || []);
  const filtered = (feed?.items || []).filter((c) => {
    if (mode === "personal" && !matched.has(c.id) && !c.has_analysis && !c.is_demo)
      return false;
    if (mode === "saved" && !saved.includes(companyId + ":" + c.id))
      return false;
    if (topic !== "all" && !c.classification.topics?.includes(topic))
      return false;
    if (
      level !== "all" &&
      (level === "ready"
        ? !c.has_analysis
        : c.classification.importance !== level)
    )
      return false;
    return (
      !query ||
      (
        c.title +
        " " +
        c.text +
        " " +
        (c.short_answer || c.brief?.short_answer || "")
      )
        .toLocaleLowerCase("ru")
        .includes(query.toLocaleLowerCase("ru"))
    );
  });
  const availableTopics = [
    ...new Set(
      (feed?.items || []).flatMap((c) => c.classification.topics || []),
    ),
  ] as string[];
  const featured = feed?.items.find(
    (c) => c.short_answer || c.brief?.short_answer,
  );
  const pairSaved = (id: string) => saved.includes(companyId + ":" + id);
  const sources = Object.fromEntries(
    (state?.retrieved_sources || []).map((s: Obj) => [s.source_id, s]),
  ) as Record<string, Obj>;
  const citedBank = new Set<string>(
    (state?.result?.claims || [])
      .flatMap((c: Obj) => c.evidence || [])
      .map((e: Obj) => e.source_id)
      .filter((id: string) => id.startsWith("bank:")),
  );
  const news = detail?.event || selectedCard;
  if (news?.id && !sources["news:" + news.id]) {
    sources["news:" + news.id] = {
      source_id: "news:" + news.id,
      kind: "news",
      title: news.title,
      url: news.url,
      published_at: news.published_at,
    };
  }
  const detailClassification = {
    ...(state?.brief?.classification ||
      state?.preparation?.classification ||
      selectedCard?.classification ||
      {}),
    ...(detail?.link?.importance
      ? {
          importance: detail.link.importance,
          importance_reason: detail.link.importance_reason,
        }
      : {}),
  };
  const primaryTopic = (card: Card) =>
    (card.classification.topics || []).map((t: string) => topics[t] || t)[0] ||
    "Новости";
  const docSources = (doc: Obj) =>
    bankSources.filter(
      (s) =>
        s.locator?.includes("/" + doc.id + "#") || s.title?.includes(doc.title),
    );

  if (bootError)
    return (
      <main className="startup">
        <Logo />
        <ErrorBox message={bootError} retry={loadBoot} />
      </main>
    );
  if (!boot)
    return (
      <main className="startup">
        <Logo />
        <Loader2 className="spin" />
        <p>Собираем вашу ленту…</p>
      </main>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Logo />
        <div className="workspace-label">БИЗНЕС · ОБЗОР</div>
        <nav aria-label="Основная навигация">
          <button
            className={section === "feed" ? "active" : ""}
            onClick={() => navigate("feed")}
          >
            <Newspaper size={21} />
            Моя лента<span>{feed?.matched_ids.length || "—"}</span>
          </button>
          <button
            className={section === "bank" ? "active" : ""}
            onClick={() => navigate("bank")}
          >
            <Layers3 size={21} />
            Аналитика банка
          </button>
          <button
            className={section === "company" ? "active" : ""}
            onClick={() => navigate("company")}
          >
            <Building2 size={21} />
            Моя компания
          </button>
        </nav>
        <div className="sidebar-note">
          <div className="note-symbol">
            <ShieldCheck size={23} />
          </div>
          <b>Выводы с основаниями</b>
          <p>У каждого разбора есть факты, источники и ограничения.</p>
        </div>
        <div className="sidebar-bottom">
          <span
            className={
              "status-dot " +
              (boot.status.database === "connected" ? "green" : "amber")
            }
          />
          {boot.status.database === "connected"
            ? "Данные подключены"
            : "Сохранённый набор"}
          <small>
            {boot.status.news_count} новостей · {boot.status.company_count}{" "}
            компаний
          </small>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="mobile-brand">
            <Logo />
          </div>
          <div className="breadcrumb">
            Бизнес <ChevronRight size={14} />
            <span>
              {section === "bank"
                ? "Аналитика банка"
                : section === "company"
                  ? "Профиль компании"
                  : "Персональная аналитика"}
            </span>
          </div>
          <div className="company-switch">
            <span className="company-avatar">
              <Building2 size={18} />
            </span>
            <label>
              <span>{activeProfile?.title || "Ваша компания"}</span>
              <select
                aria-label="Выбрать компанию"
                value={companyId}
                onChange={(e) => changeCompany(e.target.value)}
              >
                {profileCompanies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {shortIndustry(c)} · {c.id}
                  </option>
                ))}
              </select>
            </label>
            <ChevronDown size={16} />
          </div>
          <button
            ref={profileTrigger}
            className="user-avatar profile-trigger"
            aria-label="Сменить бизнес-профиль"
            title={activeProfile?.title || "Сменить профиль"}
            aria-haspopup="dialog"
            aria-expanded={profileOpen}
            aria-controls="business-profiles"
            style={{ background: activeProfile?.color, color: "#fff" }}
            onClick={() => setProfileOpen(true)}
          >
            {activeProfile?.initial || "Б"}
          </button>
        </header>
        {profileOpen && (
          <div
            className="profile-backdrop"
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setProfileOpen(false);
                profileTrigger.current?.focus();
              }
            }}
          >
            <section
              id="business-profiles"
              className="profile-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="profile-title"
              onKeyDown={(e) => {
                if (e.key !== "Tab") return;
                const buttons = Array.from(
                  e.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
                );
                const first = buttons[0],
                  last = buttons[buttons.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }}
            >
              <div className="profile-dialog-heading">
                <div>
                  <span className="eyebrow">ВАШ БИЗНЕС</span>
                  <h2 id="profile-title">Выберите профиль</h2>
                </div>
                <button
                  ref={profileClose}
                  className="icon-button"
                  aria-label="Закрыть выбор профиля"
                  onClick={() => {
                    setProfileOpen(false);
                    profileTrigger.current?.focus();
                  }}
                >
                  <X size={20} />
                </button>
              </div>
              <p>
                Смените направление бизнеса, чтобы увидеть его компании и
                персональную ленту.
              </p>
              <div className="profile-options">
                {boot.profiles.map((profile) => (
                  <button
                    key={profile.id}
                    className={
                      "profile-option " +
                      (profile.id === activeProfile?.id ? "selected" : "")
                    }
                    aria-pressed={profile.id === activeProfile?.id}
                    onClick={() => changeProfile(profile)}
                  >
                    <span
                      className="profile-option-avatar"
                      style={{ background: profile.color }}
                    >
                      {profile.initial}
                    </span>
                    <span>
                      <b>{profile.title}</b>
                      <small>{profile.description}</small>
                      <em>Компаний: {profile.company_ids.length} · Разборов: {profile.analysis_count || 0}</em>
                    </span>
                    {profile.id === activeProfile?.id ? (
                      <Check size={20} />
                    ) : (
                      <ArrowRight size={18} />
                    )}
                  </button>
                ))}
              </div>
              <div className="profile-dialog-note">
                <ShieldCheck size={16} />
                <span>
                  Разборы, важность и сохранённые новости относятся к выбранной
                  компании.
                </span>
              </div>
            </section>
          </div>
        )}
        <nav className="mobile-nav" aria-label="Разделы">
          <button
            className={section === "feed" ? "active" : ""}
            onClick={() => navigate("feed")}
          >
            Моя лента
          </button>
          <button
            className={section === "bank" ? "active" : ""}
            onClick={() => navigate("bank")}
          >
            Аналитика банка
          </button>
          <button
            className={section === "company" ? "active" : ""}
            onClick={() => navigate("company")}
          >
            Компания
          </button>
        </nav>
        <main
          className={"main-content " + (selectedId ? "detail-content" : "")}
        >
          {selectedId ? (
            <>
              <div className="detail-toolbar">
                <button
                  className="back-link"
                  onClick={() => setSelectedId(undefined)}
                >
                  <ArrowLeft size={17} />К ленте
                </button>
                <button
                  className={
                    "icon-button " + (pairSaved(selectedId) ? "saved" : "")
                  }
                  aria-label={
                    pairSaved(selectedId)
                      ? "Убрать из сохранённого"
                      : "Сохранить новость"
                  }
                  onClick={() => toggle(companyId + ":" + selectedId)}
                >
                  <Bookmark
                    size={20}
                    fill={pairSaved(selectedId) ? "currentColor" : "none"}
                  />
                </button>
              </div>
              {detailError ? (
                <ErrorBox message={detailError} />
              ) : !detail ? (
                <Skeleton />
              ) : (
                <>
                  {detail.is_demo && <div className="demo-detail-notice" role="note">Вымышленная новость · подбор компаний, важность и разбор выполняет рабочий пайплайн. Источники из БД служат контекстом и не подтверждают само событие.</div>}
                  <div className="detail-heading">
                    <div className="eyebrow">РАЗБОР ДЛЯ {companyId}</div>
                    <Badge
                      value={detailClassification.importance}
                      status={detail?.link?.importance_status}
                    />
                    <h1>{news.title}</h1>
                    <div className="news-meta">
                      <span className="publisher-dot">
                        {(selectedCard?.publisher || "Н")[0]}
                      </span>
                      {selectedCard?.publisher || "Публикация"}
                      <span>·</span>
                      {date(news.published_at, true)}
                      <a
                        href={safeUrl(news.url)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Оригинал <ArrowUpRight size={14} />
                      </a>
                    </div>
                  </div>
                  <div className="detail-layout">
                    <div className="detail-main">
                      <div
                        className="detail-tabs"
                        role="tablist"
                        aria-label="Содержание новости"
                      >
                        {[
                          ["analysis", "Разбор"],
                          ["companies", "Компании"],
                          ["original", "Новость"],
                          ["sources", "Источники"],
                        ].map(([key, title]) => (
                          <button
                            key={key}
                            role="tab"
                            aria-selected={detailTab === key}
                            onClick={() => setDetailTab(key)}
                          >
                            {title}
                          </button>
                        ))}
                      </div>
                      {detailTab === "companies" ? (
                        <section className="panel related-panel">
                          <div className="section-icon">
                            <Building2 size={20} />
                            <h2>Компании по этой новости</h2>
                          </div>
                          <p>
                            Сохранённые связи с компаниями. Оценка важности
                            относится к каждой компании отдельно.
                          </p>
                          <Button
                            view="secondary"
                            size={40}
                            loading={!!busy && job?.kind === "matching"}
                            disabled={
                              !!busy ||
                              (!boot.status.live_available || !!detail?.is_demo) ||
                              !related?.available
                            }
                            onClick={() => start("matching")}
                          >
                            Подобрать компании
                          </Button>
                          {relatedError && <ErrorBox message={relatedError} />}
                          <div className="related-list">
                            {related?.items?.length ? (
                              related.items.map((row: Obj) => (
                                <article
                                  className={
                                    "related-company " +
                                    (row.company_id === companyId
                                      ? "current"
                                      : "")
                                  }
                                  key={row.company_id}
                                >
                                  <div className="related-company-top">
                                    <div>
                                      <span className="eyebrow">
                                        {row.company_id}
                                      </span>
                                      <h3>{shortIndustry(row.company)}</h3>
                                    </div>
                                    <Badge
                                      value={row.importance}
                                      status={row.importance_status}
                                    />
                                  </div>
                                  <p>{row.company.industry}</p>
                                  <small>
                                    {row.company.region} ·{" "}
                                    {row.analysis_status === "running"
                                      ? "Разбор готовится…"
                                      : row.analysis_status === "ready" ||
                                          row.analysis_status === "partial"
                                        ? "Разбор подготовлен"
                                        : "Подробного разбора пока нет"}
                                  </small>
                                  {row.importance_reason && (
                                    <p className="related-reason">
                                      {row.importance_reason}
                                    </p>
                                  )}
                                  <button
                                    className="text-link"
                                    onClick={() => {
                                      const publication = selectedId;
                                      changeCompany(row.company_id);
                                      setSelectedId(publication);
                                      setDetailTab("analysis");
                                    }}
                                  >
                                    {row.company_id === companyId
                                      ? "Открыть разбор"
                                      : "Посмотреть для этой компании"}
                                    <ArrowRight size={15} />
                                  </button>
                                </article>
                              ))
                            ) : (
                              <p className="muted small">
                                {related
                                  ? "Связи пока не найдены. Запустите подбор компаний."
                                  : "Загружаем связи…"}
                              </p>
                            )}
                          </div>
                          <p className="muted small">
                            Сходство текстов помогает найти кандидатов и само по
                            себе не доказывает влияние новости.
                          </p>
                        </section>
                      ) : detailTab === "original" ? (
                        <section className="panel original-text">
                          <div className="eyebrow">ТЕКСТ ИСТОЧНИКА</div>
                          <h2>{news.title}</h2>
                          {news.text
                            .split("\n")
                            .filter(Boolean)
                            .map((p: string, i: number) => (
                              <p key={i}>{p}</p>
                            ))}
                          <a
                            className="text-link"
                            href={safeUrl(news.url)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Открыть публикацию <ExternalLink size={15} />
                          </a>
                        </section>
                      ) : detailTab === "sources" ? (
                        <section className="panel">
                          <h2>Источники разбора</h2>
                          <div className="source-item">
                            <FileText />
                            <div>
                              <b>Исходная новость</b>
                              <p>{news.title}</p>
                              <a
                                className="text-link"
                                href={safeUrl(news.url)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Читать оригинал <ExternalLink size={14} />
                              </a>
                            </div>
                          </div>
                          <div className="source-item">
                            <Building2 />
                            <div>
                              <b>Профиль и агрегаты компании {companyId}</b>
                              <p>{company?.industry}</p>
                              <small>
                                Период платежей не указан. Регион отражает
                                регистрацию.
                              </small>
                            </div>
                          </div>
                          {(state?.retrieved_sources || []).map(
                            (source: Obj) => (
                              <details
                                className="source-detail"
                                key={source.source_id}
                              >
                                <summary>
                                  <span>
                                    {source.kind === "bank"
                                      ? "Альфа-Банк"
                                      : source.kind === "metric"
                                        ? "Платежи"
                                        : "Новость"}
                                  </span>
                                  <b>{source.title}</b>
                                  <ChevronDown size={16} />
                                </summary>
                                <small>
                                  {date(source.published_at, true)} ·{" "}
                                  {source.kind === "bank" &&
                                  !citedBank.has(source.source_id)
                                    ? "Найден при поиске, не использован в выводе"
                                    : "Материал контекста"}
                                </small>
                                <pre>{source.text}</pre>
                                {safeUrl(source.url || "") && (
                                  <a
                                    className="text-link"
                                    href={safeUrl(source.url)}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    Открыть источник <ExternalLink size={14} />
                                  </a>
                                )}
                              </details>
                            ),
                          )}
                        </section>
                      ) : detail.is_demo && !state ? (
                        <section className="panel demo-wait" role="status">{!["failed", "not_matched", "not_business"].includes(detail.phase) && <Loader2 className="spin" size={24}/>}<h2>{detail.phase === "failed" ? "Не удалось обработать новость" : ["not_matched", "not_business"].includes(detail.phase) ? "Разбор для этой компании не создан" : "Тестовая новость обрабатывается"}</h2><p>{detail.stage || "Идёт реальная обработка"}. {detail.phase === "failed" ? "Результат не подменяется шаблоном. Можно повторить сценарий после устранения ошибки." : ["not_matched", "not_business"].includes(detail.phase) ? "Проверьте фактически подобранные компании на вкладке «Компании»." : "Подбор и разбор выполняются через модели и БД. Результат появится после завершения обработки."}</p></section>
                      ) : !state ? (
                        <section className="panel empty-analysis">
                          {detail.link?.importance_reason && (
                            <div className="triage-preview">
                              <div className="eyebrow">
                                ПРЕДВАРИТЕЛЬНАЯ ОЦЕНКА
                              </div>
                              <p>{detail.link.importance_reason}</p>
                              <Evidence
                                items={detail.link.importance_evidence}
                                sources={sources}
                              />
                            </div>
                          )}
                          <div className="empty-icon">
                            <Sparkles />
                          </div>
                          <h2>Как эта новость влияет на вас?</h2>
                          <p>
                            Подготовим разбор с учётом профиля компании,
                            платежных связей и материалов банка. Вы получите
                            короткий вывод и ссылки на основания.
                          </p>
                          <Button
                            view="primary"
                            size={48}
                            loading={!!busy}
                            disabled={(!boot.status.live_available || !!detail?.is_demo)}
                            onClick={() => start("analysis")}
                          >
                            Подготовить разбор
                          </Button>
                          <small>Анализ может занять несколько минут.</small>
                          {(!boot.status.live_available || !!detail?.is_demo) && (
                            <p className="muted">
                              Новые разборы доступны после подключения базы и
                              ключа моделей на сервере.
                            </p>
                          )}
                        </section>
                      ) : (
                        <>
                          <section className="brief-panel">
                            <div className="eyebrow">
                              <Sparkles size={15} /> КОРОТКО ДЛЯ ВАШЕГО БИЗНЕСА
                            </div>
                            <p>
                              {state.brief?.short_answer ||
                                state.result.summary}
                            </p>
                            <div className="brief-foot">
                              <ShieldCheck size={15} />
                              {state.result.status === "supported"
                                ? "Есть подтверждённые основания"
                                : "Для персонального вывода нужны данные"}
                              <span>{date(state.as_of)}</span>
                            </div>
                          </section>
                          <BankContext
                            state={state}
                            context={detail.bank_context}
                          />
                          <section className="panel">
                            <div className="section-icon">
                              <Newspaper size={18} />
                              <h2>Что произошло</h2>
                            </div>
                            <p>
                              {state.brief?.news_summary ||
                                state.preparation?.extraction?.facts?.[0]
                                  ?.text ||
                                news.text.slice(0, 350)}
                            </p>
                            <Evidence
                              items={
                                state.brief?.evidence?.news_summary ||
                                state.preparation?.extraction?.facts?.[0]
                                  ?.evidence
                              }
                              sources={sources}
                            />
                          </section>
                          <section className="panel">
                            <div className="section-icon">
                              <Building2 size={18} />
                              <h2>Почему это касается вас</h2>
                            </div>
                            {detailClassification.importance_reason && (
                              <div className="importance-explanation">
                                <Badge
                                  value={detailClassification.importance}
                                />
                                <p>{detailClassification.importance_reason}</p>
                              </div>
                            )}
                            <div className="context-row">
                              <span>Основная деятельность</span>
                              <b>{company?.industry}</b>
                            </div>
                            <div className="context-row">
                              <span>Регион регистрации</span>
                              <b>{company?.region}</b>
                            </div>
                            <div className="context-row">
                              <span>Годовая выручка</span>
                              <b>{company && money(company.revenue_rub)}</b>
                            </div>
                            <p className="muted small">
                              Год выручки и период платежей не указаны.
                              Банковские услуги сами по себе не подтверждают
                              долговую нагрузку.
                            </p>
                            <Evidence
                              items={
                                detail.link?.importance_evidence ||
                                state.brief?.evidence?.importance
                              }
                              sources={sources}
                            />
                          </section>
                          {company && <Payments company={company} compact />}
                          <section className="panel">
                            <div className="section-icon">
                              <TrendingUp size={19} />
                              <h2>Факты и возможное влияние</h2>
                            </div>
                            {state.result.claims
                              .filter((claim: Obj) => claim.kind === "fact")
                              .map((claim: Obj, i: number) => (
                                <div className="claim" key={i}>
                                  <span className="claim-type fact">
                                    ФАКТ
                                  </span>
                                  <p>{claim.text}</p>
                                  <Evidence
                                    items={claim.evidence}
                                    sources={sources}
                                  />
                                </div>
                              ))}
                          </section>
                          {!!state.result.missing_data?.length && (
                            <section className="panel limitations">
                              <div className="section-icon">
                                <CircleHelp size={19} />
                                <h2>Что ещё нужно уточнить</h2>
                              </div>
                              <ul>
                                {[
                                  ...new Set<string>(
                                    state.result.missing_data.map(
                                      limitationText,
                                    ),
                                  ),
                                ].map((item: string, i: number) => (
                                  <li key={i}>{item}</li>
                                ))}
                              </ul>
                            </section>
                          )}
                          <div className="analysis-bottom">
                            <span>
                              <Clock3 size={14} /> Разбор от{" "}
                              {date(state.as_of, true)}
                            </span>
                            <Button
                              view="transparent"
                              size={40}
                              disabled={!!busy || (!boot.status.live_available || !!detail?.is_demo)}
                              onClick={() => start("analysis")}
                              leftAddons={<RefreshCw size={15} />}
                            >
                              Обновить разбор
                            </Button>
                          </div>
                          <AnalysisFeedback key={detail.analysis_version} companyId={companyId} newsId={selectedId} version={detail.analysis_version} isDemo={!!detail.is_demo} demoId={detail.is_demo ? demo?.id : undefined}/>
                        </>
                      )}
                      {busy && job?.kind !== "chat" && (
                        <div className="progress-box" role="status">
                          <Loader2 className="spin" />
                          <div>
                            <b>{job?.stage || "Запускаем анализ"}</b>
                            <p>
                              Можно дождаться результата здесь. Разбор
                              продолжится и при переходе в ленту.
                            </p>
                          </div>
                        </div>
                      )}
                      {jobError && <ErrorBox message={jobError} />}
                    </div>
                    <aside
                      className={"chat-panel " + (chatOpen ? "chat-open" : "")}
                    >
                      <div className="chat-heading">
                        <div className="chat-symbol">
                          <MessageSquare size={19} />
                        </div>
                        <div>
                          <b>Обсудим новость</b>
                          <small>В контексте вашей компании</small>
                        </div>
                        <button
                          className="icon-button chat-close"
                          aria-label="Закрыть чат"
                          onClick={() => setChatOpen(false)}
                        >
                          <X size={20} />
                        </button>
                      </div>
                      <div className="chat-body">
                        <div className="chat-intro">
                          <div className="eyebrow">
                            {shortIndustry(company)} · {companyId}
                          </div>
                          <h3>От события — к пониманию</h3>
                          <p>
                            Уточните, что новость означает для бизнеса. Можно
                            спросить и о других новостях: найдём материалы в
                            базе и покажем источники ответа.
                          </p>
                        </div>
                        {messages.map((message, i) => (
                          <div key={i} className={"message " + message.role}>
                            <small>
                              {message.role === "user" ? "Вы" : "Аналитик"}
                            </small>
                            <p>{message.text}</p>
                            {message.role === "assistant" && (
                              <ChatSources
                                message={message}
                                sources={sources}
                              />
                            )}
                          </div>
                        ))}
                        {busy && job?.kind === "chat" && (
                          <div className="chat-thinking" role="status">
                            <Loader2 className="spin" size={16} />
                            {job?.stage ||
                              "Ищем материалы и проверяем основания…"}
                          </div>
                        )}
                        {jobError && <ErrorBox message={jobError} />}
                        <div ref={chatEnd} />
                      </div>
                      {!messages.length && (
                        <div className="suggestions">
                          {[
                            "Почему это касается нашей компании?",
                            "Какие данные стоит проверить?",
                            "Что говорят материалы банка?",
                          ].map((text) => (
                            <button
                              key={text}
                              disabled={
                                !state || !!busy || !boot.status.live_available
                              }
                              onClick={() => {
                                setChatOpen(true);
                                start("chat", text);
                              }}
                            >
                              {text}
                              <ArrowUpRight size={15} />
                            </button>
                          ))}
                        </div>
                      )}
                      <form
                        className="chat-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          start("chat");
                        }}
                      >
                        <label className="sr-only" htmlFor="question">
                          Вопрос по новости
                        </label>
                        <textarea
                          id="question"
                          placeholder={
                            state
                              ? "Спросите о новости, рынке или материалах банка…"
                              : "Сначала подготовьте разбор"
                          }
                          value={question}
                          onChange={(e) => setQuestion(e.target.value)}
                          maxLength={1500}
                          disabled={!state || !boot.status.live_available}
                          rows={2}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              start("chat");
                            }
                          }}
                        />
                        <button
                          type="submit"
                          aria-label="Отправить вопрос"
                          disabled={
                            !question.trim() ||
                            !!busy ||
                            !state ||
                            !boot.status.live_available
                          }
                        >
                          <Send size={18} />
                        </button>
                      </form>
                      <small className="chat-disclaimer">
                        Ответы требуют проверки перед принятием решений.
                      </small>
                    </aside>
                  </div>
                  <button
                    className="mobile-chat-button"
                    onClick={() => setChatOpen(true)}
                  >
                    <MessageSquare size={19} />
                    Обсудить новость
                    <ArrowUpRight size={18} />
                  </button>
                </>
              )}
            </>
          ) : section === "feed" ? (
            <>
              <div className="page-kicker">
                <span>
                  <span className="status-dot green" />
                  ПЕРСОНАЛЬНАЯ ЛЕНТА
                </span>
                <span className="feed-tools"><span>Лента обновляется автоматически</span><button className="expert-toggle" aria-expanded={expertOpen} onClick={() => setExpertOpen(v => !v)}>Сценарий для эксперта</button></span>
              </div>
              {expertOpen && <ExpertScenario session={feed?.demo || demo} busy={demoBusy} error={demoError} onStart={startDemo} onStop={stopDemo}/>}
              <div className="hero">
                <div className="hero-copy">
                  <h1>
                    События рынка.
                    <br />
                    <span>Контекст вашего бизнеса.</span>
                  </h1>
                  <p>
                    Важные новости, их влияние на вашу компанию
                    <br className="desktop-break" /> и основания для решений — в
                    одном месте.
                  </p>
                  <div className="hero-profile">
                    <span>
                      <Building2 size={15} />
                      {shortIndustry(company)}
                    </span>
                    <i />
                    <span>
                      <MapPin size={15} />
                      {company?.region}
                    </span>
                  </div>
                </div>
                <button
                  className="hero-insight"
                  onClick={() => featured && setSelectedId(featured.id)}
                  disabled={!featured}
                >
                  <div className="hero-insight-top">
                    <span className="insight-symbol">
                      <Sparkles size={21} />
                    </span>
                    <span>СЕЙЧАС В ФОКУСЕ</span>
                    <ArrowUpRight size={22} />
                  </div>
                  <h2>
                    {featured
                      ? primaryTopic(featured)
                      : "Персональная аналитика"}
                  </h2>
                  <p>
                    {featured?.short_answer ||
                      featured?.brief?.short_answer ||
                      "Откройте новость, чтобы подготовить разбор влияния на ваш бизнес."}
                  </p>
                  <div className="hero-insight-bottom">
                    <span>Читать разбор</span>
                    <ArrowRight size={18} />
                  </div>
                </button>
              </div>
              <div className="section-heading">
                <div>
                  <h2>Ваша новостная повестка</h2>
                  <p>Подбор с учётом деятельности и связей компании</p>
                </div>
                <button
                  aria-label="Обновить ленту"
                  className="refresh-button"
                  onClick={() => {
                    loadBoot();
                    setReload((v) => v + 1);
                  }}
                  disabled={loading}
                >
                  <RefreshCw size={16} className={loading ? "spin" : ""} />
                  <span>Обновить</span>
                </button>
              </div>
              <div className="feed-controls">
                <div
                  className="segmented"
                  role="tablist"
                  aria-label="Лента новостей"
                >
                  {[
                    ["personal", "Для вас"],
                    ["all", "Все новости"],
                    ["saved", "Сохранённое"],
                  ].map(([key, label]) => (
                    <button
                      key={key}
                      role="tab"
                      aria-selected={mode === key}
                      onClick={() => setMode(key)}
                    >
                      {key === "saved" && <Bookmark size={14} />} {label}
                      {key === "all" && (
                        <span>{feed?.items.length || "—"}</span>
                      )}
                    </button>
                  ))}
                </div>
                <label className="search-field">
                  <Search size={18} />
                  <input
                    placeholder="Поиск по новостям"
                    aria-label="Поиск по новостям"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  {query && (
                    <button
                      aria-label="Очистить поиск"
                      onClick={() => setQuery("")}
                    >
                      <X size={16} />
                    </button>
                  )}
                </label>
              </div>
              <div className="filter-row">
                <SlidersHorizontal size={16} />
                <select
                  aria-label="Фильтр по теме"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                >
                  <option value="all">Все темы</option>
                  {availableTopics.map((t) => (
                    <option key={t} value={t}>
                      {topics[t] || t}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Фильтр по важности"
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                >
                  <option value="all">Любая важность</option>
                  <option value="high">Высокая</option>
                  <option value="medium">Средняя</option>
                  <option value="low">Низкая</option>
                  <option value="ready">С готовым разбором</option>
                </select>
                {(topic !== "all" || level !== "all" || query) && (
                  <button
                    className="reset"
                    onClick={() => {
                      setTopic("all");
                      setLevel("all");
                      setQuery("");
                    }}
                  >
                    Сбросить <X size={12} />
                  </button>
                )}
                <span className="result-count">
                  {filtered.length} публикаций
                </span>
              </div>
              {feed?.sync?.status === "running" && (
                <div className="link-sync-status" role="status">
                  <Loader2 className="spin" size={14} />
                  Обновляем связи и оцениваем важность новостей…
                </div>
              )}
              {feedError ? (
                <ErrorBox
                  message={feedError}
                  retry={() => setReload((v) => v + 1)}
                />
              ) : loading ? (
                <Skeleton />
              ) : !filtered.length ? (
                <div className="empty-state">
                  <Search size={28} />
                  <h3>
                    {mode === "saved"
                      ? "Здесь будут сохранённые новости"
                      : "По вашему запросу ничего не найдено"}
                  </h3>
                  <p>
                    {mode === "saved"
                      ? "Нажмите на закладку у новости, чтобы вернуться к ней позже."
                      : "Попробуйте другие слова или сбросьте фильтры."}
                  </p>
                  <Button
                    view="secondary"
                    size={40}
                    onClick={() => {
                      setQuery("");
                      setTopic("all");
                      setLevel("all");
                      setMode("personal");
                    }}
                  >
                    Вернуться к подборке
                  </Button>
                </div>
              ) : (
                <div className="news-grid">
                  {filtered.slice(0, visibleCount).map((card, i) => (
                    <article
                      className={
                        "news-card " +
                        (i === 0 && mode === "personal" ? "lead-card" : "")
                      }
                      key={card.id}
                    >
                      <div className="card-top">
                        <Badge
                          value={card.classification.importance}
                          status={card.link?.importance_status}
                        />
                        <button
                          className={
                            "icon-button " + (pairSaved(card.id) ? "saved" : "")
                          }
                          aria-label={
                            pairSaved(card.id)
                              ? "Убрать из сохранённого"
                              : "Сохранить новость"
                          }
                          onClick={() => toggle(companyId + ":" + card.id)}
                        >
                          <Bookmark
                            size={18}
                            fill={pairSaved(card.id) ? "currentColor" : "none"}
                          />
                        </button>
                      </div>
                      <div className="card-topic">
                        {card.is_demo && <b className="demo-label">Тестовая новость</b>}
                        {primaryTopic(card)}
                        {card.is_demo && !card.has_analysis && <span className="demo-processing">{!["failed", "not_matched", "not_business"].includes(card.demo_phase || "") && <Loader2 size={13} className="spin"/>}{card.demo_stage || "Обработка"}</span>}
                      </div>
                      <h3>
                        <button onClick={() => setSelectedId(card.id)}>
                          {card.title}
                        </button>
                      </h3>
                      {(card.short_answer || card.brief?.short_answer) && (
                        <div className="card-effect">
                          <span>ДЛЯ ВАШЕГО БИЗНЕСА</span>
                          <p>{card.short_answer || card.brief?.short_answer}</p>
                        </div>
                      )}
                      <div className="card-bottom">
                        <div className="news-meta">
                          <span className="publisher-dot">
                            {card.publisher[0]}
                          </span>
                          {safeUrl(card.url) ? (
                            <a
                              className="publisher-link"
                              href={safeUrl(card.url)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {card.publisher}
                              <ExternalLink size={12} />
                            </a>
                          ) : (
                            <span>{card.publisher}</span>
                          )}
                          <span>·</span>
                          <span>{date(card.published_at)}</span>
                        </div>
                        <button
                          className="card-link"
                          onClick={() => setSelectedId(card.id)}
                        >
                          Подробнее
                          <ArrowRight size={17} />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              {filtered.length > visibleCount && (
                <div className="show-more">
                  <Button
                    view="secondary"
                    size={48}
                    onClick={() => setVisibleCount((n) => n + 8)}
                  >
                    Показать ещё {Math.min(8, filtered.length - visibleCount)}{" "}
                    <ChevronDown size={16} />
                  </Button>
                </div>
              )}
              <div className="feed-footnote">
                <ShieldCheck size={16} />
                <p>
                  Связи на {feed?.matching_as_of || "22.10.2026"}. Важность
                  оценивается отдельно для каждой найденной связи и уточняется
                  после полного разбора. Сходство публикаций само по себе не
                  доказывает влияние.
                </p>
              </div>
            </>
          ) : section === "bank" ? (
            <>
              <div className="page-kicker">
                <span>ИССЛЕДОВАНИЯ И ОБЗОРЫ</span>
                <span>Альфа-Банк</span>
              </div>
              <div className="page-heading">
                <h1>
                  Больше контекста.
                  <br />
                  <span>Точнее решения.</span>
                </h1>
                <p>Материалы банка, которые помогают понять события рынка.</p>
              </div>
              <div className="bank-summary">
                <div>
                  <b>{boot.documents.length}</b>
                  <span>материалов в базе</span>
                </div>
                <div>
                  <b>{bankSources.length}</b>
                  <span>фрагментов в готовых разборах</span>
                </div>
                <div className="bank-summary-note">
                  <ShieldCheck size={23} />
                  <p>
                    В разбор попадают только найденные основания. Дата и
                    источник сохраняются.
                  </p>
                </div>
              </div>
              <label className="search-field bank-search">
                <Search size={18} />
                <input
                  aria-label="Поиск материалов банка"
                  placeholder="Найти обзор: ставка, потребление, инфляция…"
                  value={bankQuery}
                  onChange={(e) => setBankQuery(e.target.value)}
                />
                {bankQuery && (
                  <button
                    aria-label="Очистить поиск материалов"
                    onClick={() => setBankQuery("")}
                  >
                    <X size={16} />
                  </button>
                )}
              </label>
              {bankError && <ErrorBox message={bankError} />}
              <div className="document-grid">
                {boot.documents
                  .filter((d) =>
                    (
                      d.title +
                      " " +
                      (d.subtitle || "") +
                      " " +
                      d.tags.join(" ")
                    )
                      .toLowerCase()
                      .includes(bankQuery.toLowerCase()),
                  )
                  .map((doc) => (
                    <article className="document-card" key={doc.id}>
                      <div className="document-top">
                        <div className="document-icon">
                          <FileText size={24} />
                        </div>
                        <span>{date(doc.published_at, true)}</span>
                      </div>
                      <div className="document-tags">
                        {doc.tags.slice(0, 2).map((t: string) => (
                          <span key={t}>{t}</span>
                        ))}
                      </div>
                      <h2>{doc.title}</h2>
                      <p>{doc.subtitle || "Аналитический обзор Альфа-Банка"}</p>
                      <div className="document-footer">
                        <span>
                          {docSources(doc).length
                            ? "Есть фрагменты в разборах"
                            : "Включён в поисковую базу"}
                        </span>
                        <button
                          className="icon-button"
                          aria-label={"Подробнее: " + doc.title}
                          aria-expanded={expandedDoc === doc.id}
                          onClick={() =>
                            setExpandedDoc(
                              expandedDoc === doc.id ? undefined : doc.id,
                            )
                          }
                        >
                          {expandedDoc === doc.id ? (
                            <X size={18} />
                          ) : (
                            <ArrowUpRight size={20} />
                          )}
                        </button>
                      </div>
                      {expandedDoc === doc.id && (
                        <div className="document-excerpts">
                          <small>{doc.source_name}</small>
                          {documentError ? (
                            <ErrorBox message={documentError} />
                          ) : !documentData ? (
                            <p className="document-loading">
                              <Loader2 className="spin" size={15} />
                              Загружаем текст…
                            </p>
                          ) : documentData.chunks.length ? (
                            <>
                              <p>
                                {documentData.chunks.length} текстовых
                                фрагментов · извлечено из PDF
                              </p>
                              <div className="document-scroll">
                                {documentData.chunks.map(
                                  (chunk: Obj, i: number) => (
                                    <details key={chunk.id}>
                                      <summary>
                                        <span>
                                          {chunk.section_path
                                            ?.filter(Boolean)
                                            .join(" / ") ||
                                            "Фрагмент " + (i + 1)}
                                          {chunk.pages?.length
                                            ? " · стр. " +
                                              chunk.pages.join(", ")
                                            : ""}
                                        </span>
                                        <ChevronDown size={14} />
                                      </summary>
                                      <pre>{chunk.text}</pre>
                                    </details>
                                  ),
                                )}
                              </div>
                              <p className="small muted">
                                Распознанный текст может содержать ошибки OCR.
                                Данные графиков и таблиц требуют сверки с
                                оригиналом.
                              </p>
                            </>
                          ) : docSources(doc).length ? (
                            docSources(doc).map((source) => (
                              <details key={source.source_id}>
                                <summary>
                                  {source.title}
                                  <ChevronDown size={14} />
                                </summary>
                                <pre>{source.text}</pre>
                              </details>
                            ))
                          ) : (
                            <p>
                              Текст материала сейчас недоступен. Проверьте
                              подключение базы.
                            </p>
                          )}
                        </div>
                      )}
                    </article>
                  ))}
              </div>
              {!boot.documents.some((d) =>
                (d.title + " " + (d.subtitle || "") + " " + d.tags.join(" "))
                  .toLowerCase()
                  .includes(bankQuery.toLowerCase()),
              ) && (
                <div className="empty-state">
                  <Search />
                  <h3>Материал не найден</h3>
                  <p>Попробуйте другую тему.</p>
                </div>
              )}
              <div className="feed-footnote">
                <CircleHelp size={17} />
                <p>
                  Обзоры отражают позицию на дату публикации. Поиск здесь
                  фильтрует каталог; новые разборы ищут контекст по всей
                  загруженной базе фрагментов.
                </p>
              </div>
            </>
          ) : (
            <>
              <div className="page-kicker">
                <span>ПРОФИЛЬ ДЛЯ ПЕРСОНАЛИЗАЦИИ</span>
                <span>{companyId}</span>
              </div>
              <div className="page-heading">
                <h1>
                  Контекст
                  <br />
                  <span>вашей компании.</span>
                </h1>
                <p>Эти данные используются при подборе и разборе новостей.</p>
              </div>
              {company && (
                <div className="profile-grid">
                  <section className="panel company-profile">
                    <div className="company-big-icon">
                      <Building2 size={30} />
                    </div>
                    <span className="eyebrow">КОМПАНИЯ {company.id}</span>
                    <h2>{shortIndustry(company)}</h2>
                    <p>{company.industry}</p>
                    <div className="context-row">
                      <span>ОКВЭД</span>
                      <b>{company.okved}</b>
                    </div>
                    <div className="context-row">
                      <span>Регион регистрации</span>
                      <b>{company.region}</b>
                    </div>
                    <div className="context-row">
                      <span>Годовая выручка</span>
                      <b>{money(company.revenue_rub)}</b>
                    </div>
                    <div className="context-row">
                      <span>Стадия бизнеса</span>
                      <b>{company.stage || "Не указана"}</b>
                    </div>
                    <p className="muted small">
                      Юридические названия не переданы. Для выбора используется
                      идентификатор из набора компаний.
                    </p>
                  </section>
                  <div>
                    <section className="panel">
                      <div className="section-icon">
                        <Wallet size={20} />
                        <h2>Банковские сервисы</h2>
                      </div>
                      <div className="service-tags">
                        {company.services.map((s) => (
                          <span key={s}>
                            <Check size={14} />
                            {serviceNames[s] || s}
                          </span>
                        ))}
                      </div>
                    </section>
                    <section className="panel">
                      <div className="section-icon">
                        <MapPin size={20} />
                        <h2>Внешнеторговые связи</h2>
                      </div>
                      <p>
                        {company.countries.length
                          ? company.countries
                              .map(
                                (s) => s.charAt(0) + s.slice(1).toLowerCase(),
                              )
                              .join(" · ")
                          : "Страны не указаны"}
                      </p>
                      <p className="muted small">
                        Направление торговли и объёмы не установлены.
                      </p>
                    </section>
                    <section className="panel profile-limits">
                      <h2>Что учитывать</h2>
                      <p>
                        Год выручки и период агрегатов платежей не указаны.
                        Регистрация не определяет место деятельности. Платежная
                        связь не доказывает роль поставщика или покупателя.
                      </p>
                    </section>
                  </div>
                  <Payments company={company} />
                </div>
              )}
            </>
          )}
        </main>
        <footer className="site-footer">
          <span>Альфа-Бизнес · Персональная аналитика</span>
          <span>Не является финансовой рекомендацией</span>
        </footer>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
