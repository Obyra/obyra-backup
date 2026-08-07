# ============================================
# Multi-stage Dockerfile for OBYRA Flask App
# ============================================

# ---------------------------------------------
# Stage 1: Builder - Install dependencies
# ---------------------------------------------
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /app

# Install system dependencies needed for Python packages
# WeasyPrint needs: cairo, pango, gdk-pixbuf, libffi
# Matplotlib needs: freetype, libpng
# psycopg needs: postgresql-dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libpq-dev \
    libfreetype6-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency files
COPY requirements.txt pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------
# Stage 2: Runtime - Minimal production image
# ---------------------------------------------
FROM python:3.11-slim AS runtime

# Create non-root user for security
RUN groupadd -r obyra && useradd -r -g obyra obyra

# Set working directory
WORKDIR /app

# Install only runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    shared-mime-info \
    libpq5 \
    libfreetype6 \
    libpng16-16t64 \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=obyra:obyra . .

# Create necessary directories with proper permissions
RUN mkdir -p /app/instance /app/storage /app/reports /app/logs && \
    chown -R obyra:obyra /app/instance /app/storage /app/reports /app/logs

# Copy and set permissions for entrypoint script
# Normalize CRLF -> LF defensively (Windows hosts may reintroduce \r\n via git).
# Without this, the shebang is read as "#!/bin/bash\r" and exec fails with
# "no such file or directory".
COPY --chown=obyra:obyra docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

# NOTA: el container arranca como root para poder chown el volumen montado
# por Railway (mounts root:root 755). El entrypoint hace chown de
# $STORAGE_BASE a obyra:obyra y luego dropea privs con `gosu obyra` antes
# de ejecutar gunicorn. No mantenemos `USER obyra` aca a proposito.
# USER obyra  -- removido: ver docker-entrypoint.sh

# Environment variables
ENV FLASK_APP=app.py \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Use entrypoint script
ENTRYPOINT ["/docker-entrypoint.sh"]

# Default command (can be overridden in docker-compose)
#
# POR QUE 2 WORKERS Y NO 4 (2026-08-07)
# -------------------------------------
# Railway factura memoria reservada, y el 2026-08-07 el entorno se cayo por
# limite de compute. Medido en el contenedor de produccion: 1,09 GB de uso real
# (cgroup memory.current) contra 0,008 vCPU promedio -- o sea casi todo el gasto
# era RAM ociosa, no computo.
#
# Cada worker pesa ~309 MB porque blueprint_presupuestos/__init__.py importa
# WeasyPrint a nivel de modulo (arrastra cairo/pango/fontconfig) y, sin
# --preload, cada worker carga su copia entera. 4 x 309 MB era el gasto.
#
# --threads 4 compensa la concurrencia perdida casi gratis: gthread no duplica
# el interprete, asi que 2x4 = 8 requests concurrentes, igual que antes.
#
# --max-requests recicla workers periodicamente para acotar el crecimiento
# gradual de memoria; el jitter evita que los 2 se reciclen a la vez.
#
# El valor 2000 (y no 500) es a proposito: sin --preload, cada worker reciclado
# re-importa app.py y por lo tanto vuelve a correr runtime_migrations, que son
# 144 execute() de DDL/seeds idempotentes. Con el trafico actual (bots de uptime
# ~1-2/min + healthcheck) 500 se alcanzaba en 5-8 h, o sea ~4 recorridas de DDL
# por dia sin ningun leak que lo justifique. Con 2000 recicla ~1 vez por dia por
# worker: se conserva la red de seguridad y el churn pasa a ser despreciable.
#
# --timeout queda en 120: los PDF tardan 2-5s y el pipeline IA corre por lotes.
# Bajarlo mata requests legitimos.
#
# NO agregar --preload sin antes resolver el fork: app.py crea el engine de
# SQLAlchemy y corre runtime_migrations en el import, y los hijos heredarian las
# conexiones. Requiere gunicorn.conf.py con post_fork -> db.engine.dispose().
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "--max-requests", "2000", "--max-requests-jitter", "50", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
