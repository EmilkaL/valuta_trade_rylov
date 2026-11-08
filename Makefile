.PHONY: install run lint build

install:
	uv sync --locked

run:
	uv run project

lint:
	uv run ruff check .

build:
	uv build
