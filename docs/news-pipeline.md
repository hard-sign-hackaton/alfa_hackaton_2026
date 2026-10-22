# Новостной пайплайн

Для передачи готовых новостей и эмбеддингов коллеге: [дамп и восстановление](news-database-handoff.md).

Ручной сбор всех новостей из "Коммерсанта", "Ведомостей" и "Интерфакса" без фильтрации по категориям. Отдельные стадии: сбор → PostgreSQL → локальные эмбеддинги → pgvector. Планировщика и LLM-вызовов нет.

## Запуск через Docker Compose

Нужны Docker Engine и Compose. Из корня репозитория:

```sh
docker compose --profile pipeline up -d postgres
docker compose --profile pipeline build news
docker compose --profile pipeline run --rm news db upgrade
docker compose --profile pipeline run --rm news collect --days 15 --limit 50
docker compose --profile pipeline run --rm news export --format ingestion --output /runtime/news.json
docker compose --profile pipeline run --rm news export --format ai --output /runtime/ai-news.json
docker compose --profile pipeline run --rm news embed
docker compose --profile pipeline run --rm news search "цены на нефть и топливо"
```

Первый `embed` скачивает модель. Остальные команды сбора/БД/экспорта не требуют модели. `search` требует модель для вектора запроса, но не пересчитывает документы. При нескольких профилях передавать `--profile ID` в `search`.

`news-runtime` — volume отчетов и JSON, `news-models` — кеш модели, `news-postgres` — данные БД. Для выгрузки volume в локальную папку можно вместо `news-runtime:/runtime` подключить `../local_runtime/news:/runtime` и дать пользователю контейнера UID 10001 права на запись. Не помещать runtime в Git. Существующие AI-сервисы Compose не изменены.

PostgreSQL слушает только `127.0.0.1:5433`. `NEWS_DB_PORT` меняет порт, `NEWS_DB_PASSWORD` задает пароль; default предназначен только для локальной разработки. Смена переменной не меняет пароль в уже инициализированном PostgreSQL volume.

## Запуск Python без контейнера приложения

Python 3.12, PostgreSQL из Compose остается тем же. Пример PowerShell из корня:

```powershell
py -3.12 -m venv ..\local_runtime\news-venv
..\local_runtime\news-venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = 'postgresql+psycopg://alfa_news:local-news-development-only@localhost:5433/alfa_news'
$env:NEWS_LOOKBACK_DAYS = '15'
$env:HF_HOME = (Join-Path (Resolve-Path '..\local_runtime').Path 'hf-cache')
..\local_runtime\news-venv\Scripts\python.exe -m app.modules.news db upgrade
..\local_runtime\news-venv\Scripts\python.exe -m app.modules.news collect --limit 50
```

В последующих командах можно использовать тот же интерпретатор вместо `python`:

```sh
python -m app.modules.news collect --sources kommersant vedomosti interfax --from 2026-10-07T00:00:00+05:00 --to 2026-10-22T00:00:00+05:00 --limit 50
python -m app.modules.news export --format ai
python -m app.modules.news embed --batch-size 16
python -m app.modules.news search "стоимость кредитов для бизнеса" --top-k 5
```

`NEWS_RUNTIME_DIR` меняет каталог результатов, default — `../local_runtime/news` относительно checkout. `NEWS_LOOKBACK_DAYS` задает период по умолчанию (15), `--days` переопределяет его. `--from` и `--to` принимают ISO 8601 с часовым поясом. Интервал `[from, to)`, хранение UTC. Без `--to` используется момент запуска, без `--from` — начало относительно конца периода.

`--limit` — число успешно сохраненных публикаций на источник, без параметра ограничение статей отсутствует. По умолчанию остаются пределы 3000 HTTP-попыток и 100 sitemap на источник; параметры `--max-requests`, `--max-sitemaps`, `--timeout`, `--delay` изменяют их. Пауза не может быть меньше секунды. Эти пределы ограничивают затраты, но не доказывают полноту покрытия.

## Источники и происхождение данных

У каждого сайта отдельный поток и HTTP-сессия. Сначала RSS и sitemap-индекс, затем доступные вложенные sitemap и HTML. Запросы внутри одного источника последовательны, сайты работают параллельно. Один сайт может завершиться с ошибкой, пока другие сохраняют результат. Повторы временных ошибок и редиректы учитываются в бюджете запросов; редиректы за пределы домена отклоняются до запроса.

Дата публикации берется из `article:published_time`, `datePublished` HTML/JSON-LD или RSS `pubDate`. `lastmod` не подставляется как дата публикации и не служит основанием для раннего прекращения обхода. Дата без часового пояса считается неизвестной. Несортированный sitemap не приводит к остановке на первых старых ссылках.

Обнаруженные paywall, слишком короткий/пустой текст и неизвестная дата фиксируются в отчете. Обход платного доступа не реализован; отсутствие явного paywall не доказывает полноту текста. Публикации, отсутствующие в доступных индексах, не будут найдены. Архивный период можно запросить, но полное архивное покрытие не гарантируется.

Метод извлечения, источник даты, время сбора, рубрики и ограничения сохраняются вместе с новостью. Полные сырые HTML в этом пайплайне не сохраняются. Отчет запуска содержит настройки, число найденных/проверенных/сохраненных ссылок, ошибки, длительность и статус каждого воркера. `partial` включает выборку, остановленную лимитом; `completed` означает завершение обхода обнаруженных документов, а не всей публикационной истории издателя. Нулевой результат не подменяется демо-данными.

Стабильный ID — SHA-256 нормализованного URL: удалены fragment и известные tracking-параметры. Повторный сбор делает upsert. Разные URL одного события пока остаются разными публикациями. Категории сохраняются без фильтрации; `topics`, `regions`, `countries` в AI-проекции пока пусты. Классификация и бизнес-релевантность относятся к следующим стадиям.

## Контракты и таблицы

`NewsArticleDTO` — отдельная Pydantic-модель загрузки (wire-schema сохраняет прежнее имя IngestedNews), ее экспортируемая JSON Schema лежит рядом с существующими контрактами. AI-экспорт строго выбирает поля текущего `research/ai/contracts.py::NewsEvent`; его модель и T01/UX-схемы не изменены. Резюме, факты, география и UI-поля не выдумываются загрузчиком.

Таблицы: `news_sources`, `news_articles`, `news_ingestion_runs`, `news_embedding_profiles`, `news_embeddings`. Alembic использует общую таблицу версий `alembic_version` и корневой каталог `migrations/`. История прежнего новостного модуля принимается без пересоздания данных; конфликт историй останавливает upgrade. `db upgrade` применяет миграции и повторно безопасно регистрирует источники. PostgreSQL JSONB хранит метаданные, отдельные колонки — URL, текст, даты и хеш содержимого; `vector(384)` — вектор.

Upsert статьи транзакционен, одинаковый URL сериализуется advisory lock. Изменение заголовка или текста удаляет все старые эмбеддинги статьи триггером. Если текст изменился во время вычисления вектора, старый результат не сохраняется. Ошибка embedding-провайдера оставляет новость в БД и допускает повторный запуск.

## Эмбеддинги и поиск

Default — локальная `intfloat/multilingual-e5-small`, 384 измерения, CPU. Revision разрешается в immutable Hub commit и сохраняется в профиле; `NEWS_MODEL_REVISION` либо `embed --revision` позволяет зафиксировать его заранее. `NEWS_EMBEDDING_DEVICE` меняет устройство. Это разрешенная командой embedding-модель, не вызов дополнительной генеративной LLM.

Подготовка: `passage:` + заголовок до 64 токенов + окна текста по 384 токена с перекрытием 64; учитываются специальные токены, превышение 512 отклоняется. Все тело документа покрывается окнами. Нормализованные векторы окон усредняются и снова L2-нормализуются, результат `float32`. Для запроса применяется `query:`. Усреднение — стартовый способ представления, а не доказанная оптимальная стратегия.

Профиль включает model, revision, dimension, normalization и preparation version. Неизмененный текст в том же профиле не пересчитывается. Для сопоставления компаний/аналитики с новостями нужен совместимый профиль; одинаковых 384 измерений недостаточно.

PostgreSQL — единственное хранилище и поисковый backend. Векторы лежат в `news_embeddings.vector` (`vector(384)`), профиль модели — в `news_embedding_profiles`. `NewsSearchService` получает вектор запроса через embedding-сервис и вызывает репозиторий; SQLAlchemy выполняет поиск по cosine distance с HNSW-индексом `ix_news_vector_hnsw`. Для запроса задаются `hnsw.ef_search=64` и iterative scan `strict_order`, результаты фильтруются по профилю. На небольшом корпусе PostgreSQL может выбрать точный последовательный поиск вместо HNSW: это нормальное решение планировщика.

При добавлении новости вычисляется только ее эмбеддинг. PostgreSQL автоматически обновляет индекс при INSERT/UPDATE/DELETE, отдельные файлы, manifest и команда пересборки не нужны. Неизмененные документы повторно не кодируются. При изменении текста старый вектор удаляется; до следующего `embed` статья отсутствует в поиске. Запрос возвращает ID, URL, заголовок и `similarity = 1 - cosine distance` одним SQL-запросом. Приближенный поиск может отличаться от точного; similarity не является вероятностью или бизнес-важностью.

Миграция `0003_pgvector_only` удаляет прежнюю служебную таблицу версии файлового индекса, функцию и триггер ее обновления. Новости, профили, векторы, HNSW и триггер инвалидирования сохраняются. Прежние команды `index rebuild` и параметр `--backend` удалены из CLI. Старые файлы runtime больше не используются и могут быть удалены владельцем отдельно.

Источники технических решений: [pgvector](https://github.com/pgvector/pgvector), [карточка E5](https://huggingface.co/intfloat/multilingual-e5-small). Генерацией эмбеддингов управляет Python-слой; pgai не используется.

Использованы подходы из [SemanticNews](https://github.com/svn-re7/SemanticNews/tree/231ad4ff400aed9cf0a65dfc66c3730430b0f7de): сетевой слой, обход sitemap, контейнер Коммерсанта и провайдер эмбеддингов. Код адаптирован без Flask/SQLite/UI; ранний выход по нескольким старым ссылкам и подмена publication date значением lastmod не перенесены.

## Тесты

```sh
python -m pip install -r requirements.txt -r research/ai/requirements.txt -r research/contracts/requirements.txt
python -m unittest discover -s tests/news -v
python research/contracts/t01/verify.py
python -m unittest discover -s research/contracts/t01 -p test_bridge.py -v
python research/contracts/validate.py
python -m unittest discover -s research/ai -p test_research.py -v
```

PostgreSQL integration tests включаются только для отдельной disposable БД с именем, заканчивающимся на `_test`. Создать ее в локальном контейнере, выполнить `db upgrade` с ее `DATABASE_URL`, затем задать `NEWS_TEST_DATABASE_URL` на ту же БД и повторить unittest. Тесты создают явно синтетические записи и удаляют только собственные статьи и профили. Обычная база сбора для тестов не используется.

Для локального пароля по умолчанию, один раз создать тестовую БД:

```sh
docker compose --profile pipeline exec -T postgres createdb -U alfa_news alfa_news_pipeline_test
docker compose --profile pipeline run --rm -e DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@postgres:5432/alfa_news_pipeline_test news db upgrade
docker compose --profile pipeline run --rm --entrypoint python -e NEWS_TEST_DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@postgres:5432/alfa_news_pipeline_test news -m unittest discover -s tests/news -v
```

Тесты покрывают три реальных сохраненных HTML, XML, даты, дубли, параллельность, сбой сайта, полное покрытие токенов, ошибки провайдера, upsert, инвалидирование, разделение профилей и немедленную доступность новых векторов. Наличие реального E5/pgvector прогона и его ограничения описываются в отчете проверки; тестовые векторы не являются подтверждением работы модели.

## Проверки и история

Текущая проверка после перехода на единственный backend: [news-pgvector-checks.json](news-pgvector-checks.json). Поиск проверяется на реальных сохраненных E5-векторах, интеграционные тесты — на отдельной PostgreSQL. Прошли 35 новостных тестов на хосте и в Docker, включая реальную PostgreSQL, а также 16 AI- и 12 T01-тестов. Сохранились 153 новости и 153 E5-вектора; повторный `embed` записал 0 векторов, оба экспорта по 153 записи прошли JSON Schema. Docker-образ собран без пакета FAISS, реальный E5-поиск внутри контейнера совпал с хостом по первому результату. Сборщик и JSON-контракты при этой смене не изменяются.

Исторические отчеты сохранены без изменения в [archive](archive/): [первый живой сбор и поиск](archive/news-pipeline-checks.json), [разделение на слои](archive/news-layout-checks.json). Они описывают прежние версии, включая удаленный файловый backend, и не являются инструкцией по текущему запуску. Полнота исторического сбора и качество отраслевой релевантности требуют отдельной оценки.

## Организация кода

Навигация и правила добавления соседних модулей находятся в [корневом README](../README.md). Рабочий код — `app/modules/news`, общие соединения и провайдер — `app/shared`. Старый пакет `news_pipeline` содержит только CLI-переходник. Проверки после переноса — [news-layout-checks.json](archive/news-layout-checks.json).
