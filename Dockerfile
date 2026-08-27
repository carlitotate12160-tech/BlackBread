FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8.11 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --system blackbread && useradd --system --gid blackbread --home /app blackbread
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY pyproject.toml ./
COPY src ./src
RUN mkdir -p /var/lib/blackbread/artifacts && chown -R blackbread:blackbread /app /var/lib/blackbread
USER blackbread
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src"
EXPOSE 8000
CMD ["uvicorn", "blackbread.app:app", "--host", "0.0.0.0", "--port", "8000"]
