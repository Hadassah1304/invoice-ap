#!/usr/bin/env bash
set -e

echo "=========================================="
echo "Resetting & freshly seeding AP Database..."
echo "=========================================="

# Remove existing database and any WAL / SHM journals
rm -f data/ap.db data/ap.db-wal data/ap.db-shm
mkdir -p data/uploads

# Detect CLI command runner
if command -v invoice-ap &> /dev/null; then
    CMD="invoice-ap"
elif [ -f "./.venv/bin/invoice-ap" ]; then
    CMD="./.venv/bin/invoice-ap"
elif command -v python3 &> /dev/null; then
    CMD="python3 -m invoice_pipeline.cli"
else
    CMD="python -m invoice_pipeline.cli"
fi

$CMD init-db --seed samples/seed.json

echo "Database reset complete! Seeded with demo vendors, POs, and items."
