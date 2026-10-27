# Variables
VENV_DIR = .venv
FLASK_APP = main.py

ifeq ($(OS),Windows_NT)
PYTHON = $(VENV_DIR)/Scripts/python.exe
PIP = $(VENV_DIR)/Scripts/pip.exe
else
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
endif

# Default target
.DEFAULT_GOAL := help

# Targets
help:  ## Show available targets
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

venv: ## Create a virtual environment
	@python -m venv $(VENV_DIR)
	@echo "Virtual environment created at $(VENV_DIR)"

install: venv ## Install dependencies
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@echo "Dependencies installed."

run: ## Run the Flask app
	@$(PYTHON) $(FLASK_APP)

lint: ## Lint the project using flake8
	@$(PIP) install flake8
	@$(PYTHON) -m flake8 app tests main.py
	@echo "Linting completed."

hooks: ## Enable the pre-commit secret scan for this clone
	@git config core.hooksPath .githooks
	@echo "Pre-commit secret scan enabled."

test: ## Run all tests
	@$(PYTHON) -m unittest discover -s tests
	@echo "Tests completed."

clean: ## Clean up temporary and unnecessary files
	@$(PYTHON) -c "import pathlib, shutil; [p.unlink() for p in pathlib.Path('.').rglob('*.pyc') if p.is_file()]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__') if p.is_dir()]"
	@echo "Temporary files cleaned."

reset: clean ## Clean and reset the project
	@$(PYTHON) -c "import shutil; shutil.rmtree('$(VENV_DIR)', ignore_errors=True)"
	@echo "Project reset complete. Re-run 'make install' to set up again."

docker:
	@docker build -t mask-punisher .
	@#docker run -p 3000:3000 mask_utils-punisher
# Phony targets (not related to files)
.PHONY: help venv install run lint test hooks clean reset docker
