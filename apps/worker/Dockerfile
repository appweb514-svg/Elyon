FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils ffmpeg fonts-dejavu-core libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY elyon_api/ elyon_api/
COPY migrations/ migrations/
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-cache-dir .

RUN useradd --uid 10001 --create-home elyon \
    && mkdir -p /var/lib/elyon/media \
    && chown -R elyon:elyon /var/lib/elyon
USER elyon

CMD ["celery", "-A", "elyon_api.worker", "worker", "--loglevel=info"]