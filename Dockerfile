FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY research/ai/requirements.txt /tmp/requirements-ai.txt
COPY research/news/requirements.txt /tmp/requirements-news.txt
COPY research/contracts/requirements.txt /tmp/requirements-contracts.txt
RUN python -m pip install --disable-pip-version-check -r /tmp/requirements-ai.txt -r /tmp/requirements-news.txt -r /tmp/requirements-contracts.txt \
    && groupadd --gid 10001 researcher \
    && useradd --uid 10001 --gid researcher --no-create-home researcher \
    && mkdir /output \
    && chown researcher:researcher /output

COPY --chown=researcher:researcher research /app/research
USER researcher
WORKDIR /app/research/ai
CMD ["python", "run.py", "--mode", "offline", "--output", "/output"]
