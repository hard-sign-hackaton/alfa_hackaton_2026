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
