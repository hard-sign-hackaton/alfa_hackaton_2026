# Передача новостей и эмбеддингов

Дамп хранится вне Git. Снимок `alfa-news-2026-10-22.dump` содержит 153 новости, 153 реальных E5-вектора, один профиль модели, источники, историю сборов, схему, индексы и версию Alembic `0003_pgvector_only`. Это полный снимок текущей проектной БД, а не только JSON новостей. Кеш модели и пароли ролей в него не входят.

SHA-256: `7629377c97f13782ee5a991c5368b05c2456b7e1db4260b686f6df99c94f4936`.

## Восстановление

Нужны Python 3.12, запущенный Docker Engine и Compose. Локальные PostgreSQL и Python-зависимости проекта для восстановления не нужны. Получить от коллеги `.dump` или прямую HTTPS-ссылку скачивания. Восстанавливать только доверенные дампы: они содержат SQL-объекты.

Из корня репозитория:

```sh
python scripts/restore_news_dump.py --file /path/to/alfa-news-2026-10-22.dump --sha256 7629377c97f13782ee5a991c5368b05c2456b7e1db4260b686f6df99c94f4936
```

В Windows вместо `python` можно использовать `py -3.12`; путь с пробелами заключить в прямые двойные кавычки.

Вариант с облаком (нужна ссылка на сам файл, не страницу предпросмотра):

```sh
python scripts/restore_news_dump.py --url "https://YOUR_HOST/alfa-news-2026-10-22.dump" --sha256 7629377c97f13782ee5a991c5368b05c2456b7e1db4260b686f6df99c94f4936
```

Скрипт запускает сервис `postgres`, создает отдельную БД `alfa_news_agent` и восстанавливает ее одной транзакцией. Данные остаются в Compose volume `news-postgres`. Можно задать `--database другое_имя`, используя латинские строчные буквы, цифры и подчеркивания. Повторная загрузка в непустую БД отклоняется; для нового снимка указать новое имя. Скрипт не удаляет существующие таблицы и не меняет основную `alfa_news`. При загрузке по URL временный файл удаляется после завершения; локальный исходник сохраняется.

Ожидаемый итог: `articles=153`, `embeddings=153`, `profiles=1`. Сравнение восстановленной копии с исходной БД проверено по всем строкам всех проектных таблиц, включая векторы.

## Подключение AI-части

При запуске Python на хосте:

```text
DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@localhost:5433/alfa_news_agent
```

Для контейнера внутри того же Compose использовать `postgres:5432` вместо `localhost:5433`. Если настроены `NEWS_DB_PORT` или `NEWS_DB_PASSWORD`, подставить свои значения. Сам новостной CLI в Compose по умолчанию подключен к `alfa_news`, поэтому для восстановленной копии обязательно переопределить `DATABASE_URL`:

```sh
docker compose --profile pipeline build news
docker compose --profile pipeline run --rm -e DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@postgres:5432/alfa_news_agent news db upgrade
docker compose --profile pipeline run --rm -e DATABASE_URL=postgresql+psycopg://alfa_news:local-news-development-only@postgres:5432/alfa_news_agent news search "цены на нефть и топливо" --top-k 5
```

Миграции запускать из совместимой версии проекта: этот снимок требует историю с `0003_pgvector_only`. Эмбеддинги документов уже готовы, запускать `embed` для переноса не требуется. Для вектора поискового запроса CLI скачает `intfloat/multilingual-e5-small` с revision из сохраненного профиля. Поиск выполняется через pgvector; HNSW восстанавливается вместе с дампом, файлового индекса нет.
