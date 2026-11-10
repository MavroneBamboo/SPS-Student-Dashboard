FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml .
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
ARG INSTALL_TEST_DEPENDENCIES=false
RUN apt-get update \
    && apt-get install --yes --no-install-recommends zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip setuptools urllib3 msgpack \
    && if [ "$INSTALL_TEST_DEPENDENCIES" = "true" ]; then \
      pip install --no-cache-dir ".[test]"; \
    else \
      pip install --no-cache-dir .; \
    fi
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
