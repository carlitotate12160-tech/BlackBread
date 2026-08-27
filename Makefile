.PHONY: check format migrate test

check:
	uv run ruff check .
	uv run mypy
	uv run pytest

format:
	uv run ruff format .

migrate:
	uv run alembic upgrade head

test:
	uv run pytest

