# Convenience targets. Everything here is a one line command you can also run
# by hand; nothing is hidden in the Makefile.

.PHONY: help setup run test eval check docker clean

help:
	@echo "setup   create .venv and install the project"
	@echo "run     start the service on http://127.0.0.1:8000"
	@echo "test    run the test suite"
	@echo "eval    run the evaluation suites (needs a model server)"
	@echo "check   validate the evaluation suites without a model"
	@echo "docker  build and start everything with Docker Compose"

setup:
	python -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e ".[dev]"

run:
	.venv/bin/python -m insights

test:
	.venv/bin/python -m pytest

eval:
	.venv/bin/python -m insights.evaluation

check:
	.venv/bin/python -m insights.evaluation --check

docker:
	docker compose up --build

clean:
	rm -rf .venv data .pytest_cache
