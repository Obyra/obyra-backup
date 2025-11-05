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
COPY --chown=obyra:obyra docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Switch to non-root user
USER obyra

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
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
