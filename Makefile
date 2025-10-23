.PHONY: db.up db.provision db.migrate db.reset.local

DB_CONTAINER ?= obyra-pg
DB_IMAGE ?= postgres:16
DB_PORT ?= 5433
DB_USER ?= obyra
DB_PASSWORD ?= obyra
DB_NAME ?= obyra_dev
DB_SUPERUSER ?= $(DB_USER)

DB_URL ?= postgresql+psycopg://$(DB_USER):$(DB_PASSWORD)@localhost:$(DB_PORT)/$(DB_NAME)

export DATABASE_URL ?= $(DB_URL)
export ALEMBIC_DATABASE_URL ?= $(DB_URL)


db.up:
	@echo "Iniciando contenedor de PostgreSQL ($(DB_IMAGE)) en el puerto $(DB_PORT)..."
	docker run --name $(DB_CONTAINER) \
	    -e POSTGRES_USER=$(DB_USER) \
	    -e POSTGRES_PASSWORD=$(DB_PASSWORD) \
	    -e POSTGRES_DB=$(DB_NAME) \
	    -p $(DB_PORT):5432 \
	    -d $(DB_IMAGE) >/dev/null 2>&1 || docker start $(DB_CONTAINER) >/dev/null
	@echo "PostgreSQL listo: $(DB_URL)"


db.provision:
	@echo "Provisionando roles y permisos base (infra/sql/01_*.sql, 02_*.sql, 03_*.sql)..."
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_SUPERUSER) -d $(DB_NAME) < infra/sql/01_schemas_roles.sql
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_SUPERUSER) -d $(DB_NAME) < infra/sql/02_grants.sql
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_SUPERUSER) -d $(DB_NAME) < infra/sql/03_observability.sql
	@echo "Provisionamiento base completado."


db.migrate:
	@echo "Ejecutando migraciones con Alembic usando $${ALEMBIC_DATABASE_URL:-$(DB_URL)}"
	alembic upgrade head


db.reset.local:
        @echo "Ejecutando reinicio lógico de migraciones..."
        alembic downgrade base
        alembic upgrade head
