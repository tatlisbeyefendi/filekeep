.PHONY: help install test cov lint format fix demo clean build

help:  ## show this help
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t 12

install:  ## editable install with dev extras
	python -m pip install -e '.[dev]'

test:  ## run the test suite
	python -m pytest

cov:  ## run the tests with a coverage report
	python -m pytest --cov --cov-report=term-missing

lint:  ## check style and formatting
	python -m ruff check .
	python -m ruff format --check .

format:  ## format the code
	python -m ruff format .

fix:  ## apply every autofix ruff knows
	python -m ruff check --fix --unsafe-fixes .
	python -m ruff format .

demo:  ## rebuild docs/demo*.svg from a throw-away directory tree
	PYTHONPATH=src python scripts/render_demo.py

build:  ## build a wheel and an sdist
	python -m pip install -q build && python -m build

clean:  ## remove caches
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
