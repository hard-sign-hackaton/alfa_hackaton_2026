# Новости в анализе компании

`db` хранит профили компаний, подготовленные показатели, банковские материалы и пары для анализа.
`postgres` хранит новости, векторы новостного модуля и снимок компаний из `app/modules/companies`.
Агент читает `news_articles` через `NewsReader`; старые пары разрешаются в канонический ID по URL.
Таблица `news` остаётся для совместимости с локальными экспериментами и старой загрузкой.

## Компании

Снимок `docs/companies/companies_analytics.json` загружается в `postgres` модулем
`app/modules/companies` в таблицы `company_groups`, `companies`, `company_import_runs`,
`company_embedding_profiles` и `company_embeddings`. Это отдельный источник данных,
который не заменяет демонстрационные профили в `db`. `company_embeddings.vector` — E5-профиль
компании для поиска по тексту новости; подготовка `e5-company-profile-v1` фиксируется в
`company_embedding_profiles`. Запуск и ограничения описаны в
[docs/companies-pipeline.md](companies-pipeline.md). Роль `analysis_news_reader` получает
`SELECT` на таблицы компаний вместе с новостными таблицами.

## Запуск

Настройки берутся из корневого `.env`; список полей приведён в `.env.example`.
Пароли `POSTGRES_PASSWORD`, `DB_AGENT_PASSWORD`, `NEWS_DB_PASSWORD` и
`NEWS_READER_PASSWORD` нужно задать до первого запуска соответствующих томов.

```sh
docker compose run --rm db-seed
docker compose run --rm ai-agent
```

Первая команда загружает демонстрационные профили и сохранённые публикации.
Она не добавляет платежные агрегаты, банковскую аналитику или вымышленные векторы.
Для своей пары:

```sh
docker compose run --rm ai-agent python analyze_pair.py --company-id COMPANY_ID --news-id NEWS_ID
```

Результат и телеметрия сохраняются в `research/ai/live_results/database-agent/`.
Строка `NEWS_DATABASE_URL` использует роль `analysis_news_reader` с правами SELECT.
Инициализация и выдача прав выполняются отдельным сервисом `news-db-init`.

## Семантический поиск

Обычный образ использует полнотекстовый поиск PostgreSQL. Для семантического поиска
нужны существующие E5-векторы и отдельный образ с локальной моделью:

```sh
docker compose --profile pipeline build news
docker compose --profile pipeline run --rm news embed
docker compose build ai-agent-semantic
docker compose run --rm ai-agent-semantic --pair-id demo-metal-primary
```

После восстановления дампа с готовыми векторами `embed` не требуется.
`NEWS_DATABASE_NAME` выбирает базу, в том числе восстановленную `alfa_news_agent`.
При нескольких профилях задаётся `NEWS_EMBEDDING_PROFILE`. Модель запроса должна
совпадать с сохранёнными revision и подготовкой; агент не пересчитывает векторы документов.

Оба поиска отсекают будущие публикации и исходную новость до `top-k`.
В контекст попадают текстовые фрагменты, даты, URL и издатель; similarity не является
доказательством влияния на компанию. Проверка цитат не заменяет проверку смысла вывода.

## Проверка интеграции

```sh
docker compose run --rm integration-tests
```

Тесты используют отдельную `alfa_news_integration_test`; синтетические строки
удаляются по собственным ID. Рабочие новости и векторы при этом не заменяются.
