# Альфа Хак 2026 — персонализированная новостная аналитика

Сервис связывает внешние новости, контекст компании и аналитические материалы Альфа-Банка. В этой ветке реализованы сбор новостей, загрузка компаний, их хранение, эмбеддинги и векторный поиск. Исследовательский AI-модуль, UX-прототип и контракты находятся отдельно; объединенный продуктовый backend пока не реализован.

## Навигация

| Каталог / файл | Назначение |
|---|---|
| [app/shared/db](app/shared/db/) | Общие SQLAlchemy Base, Engine, фабрика сессий и запуск миграций |
| [app/shared/embeddings](app/shared/embeddings/) | Интерфейс embedding-провайдера и локальная E5; без зависимостей от новостей и БД |
| [app/modules/news](app/modules/news/) | Прикладной модуль новостей: DTO, парсеры, ORM-модели, репозитории, сервисы и CLI |
| [app/modules/companies](app/modules/companies/) | Прикладной модуль компаний: DTO, нормализация, ORM-модели, импорт, эмбеддинги, поиск и CLI |
| [migrations](migrations/) и [alembic.ini](alembic.ini) | Общая история изменений схемы PostgreSQL |
| [tests/news](tests/news/) | Проверки слоев, парсеров, сервисов, PostgreSQL, индексов и совместимости |
| [tests/companies](tests/companies/) | Проверки структуры данных компаний, импорта, профилей, PostgreSQL и векторов |
| [docs/companies/companies_analytics.json](docs/companies/companies_analytics.json) | Снимок компаний, групп и платежной аналитики для MVP |
| [docs/companies/JSON_STRUCTURE.md](docs/companies/JSON_STRUCTURE.md) | Описание структуры снимка компаний |
| [research/news](research/news/) | Исходное исследование N01/N02: проверки источников, сохраненные материалы и первый сборщик |
| [research/ai](research/ai/) | Исследовательский агент, ранжирование, модели входов/выходов и эксперименты |
| [research/contracts](research/contracts/) | JSON Schema, примеры и валидаторы контрактов |
| [research/contracts/t01](research/contracts/t01/) | Границы AI/UX, адаптер сборки и проверки совместимости |
| [research/data](research/data/) | Результаты исследования данных компаний и связей |
| [research/ux](research/ux/) | UX-прототип и материалы его проверки |
| [docs/news-pipeline.md](docs/news-pipeline.md) | Подробный запуск новостного пайплайна, параметры и ограничения |
| [docs/companies-pipeline.md](docs/companies-pipeline.md) | Запуск импорта компаний, построение профилей, эмбеддинги и поиск |
| [docs/news-database-handoff.md](docs/news-database-handoff.md) | Передача дампа коллеге, восстановление и подключение AI-части |
| [scripts/restore_news_dump.py](scripts/restore_news_dump.py) | Загрузка дампа из файла или по HTTPS в отдельную пустую БД |
| [docs/archive/news-pipeline-checks.json](docs/archive/news-pipeline-checks.json) | Первый живой прогон, модель и контрольная поисковая выдача |
| [docs/archive/news-layout-checks.json](docs/archive/news-layout-checks.json) | Проверки после разделения на слои |
| [docs/news-pgvector-checks.json](docs/news-pgvector-checks.json) | Проверки текущего поиска через PostgreSQL |
| [compose.yaml](compose.yaml) | PostgreSQL, CLI новостей и компаний, исследовательские сервисы |
| [Dockerfile.news](Dockerfile.news) | Образ приложения с модулями новостей и компаний |
| [Dockerfile](Dockerfile) | Существующий образ исследовательских экспериментов |
| [requirements.txt](requirements.txt) | Зависимости приложения; для регрессионных тестов также нужны requirements исследовательских модулей |
| [news_pipeline](news_pipeline/) | Совместимый переходник старой CLI-команды; реализации здесь больше нет |

Модуль компаний реализован в `app/modules/companies/` и использует общие `app/shared/db` и `app/shared/embeddings`. Банковские аналитические материалы пока не подключены.

## Структура приложения

```text
app/
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
└── modules/
    ├── news/
    │   ├── dto.py
    │   ├── identity.py
    │   ├── normalization.py
    │   ├── models.py
    │   ├── repositories.py
    │   ├── bootstrap.py
    │   ├── config.py
    │   ├── cli.py
    │   ├── parsers/
    │   │   ├── base.py
    │   │   ├── http.py
    │   │   ├── discovery.py
    │   │   ├── registry.py
    │   │   ├── kommersant.py
    │   │   ├── vedomosti.py
    │   │   └── interfax.py
    │   └── services/
    │       ├── ingestion.py
    │       ├── export.py
    │       ├── embedding.py
    │       └── search.py
    └── companies/
        ├── dto.py
        ├── identity.py
        ├── normalization.py
        ├── profiling.py
        ├── models.py
        ├── repositories.py
        ├── bootstrap.py
        ├── config.py
        ├── cli.py
        └── services/
            ├── ingestion.py
            ├── export.py
            ├── embedding.py
            └── search.py
```

Сценарий загрузки новостей: **HTTP/RSS/sitemap → парсер → ParsedArticle → нормализация → NewsArticleDTO → сервис → репозиторий → SQLAlchemy ORM → PostgreSQL**. Парсер допускает пропуски в результате извлечения; нормализация проверяет пригодность публикации к сохранению и назначает ID. DTO не является ORM-моделью и не удерживает сессию БД.

`NewsRepository` хранит источники, статьи и историю сборов. `NewsEmbeddingRepository` хранит профили и векторы. `NewsEmbeddingService` отвечает за подготовку именно новости и пересчет устаревших векторов; общий `E5Provider` — за токенизацию и выполнение модели. `NewsSearchService` связывает запрос, embedding-провайдер и поиск через репозиторий PostgreSQL.

Сценарий загрузки компаний: **JSON-снимок → Pydantic-валидация → нормализация и текстовый профиль → CompanyRepository → SQLAlchemy ORM → PostgreSQL → CompanyEmbeddingService → pgvector**. Сохраняются группы, компании, платежная аналитика и исходный нормализованный payload. `profile_text` собирает ОКВЭД, регион, выручку, банковские услуги, страны торговли, отрасли и географию контрагентов. `CompanySearchService` ищет компании по произвольному тексту новости через тот же E5-провайдер.

## Быстрый запуск

Нужны Docker Engine и Compose. Из корня репозитория:

```sh
docker compose --profile pipeline up -d postgres
docker compose --profile pipeline build news
docker compose --profile pipeline run --rm news db upgrade
docker compose --profile pipeline run --rm news collect --days 15 --limit 50
docker compose --profile pipeline run --rm news export --format ai --output /runtime/ai-news.json
docker compose --profile pipeline run --rm news embed
docker compose --profile pipeline run --rm news search "цены на нефть и топливо" --top-k 5
docker compose --profile pipeline run --rm companies import
docker compose --profile pipeline run --rm companies embed
docker compose --profile pipeline run --rm companies search "рост цен на автозапчасти" --top-k 5
```

Собираются все новости трех источников без категорийного фильтра. Сайты работают в трех отдельных потоках. `--limit 50` ограничивает число сохранений на каждый источник и не означает полное покрытие периода. `NEWS_LOOKBACK_DAYS` задает период по умолчанию; доступны `--from` и `--to` с часовым поясом.

`companies import` загружает снимок компаний и платежную аналитику, `companies embed` строит профильные векторы, а `companies search` ищет компании по произвольному тексту новости. `news db upgrade` применяет общую схему, включая таблицы компаний; отдельный `companies db upgrade` делает то же самое.

Векторы и HNSW-индекс хранятся в PostgreSQL с pgvector. Повторный сбор делает upsert, изменение текста инвалидирует старые векторы. После `embed` новые векторы сразу доступны поиску: PostgreSQL обновляет индекс при сохранении, отдельная пересборка не нужна. Scheduler не добавлен. Первый `embed` скачивает локальную `intfloat/multilingual-e5-small`; модель, ее revision и подготовка текста фиксируются в профиле.

Данные БД, кеш модели и результаты CLI хранятся в Docker volumes. При запуске Python напрямую результаты по умолчанию пишутся в `../local_runtime/news` и `../local_runtime/companies`, вне Git; `NEWS_RUNTIME_DIR` и `COMPANIES_RUNTIME_DIR` меняют эти каталоги. PostgreSQL доступен на `127.0.0.1:5433`, порт и локальный пароль настраиваются через `NEWS_DB_PORT` и `NEWS_DB_PASSWORD`.

Для Python 3.12 без контейнера приложения:

```sh
python -m pip install -r requirements.txt
# Задать DATABASE_URL=postgresql+psycopg://... в окружении
python -m app db upgrade
python -m app news collect --days 15 --limit 50
python -m app news export --format ai
python -m app news embed
python -m app news search "цены на нефть и топливо" --top-k 5
python -m app companies import
python -m app companies embed
python -m app companies search "рост цен на автозапчасти" --top-k 5
```

Также доступен `python -m app.modules.news ...` и `python -m app.modules.companies ...`. Старый `python -m news_pipeline ...` перенаправляет в тот же новостной CLI. У проекта одна реализация пайплайна для каждого модуля.

## Правила совместной разработки

- Общие соединения, пул и фабрика SQLAlchemy Session находятся в `app/shared/db`. Каждый поток/операция открывает собственную Session. HTTP и вычисление эмбеддингов выполняются вне транзакций сохранения.
- Каждый модуль владеет своими ORM-моделями, DTO, репозиториями и сервисами. ORM-объекты остаются в репозитории; для обмена используются DTO. Не добавлять модели соседнего модуля в новостной `models.py`.
- Общий код не импортирует `app.modules.*`. Межмодульный обмен строить через явные контракты и сервисы.
- Миграции проекта находятся в `migrations/versions`. Новые revision ID должны быть уникальными; согласовывать зависимости и объединять Alembic heads при слиянии параллельных веток. Не редактировать уже примененные SQL-операции миграции.
- При добавлении модуля зарегистрировать его модели в `migrations/env.py` для autogenerate. Расширение pgvector уже создается начальной миграцией; соседним модулям не нужно повторно создавать новостные таблицы.
- Для новых embedding-корпусов использовать общий провайдер и фиксировать модель/revision/подготовку. Размерность сама по себе не подтверждает совместимость пространств; новостная и компанийная таблицы поддерживают 384 измерения.

После добавления моделей ревизию можно подготовить командой `python -m alembic revision --autogenerate -m "add module tables"` с заданным `DATABASE_URL`. Проверить сгенерированные операции, затем применить `python -m app db upgrade`. Шаблон генерации находится в `migrations/script.py.mako`.

## Существующая БД и миграции

`python -m app db upgrade` применяет общую историю Alembic. Если найдена только прежняя `news_alembic_version`, версия проверяется и таблица истории транзакционно переименовывается в `alembic_version`. Revision ID `0001_news` и `0002_news_fk_indexes` сохранены; статьи и векторы не пересоздаются. Миграция `0003_pgvector_only` удаляет служебную таблицу версии файлового индекса и связанный триггер; HNSW и инвалидирование векторов при изменении текста сохраняются. Миграция `0004_companies` добавляет группы, компании, историю импорта, профили и векторы компаний.

Если обе таблицы истории уже существуют, upgrade прекращается с ошибкой. Такой случай требует согласования историй с коллегами и не исправляется автоматическим stamp/drop. Новой пустой БД достаточно обычного `upgrade`.

## Проверки

```sh
python -m pip install -r requirements.txt -r research/ai/requirements.txt -r research/contracts/requirements.txt
python -m unittest discover -s tests/news -v
python -m unittest discover -s tests/companies -v
python research/contracts/t01/verify.py
python -m unittest discover -s research/contracts/t01 -p test_bridge.py -v
python research/contracts/validate.py
python -m unittest discover -s research/ai -p test_research.py -v
```

Без `NEWS_TEST_DATABASE_URL` и `COMPANY_TEST_DATABASE_URL` интеграционные тесты БД пропускаются. Для них нужна отдельная disposable БД с именем, оканчивающимся на `_test`, и примененными миграциями. Команды создания и проверки внутри Docker приведены в [инструкции по новостям](docs/news-pipeline.md#тесты) и [инструкции по компаниям](docs/companies-pipeline.md#тесты).

Текущий поиск проверен технически на небольшом корпусе. Полнота исторического сбора, качество отраслевой релевантности и объединение публикаций в события пока не доказаны. Поиск компаний проверен на 12 компаниях с синтетическими векторами; качество ранжирования на реальной E5-модели и новостях еще не измерено. Исследовательские fixtures и UX-демо не считать реальными данными компаний или экспертной позицией банка.
