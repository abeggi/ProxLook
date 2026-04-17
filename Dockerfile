# ProxLook - Proxmox Inventory Dashboard
# Dockerfile for containerized deployment

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_PORT=8090 \
    LOG_LEVEL=INFO \
    LOG_PATH=/app/app.log \
    LOG_MAX_BYTES=5242880 \
    LOG_BACKUP_COUNT=5

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 proxlook && \
    mkdir -p /app && \
    chown -R proxlook:proxlook /app

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=proxlook:proxlook . .

# Create necessary directories and set permissions
RUN mkdir -p /app/data && \
    chown -R proxlook:proxlook /app/data && \
    chmod +x /app/manage.sh

# Switch to non-root user
USER proxlook

# Create default .env if not exists
RUN if [ ! -f /app/.env ]; then \
    echo "APP_PORT=8090" > /app/.env && \
    echo "DATABASE_URL=sqlite:////app/data/proxlook.db" >> /app/.env && \
    echo "LOG_LEVEL=INFO" >> /app/.env && \
    echo "LOG_PATH=/app/app.log" >> /app/.env && \
    echo "LOG_MAX_BYTES=5242880" >> /app/.env && \
    echo "LOG_BACKUP_COUNT=5" >> /app/.env; \
    fi

# Expose the application port
EXPOSE 8090

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8090/api/scan/status || exit 1

# Default command (can be overridden)
CMD ["python", "main.py"]