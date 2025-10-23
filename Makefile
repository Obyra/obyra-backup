.PHONY: db.up db.migrate db.reset.local

DB_CONTAINER ?= obyra-pg
DB_IMAGE ?= postgres:16
DB_PORT ?= 5433
DB_USER ?= obyra
DB_PASSWORD ?= obyra
DB_NAME ?= obyra_dev

DB_URL ?= postgresql+psycopg://$(DB_USER):$(DB_PASSWORD)@localhost:$(DB_PORT)/$(DB_NAME)

export DATABASE_URL ?= $(DB_URL)
export ALEMBIC_DATABASE_URL ?= $(DB_URL)


db.up:
@echo "Iniciando contenedor de PostgreSQL ($(DB_IMAGE)) en el puerto $(DB_PORT)..."
docker run --name $(DB_CONTAINER) -e POSTGRES_USER=$(DB_USER) -e POSTGRES_PASSWORD=$(DB_PASSWORD) -e POSTGRES_DB=$(DB_NAME) -p $(DB_PORT):5432 -d $(DB_IMAGE) >/dev/null 2>&1 || docker start $(DB_CONTAINER) >/dev/null
@echo "Asegurando esquema app..."
docker exec $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) -c "CREATE SCHEMA IF NOT EXISTS app" >/dev/null
@echo "PostgreSQL listo: $(DB_URL)"


db.migrate:
@echo "Ejecutando migraciones con Alembic usando $${ALEMBIC_DATABASE_URL:-$(DB_URL)}"
alembic upgrade head


db.reset.local:
@echo "Reiniciando base de datos local..."
-docker rm -f $(DB_CONTAINER) >/dev/null 2>&1
@$(MAKE) db.up
