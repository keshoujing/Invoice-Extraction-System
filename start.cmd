@echo off
REM Interactive launcher: asks whether to load demo data, then starts the app.
cd /d "%~dp0"

if not exist "secrets\gemini-service-account.json" (
  echo WARNING: secrets\gemini-service-account.json not found.
  echo   Live invoice recognition needs a Google Cloud service-account key -- without it,
  echo   uploads will fail to recognize suppliers ^(see secrets\README.md^).
  echo   You can still explore the app with demo data.
  echo.
)

set /p answer=Load demo data (sample invoices)? [y/N]
if /i "%answer%"=="y" (
  echo Seeding demo data into the data volume...
  docker compose --profile demo-data run --rm demo-data
)

echo Starting Invoice Archive AI at http://localhost:8000 ...
docker compose up --build
