@echo off
REM Interactive launcher: asks whether to load demo data, then starts the app.
cd /d "%~dp0"

set /p answer=Load demo data (sample invoices)? [y/N]
if /i "%answer%"=="y" (
  echo Seeding demo data into the data volume...
  docker compose --profile demo-data run --rm demo-data
)

echo Starting Invoice Archive AI at http://localhost:8000 ...
docker compose up --build
