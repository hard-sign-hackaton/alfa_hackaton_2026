#!/usr/bin/env bash
set -euo pipefail

docker compose --profile web build data-init web
docker compose --profile web up -d web

data_init_id="$(docker compose --profile web ps -aq data-init | tail -n 1)"
if [ -z "$data_init_id" ]; then
  echo "data-init container was not created" >&2
  exit 1
fi

while [ "$(docker inspect -f '{{.State.Status}}' "$data_init_id")" != "exited" ]; do
  sleep 2
done

data_init_exit="$(docker inspect -f '{{.State.ExitCode}}' "$data_init_id")"
if [ "$data_init_exit" != "0" ]; then
  docker compose --profile web logs data-init
  exit "$data_init_exit"
fi

docker compose --profile web logs data-init | tail -n 12

docker compose --profile pipeline up -d postgres
docker compose --profile pipeline build news
docker compose --profile pipeline run --rm news db upgrade
docker compose --profile pipeline run --rm news collect --days 15 --limit 50
docker compose --profile pipeline run --rm news export --format ai --output /runtime/ai-news.json
docker compose --profile pipeline run --rm news embed

docker compose --profile web restart web

web_address="$(docker compose --profile web port web 8080 | tail -n 1)"
if [ -z "$web_address" ]; then
  web_address="127.0.0.1:${WEB_PORT:-8080}"
fi
web_url="http://${web_address}"
for _ in $(seq 1 60); do
  bootstrap="$(curl -fsS "$web_url/api/bootstrap" 2>/dev/null || true)"
  if grep -Eq '"companies"[[:space:]]*:[[:space:]]*\[[[:space:]]*\{' <<<"$bootstrap"; then
    echo "Web is ready: $web_url"
    exit 0
  fi
  sleep 2
done

echo "Web did not return companies in time: $web_url/api/bootstrap" >&2
exit 1
