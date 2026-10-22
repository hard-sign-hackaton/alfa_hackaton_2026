# Хранение аналитических материалов

Аналитические материалы Альфа-Банка хранятся в PostgreSQL отдельно от новостей. Единица хранения — документ, его Markdown-представление, смысловые чанки, таблицы и эмбеддинги чанков.

## Схема

| Таблица | Назначение |
|---|---|
| `analytics_documents` | Документ: заголовок, подзаголовок, тип, дата публикации, теги, источник, SHA-256, Markdown, метаданные извлечения |
| `analytics_chunks` | Чанк: раздел, текст, `embedding_text`, хеши, страницы, ссылки на таблицы, полнотекстовый `tsvector` |
| `analytics_tables` | Полная сетка таблицы, страница, размеры, предупреждения OCR |
| `analytics_embedding_profiles` | Модель, revision, размерность и подготовка текста |
| `analytics_chunk_embeddings` | Вектор `vector(384)` на чанк, привязанный к профилю |
| `analytics_import_runs` | История импорта и отчёт |

`analytics_chunks.search_vector` строится по `text`, а не по `embedding_text`: иначе название документа совпадало бы со всеми чанками. Векторный поиск — основной, полнотекстовый — вспомогательный из-за OCR-шума. При поиске по умолчанию не больше двух чанков одного документа.

Импорт идемпотентен. Если Markdown и набор чанков не изменились, документ, чанки и уже посчитанные векторы сохраняются. При изменении текста чанки пересоздаются, старые векторы удаляются каскадом, а `embed` считает новые.

## Манифест

Метаданные документа лучше задавать явно: OCR не всегда надёжно определяет дату и тип. Манифест — JSON со списком документов:

```json
{
  "schema_version": "1.0.0",
  "documents": [
    {
      "id": "alfa-7m26",
      "source_name": "ALFA-7M26.pdf",
      "title": "Макростатистика 7М26",
      "subtitle": "Данные по рынку труда не подтверждают охлаждения экономики",
      "doc_type": "macro",
      "published_at": "2026-09-07",
      "language": "ru",
      "tags": ["макроэкономика", "рынок труда"],
      "metadata": {"period": "7M2026"}
    }
  ]
}
```

`source_name` — имя PDF, `id` — стабильный ASCII-идентификатор. Если манифеста нет, импорт попробует определить название по первому заголовку, дату — по первой дате в Markdown, `doc_type` будет `analytics`. Если дату определить нельзя, импорт остановится с ошибкой. Готовый манифест для текущего корпуса: [research/bank/manifest.json](../research/bank/manifest.json).

## Импорт

Сначала PDF преобразуются в JSON и `chunks.jsonl` скриптами `research/bank/extract_pdf.py` и `research/bank/prepare_chunks.py`. Затем:

```sh
python -m app db upgrade
python -m app analytics import \
  --extracted ../alfa_hakaton_2026_data/extracted_v2 \
  --manifest research/bank/manifest.json \
  --source-root ../alfa_hakaton_2026_data
```

`--chunks` позволяет указать отдельный `chunks.jsonl`. `--report` задаёт путь отчёта; по умолчанию он пишется в `local_runtime/analytics/import-report.json` вне Git.

Проверка:

```sh
python -m app analytics stats
python -m app analytics list --limit 20
python -m app analytics show alfa-7m26
python -m app analytics show alfa-7m26 --markdown
```

## Эмбеддинги

```sh
python -m app analytics embed --batch-size 16
python -m app analytics profiles
```

Используется общий провайдер `intfloat/multilingual-e5-small`, 384 измерения, префикс `passage:`. Эмбеддинг считается по `embedding_text` чанка, а не по всему документу. Профиль модели и revision сохраняются в БД; при повторном импорте неизменённых чанков векторы не пересчитываются.

## Поиск

```sh
python -m app analytics search "рынок труда" --top-k 5
python -m app analytics search "рынок труда" --top-k 5 --mode vector --profile PROFILE_ID
```

Полнотекстовый поиск не требует модели. Векторный поиск требует выполненный `embed` и один сохранённый профиль; при нескольких профилях укажите `--profile`. `--as-of` ограничивает выдачу датой публикации. `--per-document` задаёт максимум чанков одного документа (по умолчанию 2).

## Тесты

```sh
python -m unittest discover -s tests/analytics -v
ANALYTICS_TEST_DATABASE_URL=postgresql+psycopg://.../analytics_test \
  python -m unittest discover -s tests/analytics -v
```

Интеграционные тесты требуют отдельную disposable БД с именем, оканчивающимся на `_test`. Без переменной они пропускаются.
