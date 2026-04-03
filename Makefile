.PHONY: install lint lint-fix typecheck test all

install:
	pip install -e ".[dev]"

lint:
	ruff check src/ tests/

lint-fix:
	ruff check --fix src/ tests/

typecheck:
	mypy src/

test:
	pytest tests/ -v

all: lint typecheck test
