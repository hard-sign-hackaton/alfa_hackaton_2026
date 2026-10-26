# Альфа Хак 2026 — персонализированная новостная аналитика

Сервис связывает внешние новости, контекст компании и аналитические материалы Альфа-Банка. В этой ветке реализованы сбор новостей, их хранение, эмбеддинги и векторный поиск. Исследовательский AI-модуль, UX-прототип и контракты находятся отдельно; объединенный продуктовый backend пока не реализован.

## Быстрый запуск
Пайплайн запуска находится в файле `run_pipeline.sh`. Он запускает сбор новостей за последние 15 дней, и так же загружует несколько заранее отобранных компаний и новостей в демонстрационных целях. Работа пайплайна может занимать некоторое время, в зависимости от хост-машины, так как происходит обработка данных. Веб-интерфейс будет доступен по адресу `localhost:8080`.
 
## Экспертный сценарий 
1. Выбираем группу компаний (справа сверху, аватарка).
2. Выбираем компанию (справа сверху, выпадающий список).
3. В ленте покажутся новости, относящиеся к выбранной компании, с оценкой их важности. Для каждой новости есть краткая аналитика.
4. В ленте справа сверху есть кнопка "Сценарий для эксперта". Эта кнопка запускает демонстрационный сценарий того, как новости появляются в системе. Внутри меню сценария есть описание его работы.
5. Выбираем любую новость и проходим в подробности. Если новость появилась недавно, и для нее еще не готова аналитика - нужно запустить анализ и подождать какое-то время. Во время анализа можно изучить другие новости - анализ происходит на фоне.
6. Внутри новости во вкладке "разбор" есть аналитика системы, аналитика из материалов Альфа-Банка, а так же указания контекста: почему эта новость влияет на деятельность компании. Для каждого пункта аналитики в выпадающем меню можно посмотреть основания сделанных выводов.
7. В самом низу страницы есть возможность оценить аналитику.
8. Если анализ показался неполным, есть возможность задать вопросы в чате с ИИ. В этом чате учитываются все материалы страницы, а так же предложен список быстрых вопросов. 
9. Во вкладке "новость" можно прочитать текст оригинальной новости или перейти к источнику.
10. Во вкладке "источники" можно узнть все данные, которые использовались для подбора новости и создания аналитики: текст новости, данные о компании, материалы Альфа-Банка.
11. Слева в навигационной панели можно перейти на вкладку "Аналитика Альфа-Банка". В ней указаны все аналитические материалы, использующиеся в работе системы.
12. В навигационной панели во вкладке "Моя компания" можно найти всю информацию о компании, которая используется для работы системы.

## Навигация

| Каталог / файл | Назначение |
| --- | --- |
| [app/__main__.py](app/__main__.py) | `python -m app`: общий `db upgrade` и CLI новостей, компаний и аналитики |
| [app/shared/db](app/shared/db/) | SQLAlchemy Base, Engine, фабрика сессий и запуск Alembic-миграций |
| [app/shared/embeddings](app/shared/embeddings/) | Интерфейс embedding-провайдера и локальная E5; общая для новостей, компаний и аналитики |
| [app/modules/news](app/modules/news/) | Новости: DTO, парсеры, гибридная дедупликация, ORM-модели, репозитории, сервисы и CLI |
| [app/modules/companies](app/modules/companies/) | Компании: импорт JSON-снимка, профили, эмбеддинги, поиск и CLI |
| [app/modules/analytics](app/modules/analytics/) | Банковская аналитика: документы, чанки, таблицы, эмбеддинги и поиск |
| [app/modules/links](app/modules/links/) | Связи новость—компания: подбор, важность, статусы и сохранённые разборы |
| [app/modules/feedback](app/modules/feedback/) | Оценки полезности разборов и версии анализа |
| [app/web](app/web/) | Same-origin HTTP API, фоновая синхронизация связей, чат, экспертный сценарий и отраслевые профили |
| [frontend](frontend/) | React/Vite-интерфейс: `main.tsx` — лента, карточка и чат; `ExpertScenario.tsx` — сценарий; `AnalysisFeedback.tsx` — оценки |
| [migrations](migrations/) и [alembic.ini](alembic.ini) | Общая история изменений схемы PostgreSQL |
| [database/seeds](database/seeds/) | SQL-снимок стартовых данных (новости, компании, банк, связи, legacy) и `manifest.json` |
| [run_pipeline.sh](run_pipeline.sh) | Запуск на чистой машине: web/data-init, затем сбор новостей и расчёт эмбеддингов |
| [compose.yaml](compose.yaml) | PostgreSQL, web, news/companies/analytics CLIs, data-init, news-db-init и тестовые профили |
| [Dockerfile](Dockerfile) | Образ `data-init`, `news-db-init` и исследовательских сервисов |
| [Dockerfile.news](Dockerfile.news) | Образы news/companies/analytics, web и семантического агента |
| [requirements.txt](requirements.txt) | Python-зависимости приложения; тесты дополнительно используют requirements исследовательских модулей |
| [scripts/load_startup_data.py](scripts/load_startup_data.py) | Восстановление seeds, догрузка банка/компаний и готовых разборов |
| [scripts/export_startup_data.py](scripts/export_startup_data.py) | Экспорт согласованного SQL-снимка из работающих БД |
| [scripts/init_news_reader.py](scripts/init_news_reader.py) | Миграции и роли чтения/записи для основной БД |
| [scripts/precompute_analyses.py](scripts/precompute_analyses.py) | Пакетный предрасчёт полных разборов и кратких сводок |
| [scripts/restore_news_dump.py](scripts/restore_news_dump.py) | Загрузка дампа из файла или по HTTPS в отдельную пустую БД |
| [docs/startup-data.md](docs/startup-data.md) | Стартовые SQL-снимки, поведение `data-init` и ограничения |
| [docs/web.md](docs/web.md) | Запуск web, API, модели, связи и ограничения |
| [docs/expert-scenario.md](docs/expert-scenario.md) | Общий сценарий тестовых новостей и фактическая обработка |
| [docs/analysis-feedback.md](docs/analysis-feedback.md) | Хранение, API и метрики оценок разборов |
| [docs/companies-pipeline.md](docs/companies-pipeline.md) | Импорт, профили, эмбеддинги и поиск компаний |
| [docs/news-company-links.md](docs/news-company-links.md) | Связи, важность, фоновые обновления и роли БД |
| [docs/news-pipeline.md](docs/news-pipeline.md) | Подробный запуск новостного пайплайна, параметры и ограничения |
| [docs/news-deduplication.md](docs/news-deduplication.md) | Гибридная дедупликация новостей |
| [docs/matching-improvements.md](docs/matching-improvements.md) | Подбор компаний и улучшение качества связей |
| [docs/news-agent-integration.md](docs/news-agent-integration.md) | Подключение новостей и компаний к исследовательскому агенту |
| [docs/bank-agent-integration.md](docs/bank-agent-integration.md) | Банковские источники в исследовании компании |
| [docs/chat-retrieval.md](docs/chat-retrieval.md) | RAG-поиск и ограничения чата |
| [docs/precomputed-analysis.md](docs/precomputed-analysis.md) | Предрасчёт разборов, обновление банковского контекста и экспорт |
| [docs/analytics-storage.md](docs/analytics-storage.md) | Схема, манифест, импорт PDF/чанков, эмбеддинги и поиск аналитики |
| [docs/news-database-handoff.md](docs/news-database-handoff.md) | Передача дампа, восстановление и подключение AI-части |
| [docs/companies](docs/companies/) | Снимок компаний и описание его JSON-структуры |
| [docs/test-tours](docs/test-tours/) | Пользовательские тест-туры: сквозные сценарии от лица руководителей крупного бизнеса |
| [docs/test-tours/00-full-walkthrough.md](docs/test-tours/00-full-walkthrough.md) | Большой тест-тур: показывает основной функционал приложения |
| [docs/archive](docs/archive/) | Архив первых прогонов и проверок раскладки |
| [docs/news-pgvector-checks.json](docs/news-pgvector-checks.json) | Проверки текущего поиска через PostgreSQL |
| [research/news](research/news/) | Исходное исследование N01/N02: проверки источников, сохранённые материалы и первый сборщик |
| [research/ai](research/ai/) | Исследовательский агент, ранжирование, модели входов/выходов и эксперименты |
| [research/bank](research/bank/) | Извлечение PDF и подготовка чанков банковской аналитики |
| [research/contracts](research/contracts/) | JSON Schema, примеры и валидаторы контрактов |
| [research/contracts/t01](research/contracts/t01/) | Границы AI/UX, адаптер сборки и проверки совместимости |
| [research/data](research/data/) | Результаты исследования данных компаний и связей |
| [research/ux](research/ux/) | UX-прототип и материалы его проверки |
| [research/evaluation](research/evaluation/) | Сохранённые результаты оценки и сравнительных прогонов |
| [tests/news](tests/news/) | Проверки слоёв, парсеров, дедупликации, PostgreSQL и индексов |
| [tests/companies](tests/companies/) | Архитектура, импорт, эмбеддинги и поиск компаний |
| [tests/analytics](tests/analytics/) | Проверки импорта, чанков, PostgreSQL и поиска аналитики |
| [tests/links](tests/links/) | Репозиторий и сервис связей |
| [tests/feedback](tests/feedback/) | PostgreSQL-проверки оценок разборов |
| [tests/web](tests/web/) | API, лента, чат, экспертный сценарий и обратная связь |
| [tests/startup](tests/startup/) | Снимки, восстановление и предрасчёт разборов |
| [news_pipeline](news_pipeline/) | Совместимый переходник старой CLI-команды; реализация в `app/modules/news` |

В приложении реализован сквозной путь от сбора новостей до веб-интерфейса: новости, компании, банковская аналитика, связи и важность, полные разборы, чат, оценки и экспертный сценарий. Стартовый снимок восстанавливает `data-init`; HTTP API и фоновая обработка находятся в `app/web`, интерфейс — в `frontend`.

## Структура приложения

```text
app/
├── __main__.py
├── shared/
│   ├── config.py
│   ├── files.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── migrations.py
│   └── embeddings/
│       ├── provider.py
│       └── e5.py
├── modules/
│   ├── news/
│   │   ├── __main__.py
│   │   ├── bootstrap.py
│   │   ├── cli.py
│   │   ├── config.py
│   │   ├── deduplication.py
│   │   ├── dto.py
│   │   ├── identity.py
│   │   ├── models.py
│   │   ├── normalization.py
│   │   ├── repositories.py
│   │   ├── parsers/
│   │   │   ├── base.py
│   │   │   ├── discovery.py
│   │   │   ├── http.py
│   │   │   ├── interfax.py
│   │   │   ├── kommersant.py
│   │   │   ├── registry.py
│   │   │   └── vedomosti.py
│   │   └── services/
│   │       ├── deduplication.py
│   │       ├── embedding.py
│   │       ├── export.py
│   │       ├── ingestion.py
│   │       └── search.py
│   ├── companies/
│   │   ├── __main__.py
│   │   ├── bootstrap.py
│   │   ├── cli.py
│   │   ├── config.py
│   │   ├── dto.py
│   │   ├── identity.py
│   │   ├── models.py
│   │   ├── normalization.py
│   │   ├── profiling.py
│   │   ├── repositories.py
│   │   └── services/
│   │       ├── embedding.py
│   │       ├── export.py
│   │       ├── ingestion.py
│   │       └── search.py
│   ├── analytics/
│   │   ├── __main__.py
│   │   ├── bootstrap.py
│   │   ├── cli.py
│   │   ├── config.py
│   │   ├── dto.py
│   │   ├── identity.py
│   │   ├── manifest.py
│   │   ├── models.py
│   │   ├── repositories.py
│   │   └── services/
│   │       ├── chunk_import.py
│   │       ├── embedding.py
│   │       ├── importing.py
│   │       └── search.py
│   ├── links/
│   │   ├── __main__.py
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── service.py
│   └── feedback/
│       ├── models.py
│       └── repository.py
└── web/
    ├── __main__.py
    ├── expert_demo.py
    ├── expert_news.py
    ├── expert_pipeline.py
    ├── profiles.py
    └── server.py
```

```text
frontend/
├── index.html
├── package.json
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── tsconfig.json
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── ExpertScenario.tsx
    ├── AnalysisFeedback.tsx
    ├── config.ts
    └── style.css
```

Сценарий загрузки: **HTTP/RSS/sitemap → парсер → ParsedArticle → нормализация → NewsArticleDTO → сервис → репозиторий → SQLAlchemy ORM → PostgreSQL**. Парсер допускает пропуски в результате извлечения; нормализация проверяет пригодность публикации к сохранению и назначает ID. DTO не является ORM-моделью и не удерживает сессию БД.

`NewsRepository` хранит источники, статьи и историю сборов; `save_deduplicated` проверяет дубли по тексту и эмбеддингам. `NewsEmbeddingRepository` хранит профили и векторы. `NewsEmbeddingService` отвечает за подготовку именно новости и пересчёт устаревших векторов; общий `E5Provider` — за токенизацию и выполнение модели. `NewsSearchService` связывает запрос, embedding-провайдер и поиск через репозиторий PostgreSQL.

`app/modules/companies` импортирует снимок `docs/companies/companies_analytics.json`: `CompanyImportService` валидирует данные и делает upsert, `CompanyEmbeddingService` строит E5-профиль компании, `CompanySearchService` ищет компании по тексту новости, `CompanyExportService` выгружает нормализованный или AI-совместимый профиль.

`app/modules/analytics` принимает результат `research/bank/extract_pdf.py` и `prepare_chunks.py`: документ, Markdown, чанки и таблицы. `AnalyticsImportService` и `ChunkFileImportService` выполняют идемпотентный импорт, `AnalyticsEmbeddingService` считает векторы на уровне чанка, `AnalyticsSearchService` ищет по сохранённым материалам. Схема и команды описаны в [docs/analytics-storage.md](docs/analytics-storage.md).

`app/modules/links` хранит пары `(news_id, company_id)` в `news_company_links`: `LinkRepository` отвечает за актуальность, важность и результаты разбора, `LinkService` классифицирует новости, подбирает компании и оценивает важность. Фоновый обработчик в `app/web` обновляет связи при старте и каждые `LINKS_SYNC_SECONDS`.

`app/modules/feedback` хранит анонимные оценки версий разбора: `FeedbackRepository` связывает компанию, новость, версию анализа и идентификатор браузера, не сохраняя имена и контакты.

`app/web` — same-origin HTTP API и фоновая обработка: `bootstrap`, лента, разбор, чат, задания, оценки, банковские источники и экспертный сценарий. `profiles.py` группирует компании по отраслям для навигации; `expert_demo.py`, `expert_news.py` и `expert_pipeline.py` моделируют поступление тестовых новостей и проводят их через обычные сохранение, дедупликацию, подбор и разбор. `frontend` на React/Vite отображает ленту, карточку новости с вкладками, чат, профили, сценарий и оценки.

Стартовый SQL-набор в `database/seeds` восстанавливает `data-init`: новости, компании, банковскую аналитику, связи, оценки важности и готовые разборы. Повторный запуск сохраняет существующие данные и догружает только пустые справочные группы; подробности — в [docs/startup-data.md](docs/startup-data.md).
