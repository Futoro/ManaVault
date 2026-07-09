@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Erstelle lokale Python-Umgebung...
  python -m venv .venv
  if errorlevel 1 (
    echo Python konnte nicht gefunden werden.
    pause
    exit /b 1
  )
)

echo Pruefe Abhaengigkeiten...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Abhaengigkeiten konnten nicht installiert werden.
  pause
  exit /b 1
)

echo.
echo ManaVault startet...
echo Browser-Adresse: http://127.0.0.1:8000
echo Dieses Fenster offen lassen, solange ManaVault laufen soll.
echo.

set "MANAVAULT_URL=http://127.0.0.1:8000/?fresh=%RANDOM%%RANDOM%"
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$url='%MANAVAULT_URL%'; for ($i = 0; $i -lt 40; $i++) { try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/' -TimeoutSec 1 | Out-Null; Start-Process $url; exit } catch { Start-Sleep -Milliseconds 500 } }; Start-Process $url"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
pause
