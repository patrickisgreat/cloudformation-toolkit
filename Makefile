# cloudformation-toolkit developer tasks.
#
# Everything here is a thin wrapper over `./bin/cfn`, which is the real CLI and
# the thing CI calls. Use whichever you prefer.

VENV    ?= .venv
PYTHON  ?= python3
CFN     := ./bin/cfn
ENV     ?= dev

.PHONY: help install lint test check docs docs-check catalog catalog-check list \
        params new deploy diff delete outputs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install the dev toolchain (cfn-lint, pytest, PyYAML)
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements-dev.txt
	@echo "toolchain installed — run 'make check'"

lint: ## cfn-lint every template and stack against the resource schemas
	$(CFN) lint

test: ## Run the offline test suite (conventions, security policy, per-template)
	$(CFN) test

check: ## lint + test + docs-check + catalog-check — exactly what CI runs
	$(CFN) check

docs: ## Regenerate the parameter/output tables in every README
	$(CFN) docs

docs-check: ## Verify the generated README tables are up to date (CI-friendly)
	$(CFN) docs --check

catalog: ## Regenerate the template catalog in README.md from metadata.yaml files
	$(CFN) catalog

catalog-check: ## Verify the README catalog is up to date (CI-friendly)
	$(CFN) catalog --check

list: ## List every template and stack in the library
	$(CFN) list

params: ## Show a template's parameters: make params TARGET=containers/fargate-service
	@test -n "$(TARGET)" || { echo "usage: make params TARGET=<group>/<name>"; exit 1; }
	$(CFN) params $(TARGET)

new: ## Scaffold a new template: make new DIR=data/redshift-serverless
	@test -n "$(DIR)" || { echo "usage: make new DIR=<group>/<name>"; exit 1; }
	$(CFN) new $(DIR)

deploy: ## Deploy a target: make deploy TARGET=container-service ENV=dev
	@test -n "$(TARGET)" || { echo "usage: make deploy TARGET=<target> [ENV=dev]"; exit 1; }
	$(CFN) deploy $(TARGET) --env $(ENV)

diff: ## Preview a deploy as a change set: make diff TARGET=container-service ENV=dev
	@test -n "$(TARGET)" || { echo "usage: make diff TARGET=<target> [ENV=dev]"; exit 1; }
	$(CFN) diff $(TARGET) --env $(ENV)

delete: ## Delete a deployed stack: make delete TARGET=container-service ENV=dev
	@test -n "$(TARGET)" || { echo "usage: make delete TARGET=<target> [ENV=dev]"; exit 1; }
	$(CFN) delete $(TARGET) --env $(ENV)

outputs: ## Print a deployed stack's outputs: make outputs TARGET=container-service ENV=dev
	@test -n "$(TARGET)" || { echo "usage: make outputs TARGET=<target> [ENV=dev]"; exit 1; }
	$(CFN) outputs $(TARGET) --env $(ENV)

clean: ## Remove build output and Python caches
	rm -rf .cfn-build .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
