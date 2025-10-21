.PHONY: dev-db migrate seed-categories

dev-db:
	@docker compose up -d db

migrate:
	@FLASK_APP=wsgi.py flask db upgrade

seed-categories:
	@python seed_inventory_categories.py --global
