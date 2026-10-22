# Пайплайн данных компаний

Модуль `app/modules/companies` загружает снимок `docs/companies/companies_analytics.json`, проверяет его по структуре из [JSON_STRUCTURE.md](companies/JSON_STRUCTURE.md), сохраняет группы, компании и платежную аналитику в PostgreSQL и строит по одной E5-эмбеддинг-профилю на компанию для поиска соответствий с новостями.

## Запуск через Docker Compose

```sh
docker compose --profile pipeline up -d postgres
docker compose --profile pipeline build companies
docker compose --profile pipeline run --rm companies db upgrade
docker compose --profile pipeline run --rm companies import
docker compose --profile pipeline run --rm companies export --format ai --output /runtime/companies-ai.json
docker compose --profile pipeline run --rm companies embed
docker compose --profile pipeline run --rm companies search "рост цен на автозапчасти" --top-k 5
```

`import` не требует embedding-модели. Первый `embed` скачивает локальную `intfloat/multilingual-e5-small`; `search` использует ту же модель для вектора запроса. `companies` использует те же PostgreSQL, volume для модели и runtime-каталог, что и новостной сервис.

## Запуск Python без контейнера

Python 3.12+:

```sh
python -m pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg://alfa_news:local-news-development-only@localhost:5433/alfa_news'
python -m app db upgrade
python -m app companies import
python -m app companies embed
python -m app companies search "рост цен на автозапчасти" --top-k 5
```

Также доступен `python -m app.modules.companies ...`.

## Команды

| Команда | Назначение |
|---|---|
| `db upgrade` | Применить общую историю Alembic, включая `0004_companies`. |
| `import` / `load` | Проверить JSON и сделать upsert групп и компаний. `--dry-run` проверяет без БД. |
| `export --format ingestion` | Выгрузить нормализованные компании в структуре исходного JSON. |
| `export --format ai` | Выгрузить профили, совместимые с `research/ai/contracts.py::CompanyProfile`. |
| `embed` | Рассчитать недостающие или устаревшие профильные векторы. |
| `search "текст"` | Найти компании, ближайшие к тексту новости. |
| `get COMPANY_ID` | Показать полный сохраненный профиль компании. |

Пути и отчеты:

- `--data` по умолчанию указывает на `docs/companies/companies_analytics.json`;
- отчет импорта по умолчанию — `../local_runtime/companies/import-report.json`;
- отчет эмбеддингов — `../local_runtime/companies/embedding-report.json`;
- `COMPANIES_RUNTIME_DIR` меняет каталог отчетов;
- `--profile` выбирает сохраненный embedding-профиль, если их несколько.

## Таблицы

| Таблица | Содержимое |
|---|---|
| `company_groups` | Три выбранные группы: ранжирование, преобладающий ОКВЭД, регион, число связей и полный `details`. |
| `companies` | Компания: ОКВЭД, регион, город, выручка, стадия, банковские услуги, платежная аналитика в `details`, `profile_text` и `content_hash`. |
| `company_import_runs` | История импорта: время, статус и полный отчет. |
| `company_embedding_profiles` | Модель, immutable revision, размерность, нормализация и версия подготовки текста. |
| `company_embeddings` | Один вектор `vector(384)` на компанию и профиль, `token_count`, признак усечения и HNSW-индекс. |

Повторный импорт делает upsert по `company_id` и `group_id`. Если `profile_text` изменился, `content_hash` меняется, а триггер `company_text_change` удаляет старые векторы компании. Следующий `embed` пересчитывает только их. Импорт не удаляет строки, которых больше нет в JSON: снимок рассматривается как источник обновлений, а не как полная замена таблицы. Для полной синхронизации нужна отдельная явная операция.

## Текстовый профиль и эмбеддинги

`profile_text` — детерминированный текст на русском языке. В начале идут наиболее различимые признаки:

1. основной ОКВЭД и раздел;
2. регион и город регистрации, форма собственности;
3. выручка, стадия развития, страны внешней торговли;
4. банковские услуги;
5. оборот, число контрагентов и связей, концентрация;
6. топ-3 отрасли и регионы контрагентов;
7. крупнейшие внешние контрагенты и двусторонние связи.

Платежная аналитика добавлена как косвенный сигнал отраслевой и региональной экспозиции: компания может быть зарегистрирована в одном регионе, но работать преимущественно с контрагентами из других отраслей и регионов. Это соответствует ограничениям из `research/data/D03.md`: направление платежа не доказывает роль контрагента, а концентрация не доказывает экономическую зависимость.

Подготовка `e5-company-profile-v1` использует `passage:` + `Компания <id>` + до 384 токенов профиля. Если профиль не помещается в контекст 512 токенов, хвост усекается; `token_count` и `truncated` сохраняются для диагностики. Вектор L2-нормализован и хранится в `company_embeddings.vector`.

Запрос новости кодируется через `query:` тем же провайдером. `CompanySearchService` возвращает `company_id`, группу, ОКВЭД, город, регион, выручку, `profile_text` и `similarity = 1 - cosine distance`. Similarity — техническая близость, а не вероятность влияния новости на компанию.

## Контракты и ограничения

`export --format ai` отдает поля `CompanyProfile`: `id`, `provenance=dataset`, `source_ref`, `okved_codes`, `okved_names`, `registration_region`, `ownership_form`, `annual_revenue_rub`, `banking_services`, `trade_countries`, `development_stage`. Названия банковских услуг приводятся к кодам исследовательских fixtures: `cash_settlement_rko → cash_register`, `loans → credit`, `deposits → deposit`, `salary_project → payroll`; `leasing`, `factoring` и `bank_guarantees` совпадают. Пустой список стран торговли экспортируется как `null`, потому что отсутствие данных не означает отсутствие экспорта.

Снимок содержит только 3 группы и 12 компаний. Это не полная база клиентов банка. Платежные агрегаты не содержат дат, поэтому динамика, сезонность и средний интервал между платежами не рассчитываются. Названия компаний в снимке отсутствуют: идентификатор — `SYNTHETIC_U`. Отсутствие страны торговли не доказывает отсутствие экспорта, стадия развития не восстанавливается по выручке, а банковские услуги не определяют бизнес-модель.

## Тесты

```sh
python -m unittest discover -s tests/companies -v
```

PostgreSQL-тесты включаются только для отдельной disposable БД с именем, оканчивающимся на `_test`:

```sh
docker compose --profile pipeline exec -T postgres createdb -U alfa_news alfa_companies_test
docker compose --profile pipeline run --rm -e DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@postgres:5432/alfa_companies_test companies db upgrade
docker compose --profile pipeline run --rm \
  -e COMPANY_TEST_DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@postgres:5432/alfa_companies_test \
  --entrypoint python companies -m unittest discover -s tests/companies -v
```

Тесты покрывают структуру реального снимка, детерминированность профиля, импорт и dry-run, AI-экспорт по сохраненной JSON Schema, усечение по бюджету токенов, ошибку провайдера без сохранения векторов, upsert, инвалидирование, изоляцию профилей и поиск в PostgreSQL.
