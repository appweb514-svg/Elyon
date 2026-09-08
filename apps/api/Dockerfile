FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils ffmpeg fonts-dejavu-core libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY elyon_api/ elyon_api/
COPY migrations/ migrations/
RUN pip install --no-cache-dir .

RUN useradd --uid 10001 --create-home elyon \
    && mkdir -p /var/lib/elyon/media \
    && chown -R elyon:elyon /var/lib/elyon
USER elyon

EXPOSE 8000

HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3)"

CMD ["uvicorn", "elyon_api.main:app", "--host", "0.0.0.0", "--port", "8000"]