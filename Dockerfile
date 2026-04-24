FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src

RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080 \
    APP_ENV=production

EXPOSE 8080

CMD ["sh", "-c", "uvicorn asx_financials.api.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
