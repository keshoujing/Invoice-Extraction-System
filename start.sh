#!/usr/bin/env bash
# Interactive launcher: asks whether to load demo data, then starts the app.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f secrets/gemini-service-account.json ]; then
  echo "WARNING: secrets/gemini-service-account.json not found."
  echo "  Live invoice recognition needs a Google Cloud service-account key — without it,"
  echo "  uploads will fail to recognize suppliers (see secrets/README.md)."
  echo "  You can still explore the app with demo data."
  echo
fi

read -rp "Load demo data (sample invoices)? [y/N] " answer
if [[ "${answer:-}" =~ ^[Yy]$ ]]; then
  echo "Seeding demo data into the data volume..."
  docker compose --profile demo-data run --rm demo-data
fi

echo "Starting Invoice Archive AI at http://localhost:8000 ..."
docker compose up --build
