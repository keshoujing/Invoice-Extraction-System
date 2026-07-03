#!/usr/bin/env bash
# Interactive launcher: asks whether to load demo data, then starts the app.
set -euo pipefail
cd "$(dirname "$0")"

read -rp "Load demo data (sample invoices)? [y/N] " answer
if [[ "${answer:-}" =~ ^[Yy]$ ]]; then
  echo "Seeding demo data into the data volume..."
  docker compose --profile demo-data run --rm demo-data
fi

echo "Starting Invoice Archive AI at http://localhost:8000 ..."
docker compose up --build
