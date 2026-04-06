
## **FILE: Makefile (Aktualisiert)**
```makefile
# FILE: Makefile
# MODULE: Makefile für einfache Entwicklung und Deployment

.PHONY: help build up down logs test lint migrate seed clean backup restore deploy-monitoring deploy-all

# Colors
GREEN := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
RED := $(shell tput -Txterm setaf 1)
RESET := $(shell tput -Txterm sgr0)

help: ## Show this help message
	@echo ''
	@echo '${GREEN}TrueAngels NGO Suite - Makefile${RESET}'
	@echo ''
	@echo '${YELLOW}Usage:${RESET}'
	@echo '  make <target>'
	@echo ''
	@echo '${YELLOW}Available targets:${RESET}'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  ${GREEN}%-20s${RESET} %s\n", $$1, $$2}'

# ==================== Docker Management ====================

build: ## Build Docker images
	docker-compose build

up: ## Start all services
	docker-compose up -d
	@echo "${GREEN}Services started. API: http://localhost:8000, Streamlit: http://localhost:8501${RESET}"

down: ## Stop all services
	docker-compose down

down-volumes: ## Stop all services and remove volumes
	docker-compose down -v

logs: ## Show all logs
	docker-compose logs -f

logs-api: ## Show API logs
	docker-compose logs -f api

logs-celery: ## Show Celery logs
	docker-compose logs -f celery_worker

logs-streamlit: ## Show Streamlit logs
	docker-compose logs -f streamlit

ps: ## Show service status
	docker-compose ps

restart: down up ## Restart all services

# ==================== Database ====================

migrate: ## Run database migrations
	docker-compose exec api alembic upgrade head

migrate-create: ## Create new migration
	@read -p "Migration message: " message; \
	docker-compose exec api alembic revision --autogenerate -m "$$message"

migrate-downgrade: ## Downgrade last migration
	docker-compose exec api alembic downgrade -1

seed: ## Seed database with test data
	docker-compose exec api python scripts/seed_data.py

create-admin: ## Create admin user
	docker-compose exec api python scripts/create_admin.py

db-shell: ## Open PostgreSQL shell
	docker-compose exec postgres psql -U admin -d trueangels

redis-shell: ## Open Redis shell
	docker-compose exec redis redis-cli

# ==================== Testing ====================

test: ## Run all tests
	./scripts/run_tests.sh

test-unit: ## Run unit tests only
	./scripts/run_tests.sh --unit-only

test-integration: ## Run integration tests only
	./scripts/run_tests.sh --integration-only

test-chaos: ## Run chaos engineering tests
	./scripts/run_tests.sh --chaos

test-load: ## Run load tests
	./scripts/run_tests.sh --load

benchmark: ## Run benchmarks
	./scripts/run_tests.sh --benchmark

coverage: ## Generate coverage report
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term
	@echo "${GREEN}Coverage report generated at htmlcov/index.html${RESET}"

# ==================== Code Quality ====================

lint: ## Run linters
	docker-compose exec api black --check src/ tests/
	docker-compose exec api ruff check src/ tests/
	docker-compose exec api mypy src/

format: ## Format code
	docker-compose exec api black src/ tests/
	docker-compose exec api ruff check --fix src/ tests/

security: ## Run security scan
	docker scan trueangels_api:latest
	bandit -r src/ -f json -o bandit-report.json

# ==================== Backup & Restore ====================

backup: ## Create database backup
	@mkdir -p backups
	@docker-compose exec -T postgres pg_dump -U admin trueangels > backups/backup_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "${GREEN}Backup created at backups/backup_$(shell date +%Y%m%d_%H%M%S).sql${RESET}"

restore: ## Restore database from backup
	@read -p "Backup file path: " file; \
	docker-compose exec -T postgres psql -U admin trueangels < $$file
	@echo "${GREEN}Database restored from $$file${RESET}"

backup-all: ## Backup everything (DB + Redis + Config)
	@./scripts/full_backup.sh

# ==================== Deployment ====================

deploy-dev: ## Deploy to development
	docker-compose -f docker-compose.dev.yml up -d
	@echo "${GREEN}Development environment started${RESET}"

deploy-prod: ## Deploy to production
	@echo "${YELLOW}Deploying to production...${RESET}"
	ssh ${DEPLOY_USER}@${DEPLOY_HOST} 'cd /opt/trueangels && docker-compose pull && docker-compose up -d'
	@echo "${GREEN}Production deployment completed${RESET}"

deploy-monitoring: ## Deploy monitoring stack
	docker-compose up -d prometheus grafana loki promtail
	@echo "${GREEN}Monitoring stack started${RESET}"

blue-green: ## Blue-Green deployment
	@./scripts/blue_green_deploy.sh

rollback: ## Rollback to previous version
	@./scripts/rollback.sh

# ==================== Monitoring ====================

health: ## Check service health
	@echo "${YELLOW}Checking service health...${RESET}"
	@curl -s http://localhost:8000/health | jq . || echo "API not responding"
	@curl -s http://localhost:8501/_stcore/health || echo "Streamlit not responding"
	@docker-compose exec postgres pg_isready || echo "PostgreSQL not ready"
	@docker-compose exec redis redis-cli ping || echo "Redis not ready"

metrics: ## Show Prometheus metrics
	@curl -s http://localhost:9090/api/v1/query?query=up | jq .

grafana: ## Open Grafana dashboard
	@echo "${GREEN}Grafana: http://localhost:3000 (admin/$$GRAFANA_PASSWORD)${RESET}"

prometheus: ## Open Prometheus UI
	@echo "${GREEN}Prometheus: http://localhost:9090${RESET}"

# ==================== Utilities ====================

shell: ## Open Python shell in API container
	docker-compose exec api python

clean: ## Clean cache and temporary files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/ .pytest_cache/ .mypy_cache/

logs-clean: ## Clean log files
	sudo journalctl --rotate
	sudo journalctl --vacuum-time=7d
	docker system prune -f

info: ## Show system information
	@echo "${GREEN}System Information:${RESET}"
	@echo "Docker Version: $$(docker --version)"
	@echo "Docker Compose Version: $$(docker-compose --version)"
	@echo "Python Version: $$(python3 --version)"
	@echo "Node Version: $$(node --version 2>/dev/null || echo 'not installed')"

# ==================== Quick Commands ====================

all: build up migrate seed ## Full setup (build + up + migrate + seed)

reset: down-volumes build up migrate seed ## Full reset

status: ps health ## Show status

update: build down up migrate ## Update to latest version

# ==================== Help ====================

.DEFAULT_GOAL := help