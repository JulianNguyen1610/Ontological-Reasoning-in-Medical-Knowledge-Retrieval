.PHONY: format-check lint typecheck test

format-check:
	ruff format --check src tests/unit

lint:
	ruff check src tests/unit

typecheck:
	mypy src

test:
	pytest -q
