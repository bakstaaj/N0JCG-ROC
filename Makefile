PYTHON ?= python3
PORT ?= 8095

.PHONY: test serve deploy-check tools-check

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m compileall -q src tests deploy/operator_helper.py
	bash -n tools/*.sh deploy/*.sh
	./tools/check_repository_hygiene.sh
	@if command -v node >/dev/null 2>&1; then node --check web/app.js; else echo "INFO: node unavailable; JavaScript syntax check skipped"; fi
	@! grep -RIl $$'\r' --include='*.py' --include='*.sh' --include='*.js' --include='*.css' --include='*.html' --include='*.md' --include='Makefile' .
	@echo "FINAL: PASS"

serve:
	PYTHONPATH=src $(PYTHON) -m n0jcg_roc.server --host 127.0.0.1 --port $(PORT)

deploy-check:
	./deploy/deploy.sh --check-only

tools-check:
	./tools/install_base_tools.sh --check-only
