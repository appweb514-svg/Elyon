FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY elyon_api/ elyon_api/
RUN pip install --no-cache-dir .

RUN useradd --uid 10001 --create-home elyon
USER elyon

CMD ["celery", "-A", "elyon_api.worker", "worker", "--loglevel=info"]