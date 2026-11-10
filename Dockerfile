FROM python:3.11-slim

# Install system dependencies for OCR (Tesseract), image processing (OpenCV / PyMuPDF), and SQLite
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    sqlite3 \
    bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests and application code
COPY pyproject.toml README.md config.yaml ./
COPY invoice_pipeline ./invoice_pipeline
COPY server ./server

# Install Python package and CLI
RUN pip install --no-cache-dir .

# Copy samples, data directories, and helper scripts
COPY samples ./samples
COPY data ./data
COPY scripts ./scripts

# Reset and seed database freshly during container build
RUN chmod +x ./scripts/*.sh && \
    rm -f data/ap.db data/ap.db-wal data/ap.db-shm && \
    mkdir -p data/uploads && \
    invoice-ap init-db --seed samples/seed.json

EXPOSE 8000

# Default configuration (runtime only requires EXPLABS_API_KEY)
ENV INVOICE_CONFIG=config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["invoice-ap", "serve", "--host", "0.0.0.0", "--port", "8000"]
