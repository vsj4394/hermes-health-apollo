.PHONY: install-local install-git-hooks verify-local-install health-eval health-eval-judge health-eval-full health-eval-baseline health-eval-plan-c health-eval-plan-c-full

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf ".venv/bin/python"; elif command -v uv >/dev/null 2>&1; then printf "uv run python"; else printf "python3"; fi)

install-local:
	$(PYTHON) scripts/install_local.py

install-git-hooks:
	sh scripts/install_git_hooks.sh

verify-local-install:
	$(PYTHON) scripts/verify_local_install.py

health-eval:
	$(PYTHON) -m pytest health_eval
	$(PYTHON) -m health_eval.run --smoke

health-eval-judge:
	$(PYTHON) -m health_eval.judge --smoke

health-eval-full:
	$(PYTHON) -m health_eval.run

health-eval-baseline:
	$(PYTHON) -m health_eval.run --write-baseline

health-eval-plan-c:
	$(PYTHON) -m pytest health_eval/test_plan_c.py
	$(PYTHON) -m health_eval.run --suite plan_c --smoke

health-eval-plan-c-full:
	$(PYTHON) -m health_eval.run --suite plan_c
