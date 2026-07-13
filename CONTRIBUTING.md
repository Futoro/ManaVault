# Zu ManaVault beitragen

Danke fuer dein Interesse an ManaVault.

## Lokale Entwicklung

1. Repository klonen.
2. Eine virtuelle Python-Umgebung erstellen.
3. `pip install -r requirements.txt` ausfuehren.
4. Mit `uvicorn backend.main:app --reload` starten.
5. `http://127.0.0.1:8000` oeffnen.

## Pull Requests

- Halte Aenderungen auf ein nachvollziehbares Thema begrenzt.
- Fuege bei Datenbankaenderungen eine rueckwaertskompatible Migration in `init_db()` hinzu.
- Teste mindestens `python -m py_compile backend/main.py backend/public.py` und `node --check frontend/app.js`.
- Nimm keine Datenbanken, Kartenbilder, persoenlichen Sammlungsdaten oder Zugangsdaten auf.
- Beschreibe sichtbare Aenderungen im `CHANGELOG.md`.

Fehlerberichte und Feature-Ideen koennen ueber die GitHub-Issue-Vorlagen eingereicht werden.
