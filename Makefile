.PHONY: audit check format governance migrate quality security test

check: quality test security governance

quality:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

security:
	uv run bandit -c pyproject.toml -r src/blackbread
	uv run pip-audit

governance:
	uv run pytest tests/governance --no-cov

format:
	uv run ruff format .

migrate:
	uv run alembic upgrade head

test:
	uv run pytest

audit: check
