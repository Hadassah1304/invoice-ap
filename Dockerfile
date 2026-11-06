# Multi-stage slim build
FROM python:3.11-slim as builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY invoice_pipeline ./invoice_pipeline
COPY server ./server
COPY config.yaml ./config.yaml

RUN pip install --no-cache-dir .

EXPOSE 8000

ENV INVOICE_CONFIG=config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["invoice-ap", "serve", "--host", "0.0.0.0", "--port", "8000"]
