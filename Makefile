.PHONY: dev-db migrate seed-categories

dev-db:
	docker-compose up -d db

migrate:
	alembic upgrade head

seed-categories:
	python seed_inventory_categories.py --global
