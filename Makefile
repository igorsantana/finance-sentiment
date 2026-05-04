.PHONY: help build up down nuke logs ps migrate psql db-reset companies ingest extract full judge judge-stats shell status dev

COMPOSE  := docker compose
EXEC     := $(COMPOSE) exec -T app
EXEC_TTY := $(COMPOSE) exec app

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?##' '{printf "  %-14s %s\n", $$1, $$2}'

build: ## Build images
	$(COMPOSE) build

up: ## Start db, app, cron in the background
	$(COMPOSE) up -d

down: ## Stop services (volumes preserved)
	$(COMPOSE) down

nuke: ## Stop services and drop volumes (DESTRUCTIVE)
	$(COMPOSE) down -v

logs: ## Tail logs (CTRL-C to exit)
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Apply pending DB migrations
	$(EXEC) python scripts/migrate.py

psql: ## Open psql shell to the local DB
	$(COMPOSE) exec db psql -U app finance_news

db-reset: ## Drop DB volume, recreate, migrate
	$(COMPOSE) down -v
	$(COMPOSE) up -d db
	$(COMPOSE) up -d app
	$(EXEC) python scripts/migrate.py

companies: ## Refresh the companies table from BrAPI (all available tickers)
	$(EXEC) python scripts/companies/fetch_top.py

ingest: ## Fetch fresh articles into the DB
	$(EXEC) python -m finance_news.pipeline ingest

extract: ## Run sentiment extraction on pending articles
	$(EXEC) python -m finance_news.pipeline extract

full: ## ingest + extract + summarize
	$(EXEC) python -m finance_news.pipeline run

judge: ## Open the judging TUI (interactive)
	$(EXEC_TTY) python scripts/judging/cli.py

judge-stats: ## Show confusion matrix vs human judgments
	$(EXEC) python scripts/judging/stats.py

shell: ## Open a bash shell in the app container
	$(EXEC_TTY) bash

status: ## Show pipeline status (last runs, counts)
	$(EXEC) python -m finance_news.pipeline status

api-logs: ## Tail just the API (uvicorn) logs
	$(COMPOSE) logs -f app

web: ## Run the Vite dev server (host-side, proxies /api → :8000)
	cd web && npm install && npm run dev

dev: ## Live-reload backend (uvicorn --reload) + frontend (vite). Ctrl-C stops both.
	@trap 'kill 0 2>/dev/null; $(COMPOSE) stop app db cron 2>/dev/null' EXIT INT TERM; \
	$(COMPOSE) up app db cron & \
	(cd web && npm install --silent && npm run dev) & \
	wait
