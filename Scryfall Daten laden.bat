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
echo Scryfall Bulk Data wird geladen und importiert.
echo Das kann beim ersten Mal mehrere Minuten dauern.
echo.

".venv\Scripts\python.exe" -m backend.import_scryfall
echo.
echo Fertig. Danach ManaVault starten und Karten suchen.
pause
