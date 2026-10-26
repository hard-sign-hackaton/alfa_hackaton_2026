# Источники новостей

В рабочей конфигурации новости собираются с трёх сайтов. Реестр источников:
`app/modules/news/parsers/registry.py`.

### Интерфакс
- Сайт: [https://www.interfax.ru/](https://www.interfax.ru/)
- Обнаружение материалов:
  - sitemap: [https://www.interfax.ru/SEO_SiteMapIndex.xml](https://www.interfax.ru/SEO_SiteMapIndex.xml)
  - RSS: [https://www.interfax.ru/rss.asp](https://www.interfax.ru/rss.asp)
- Парсер: `app/modules/news/parsers/interfax.py`

### Коммерсантъ
- Сайт: [https://www.kommersant.ru/](https://www.kommersant.ru/)
- Обнаружение материалов:
  - sitemap: [https://www.kommersant.ru/sitemaps/news.xml](https://www.kommersant.ru/sitemaps/news.xml)
  - RSS: [https://www.kommersant.ru/RSS/news.xml](https://www.kommersant.ru/RSS/news.xml)
- Парсер: `app/modules/news/parsers/kommersant.py`

### Ведомости
- Сайт: [https://www.vedomosti.ru/](https://www.vedomosti.ru/)
- Обнаружение материалов:
  - sitemap: [https://www.vedomosti.ru/sitemap.xml](https://www.vedomosti.ru/sitemap.xml)
  - RSS: [https://www.vedomosti.ru/rss/news](https://www.vedomosti.ru/rss/news)
- Парсер: `app/modules/news/parsers/vedomosti.py`

Права на новостные материалы принадлежат соответствующим изданиям. Проект не
перелицензирует эти материалы; при использовании необходимо соблюдать условия
сайтов и применимое законодательство.

# Embedding-модель

### `intfloat/multilingual-e5-small`

- Карточка модели: [https://huggingface.co/intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
- Лицензия: MIT
- Реализация: `app/shared/embeddings/e5.py`
- Runtime: `sentence-transformers` и PyTorch, по умолчанию на CPU

Модель применяется для:

- статей и поисковых запросов по новостям;
- профилей компаний;
- банковских материалов и их чанков.

При первом запуске модель может быть загружена с Hugging Face Hub и закэширована
в `HF_HOME` (`/models` в Docker).


# Основные сторонние компоненты

Перечень отражает основные компоненты проекта. Версии и зависимости указаны в
`requirements.txt`, `research/ai/requirements.txt`, `research/ai/database-requirements.txt`
и `frontend/pnpm-lock.yaml`; лицензии включенных зависимостей сохраняются в их дистрибутивах.

| Компоненты | Назначение | Лицензия и источник |
| --- | --- | --- |
| Python 3.12 | Backend и CLI | [PSF License и включенные уведомления](https://github.com/python/cpython/blob/3.12/LICENSE) |
| Node.js | Сборка frontend | [MIT и лицензии включенных компонентов](https://github.com/nodejs/node/blob/main/LICENSE) |
| PostgreSQL 16/17, расширение pgvector | Хранение данных и векторный поиск | [PostgreSQL License](https://www.postgresql.org/about/licence/), [pgvector LICENSE](https://github.com/pgvector/pgvector/blob/master/LICENSE) |
| React, React DOM, Vite; Alfa Core Components | Интерфейс и сборка | MIT: [React](https://github.com/facebook/react/blob/main/LICENSE), [Vite](https://github.com/vitejs/vite/blob/main/LICENSE), [Core Components](https://github.com/alfa-laboratory/core-components/blob/master/package.json) |
| TypeScript; Lucide | Проверка типов; иконки | [Apache-2.0](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt); [ISC](https://github.com/lucide-icons/lucide/blob/main/LICENSE) |
| Pydantic, SQLAlchemy, Alembic, pgvector-python, Beautiful Soup, jsonschema | Контракты, БД, парсинг и валидация | MIT; проверено по метаданным установленных пакетов |
| Requests; defusedxml; python-dotenv | HTTP, XML и конфигурация | Apache-2.0; PSF License; BSD-3-Clause соответственно, по метаданным пакетов |
| Psycopg | Драйвер PostgreSQL | [LGPL-3.0](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt); бинарная сборка включает отдельные компоненты |
| Sentence Transformers, Transformers; Docling | Эмбеддинги; извлечение PDF | [Apache-2.0](https://github.com/huggingface/sentence-transformers/blob/master/LICENSE), [Apache-2.0](https://github.com/huggingface/transformers/blob/main/LICENSE), [MIT](https://github.com/docling-project/docling/blob/main/LICENSE) |
| NumPy, PyTorch | Численные операции и выполнение моделей | [NumPy LICENSE](https://github.com/numpy/numpy/blob/main/LICENSE.txt), [PyTorch LICENSE](https://github.com/pytorch/pytorch/blob/main/LICENSE): собственные и включенные сторонние лицензии |
| langchain-core, langchain-openai | Клиент и структуры вызовов LLM | MIT, по метаданным пакетов; агентная логика реализована в проекте |

Docker Engine и Compose используются для запуска контейнеров; базовые образы
перечислены в `compose.yaml` и Dockerfile, уведомления их системных пакетов входят в образы.

# LLM и внешние сервисы

По умолчанию используются `google/gemma-4-26b-a4b-it` (классификация, важность и краткий разбор),
`qwen/qwen3.6-35b-a3b` (извлечение), `deepseek/deepseek-v4.1-flash` (исследование и анализ),
`z-ai/glm-5.3-flash` (чат). `qwen/qwen3-vl-30b-a3b-instruct` и `moonshotai/kimi-k2.6`
разрешены конфигурацией как альтернативы. Маршруты: `research/ai/model_config.py`.
Вызовы идут через предоставленный хакатоном [API-шлюз](https://changellenge.up.railway.app/v1)
(`LLM_BASE_URL`, ключ `LLM_API_KEY`). Доступ к размещенным LLM определяется условиями
провайдера шлюза и правообладателей моделей; проект не распространяет их веса.
Hugging Face Hub используется для загрузки E5; Docling может загружать собственные
модели обработки документов, условия которых указаны в соответствующих карточках.

# Происхождение данных и демонстрационные интеграции

- Профили `docs/companies/companies_analytics.json` подготовлены из обезличенных данных компаний и платежей, переданных по кейсу; платежные агрегаты не устанавливают природу отношений контрагентов.
- Банковские материалы получены из предоставленных PDF Альфа-Банка; происхождение и даты перечислены в `research/bank/manifest.json`. Права на материалы сохраняются за правообладателем.
- `database/seeds` содержит подготовленный снимок стартовых данных и результатов. Вымышленные новости экспертного сценария (`app/web/expert_news.py`) и тестовые материалы (`research/ai/fixtures.py`) созданы для демонстрации и проверок.
- Интеграция с Альфа-Бизнесом смоделирована интерфейсом и навигацией прототипа. Подключение к реальным банковским учетным записям и платежным API не реализовано.
