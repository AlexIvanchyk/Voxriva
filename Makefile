.PHONY: setup test test-backend test-frontend test-config test-compose test-sdk test-sdk-compose freeze-delivery-contract test-architecture test-contract test-postgres test-cloud-compose test-worker-crash-compose test-browser-matrix test-e2e

PYTHON := .venv/bin/python

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -e '.[dev]'
	npm --prefix frontend install --no-audit --no-fund

test: test-architecture test-backend test-frontend test-config test-sdk test-contract

test-backend:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy backend migrations
	$(PYTHON) -m pytest --cov=backend.app --cov-report=term-missing

test-frontend:
	npm --prefix frontend run lint
	npm --prefix frontend test
	npm --prefix frontend run build

test-config:
	docker compose config --quiet

test-compose:
	bash scripts/test-compose.sh


test-sdk:
	$(PYTHON) -m ruff check --config sdk/python/pyproject.toml sdk/python/src sdk/python/tests
	$(PYTHON) -m mypy --config-file sdk/python/pyproject.toml sdk/python/src
	PYTHONPATH=sdk/python/src $(PYTHON) -m pytest sdk/python/tests/test_client.py -q

test-sdk-compose:
	bash scripts/test-sdk-compose.sh

test-cloud-compose:
	bash scripts/test-cloud-compose.sh

test-worker-crash-compose:
	bash scripts/test-worker-crash-compose.sh

test-browser-matrix:
	bash scripts/test-browser-matrix-compose.sh

# Each suite owns a separate stack but uses the same default host ports.
# Recipes keep them sequential even when the outer make uses parallel jobs.
test-e2e:
	$(MAKE) test-compose
	$(MAKE) test-cloud-compose
	$(MAKE) test-worker-crash-compose
	$(MAKE) test-sdk-compose

freeze-delivery-contract:
	PYTHONPATH=. $(PYTHON) scripts/freeze-delivery-contract.py

test-architecture:
	$(PYTHON) scripts/check-architecture.py
	PYTHONPATH=. $(PYTHON) scripts/generate-variable-formats.py --check

test-contract:
	PYTHONPATH=. $(PYTHON) scripts/freeze-delivery-contract.py --check

test-postgres:
	@test -n "$$TEST_DATABASE_URL" || (echo 'Set TEST_DATABASE_URL to an isolated PostgreSQL test database.' >&2; exit 1)
	$(PYTHON) -m pytest -m postgres -q

.PHONY: test-production-compose
test-production-compose:
	bash scripts/test-production-compose.sh
