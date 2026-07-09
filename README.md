# ManaVault

ManaVault ist eine lokale Web-App fuer Magic: The Gathering Collection- und Deck-Management.

## Setup

Einfachste Variante unter Windows:

```text
ManaVault starten.bat
```

Das Skript erstellt bei Bedarf die lokale Python-Umgebung, installiert Abhaengigkeiten und startet die App.

Manuelle Variante:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Danach im Browser oeffnen:

```text
http://127.0.0.1:8000
```

## Linux / Raspberry Pi

Die Windows-Dateien bleiben bestehen. Fuer Linux gibt es eigene Skripte:

```bash
chmod +x start-linux.sh import-scryfall-linux.sh
./start-linux.sh
```

Auf einem Raspberry Pi ist die App danach im Netzwerk erreichbar unter:

```text
http://<raspberry-pi-ip>:8000
```

Die komplette Anleitung steht in:

```text
README-LINUX.md
```

Auf einem Linux-Server ohne Oberflaeche kann ManaVault direkt als Dienst installiert werden:

```bash
chmod +x install-linux-service.sh uninstall-linux-service.sh
sudo ./install-linux-service.sh
```

## Scryfall Import

Einfachste Variante:

```text
Scryfall Daten laden.bat
```

Das laedt den aktuellen Scryfall `all_cards` Bulk-Dump herunter und importiert ihn in `data/manavault.sqlite3`. Dadurch werden auch nicht-englische Drucke mit Feldern wie `printed_name` importiert.

Alternative in der laufenden App:

In der Weboberflaeche auf **Scryfall Bulk importieren** klicken. ManaVault nutzt Scryfalls Bulk-Data-Endpunkt, speichert die JSON-Datei lokal unter `data/` und importiert Kartendaten in SQLite. Deutsche Kartennamen werden ueber Scryfalls `printed_name` gefunden.

Es werden nur Bild-URLs gespeichert. Kartenbilder werden nicht vorab heruntergeladen.

## Datenhaltung

- `cards`: Scryfall-Kartendaten
- `card_copies`: einzelne physische Karten oder Proxies
- `locations`: Orte wie Stock, Binder, Box, Trade Binder und Deck
- `decks`: mehrere Decks
- `deck_slots`: geplante Deckliste, auch fuer Karten, die noch nicht als Copy vorhanden sind

Die Datenbank liegt unter:

```text
data/manavault.sqlite3
```

## Sammlung exportieren

In der Seite **Sammlung** gibt es den Button **Export**. Der Export kann als `JSONL` oder `Markdown` heruntergeladen werden.

Empfohlen fuer Deckvorschlaege ist `JSONL`: Jede Zeile beschreibt eine Karte mit Menge, freien Copies, Proxies, Fundorten, Tags, Preis und Sammlungswert. Proxies werden separat gezaehlt und nicht in den Kartenwert eingerechnet.

## API-Auszug

- `GET /api/cards/search?q=`
- `POST /api/cards/import-scryfall`
- `GET /api/collection`
- `GET /api/collection/export?format=jsonl`
- `POST /api/collection/copies`
- `PATCH /api/collection/copies/{id}`
- `DELETE /api/collection/copies/{id}`
- `GET /api/locations`
- `POST /api/locations`
- `GET /api/decks`
- `POST /api/decks`
- `GET /api/decks/{id}`
- `POST /api/decks/{id}/slots`
- `DELETE /api/decks/{id}/slots/{slot_id}`
- `GET /api/decks/{id}/status`
- `POST /api/decks/{id}/import-list`
- `GET /api/decks/{id}/export-list`
