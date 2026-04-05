# FILE: Makefile
# MODULE: Makefile für einfache Entwicklung und Deployment

.PHONY: help build up down logs test lint migrate shell clean

# Colors
GREEN := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
RESET := $(shell tput -Txterm sgr0)

help: ## Show this help message
	@echo ''
	@echo '${GREEN}TrueAngels NGO Suite - Makefile${RESET}'
	@echo ''
	@echo '${YELLOW}Usage:${RESET}'
	@echo '  make <target>'
	@echo ''
	@echo '${YELLOW}Available targets:${RESET}'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  ${GREEN}%-15s${RESET} %s\n", $$1, $$2}'

build: ## Build Docker images
	docker-compose build

up: ## Start all services
	docker-compose up -d
	@echo "Services started. API: http://localhost:8000, Streamlit: http://localhost:8501"

down: ## Stop all services
	docker-compose down

down-volumes: ## Stop all services and remove volumes
	docker-compose down -v

logs: ## Show logs
	docker-compose logs -f

logs-api: ## Show API logs
	docker-compose logs -f api

logs-celery: ## Show Celery logs
	docker-compose logs -f celery_worker

test: ## Run tests
	docker-compose exec api pytest tests/ -v --cov=src

test-coverage: ## Run tests with coverage report
	docker-compose exec api pytest tests/ -v --cov=src --cov-report=html --cov-report=term
	@echo "Coverage report generated at htmlcov/index.html"

lint: ## Run linters
	docker-compose exec api black --check src/ tests/
	docker-compose exec api ruff check src/ tests/
	docker-compose exec api mypy src/

format: ## Format code
	docker-compose exec api black src/ tests/
	docker-compose exec api ruff check --fix src/ tests/

migrate: ## Run database migrations
	docker-compose exec api alembic upgrade head

migrate-create: ## Create new migration
	@read -p "Migration message: " message; \
	docker-compose exec api alembic revision --autogenerate -m "$$message"

migrate-downgrade: ## Downgrade last migration
	docker-compose exec api alembic downgrade -1

shell: ## Open Python shell
	docker-compose exec api python

shell-db: ## Open PostgreSQL shell
	docker-compose exec postgres psql -U admin -d trueangels

shell-redis: ## Open Redis shell
	docker-compose exec redis redis-cli

clean: ## Clean Python cache files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

backup: ## Create database backup
	docker-compose exec postgres pg_dump -U admin trueangels > backup_$(shell date +%Y%m%d_%H%M%S).sql

restore: ## Restore database from backup
	@read -p "Backup file: " file; \
	docker-compose exec -T postgres psql -U admin trueangels < $$file

dev: ## Start development environment
	docker-compose -f docker-compose.dev.yml up -d
	@echo "Development environment started"

dev-down: ## Stop development environment
	docker-compose -f docker-compose.dev.yml down

prod-deploy: ## Deploy to production
	@echo "Deploying to production..."
	ssh ${DEPLOY_USER}@${DEPLOY_HOST} 'cd /opt/trueangels && docker-compose pull && docker-compose up -d'

health: ## Check service health
	@curl -s http://localhost:8000/health | jq .
	@curl -s http://localhost:8501/_stcore/health

monitoring: ## Show monitoring URLs
	@echo "Prometheus: http://localhost:9090"
	@echo "Grafana: http://localhost:3000 (admin/$$GRAFANA_PASSWORD)"

seed: ## Seed database with test data
	docker-compose exec api python scripts/seed_data.py