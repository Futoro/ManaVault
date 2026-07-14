# ManaVault

[![Release](https://img.shields.io/github/v/release/Futoro/ManaVault)](https://github.com/Futoro/ManaVault/releases)
[![CI](https://github.com/Futoro/ManaVault/actions/workflows/ci.yml/badge.svg)](https://github.com/Futoro/ManaVault/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ManaVault ist ein selbst gehosteter Sammlungs- und Deckmanager fuer **Magic: The Gathering**. Er verwaltet konkrete Originale und Proxys, erkennt Karten per Smartphone-Kamera und zeigt, welche Karten in Decks gebunden oder noch nicht vorhanden sind.

## Funktionen

- Sammlung mit Druck, Sprache, Zustand, Originalen und Proxys
- lokale Scryfall-Kartendaten inklusive Tokens und Emblemen
- Live-Kartenscanner mit Kamera, OCR und schnellem Mehrfachimport
- Deckbuilder mit Hauptdeck, Sideboard, Varianten und Fehlkarten
- getrennte Tokens sowie Hinweise auf benoetigtes Deckzubehoer
- Deckwerte, Einkaufsliste und Cardmarket-Export
- QR-Codes fuer schreibgeschuetzte Deckansichten
- optionaler, passwortgeschuetzter externer Zugriff
- SQLite-Backups und optionales taegliches rclone-Backup
- optionaler, kontextabhängiger KI-Assistent über kostenlose lokale Modelle oder OpenAI

## Schnellstart

Unterstuetzt werden Debian, Ubuntu und vergleichbare Linux-Server mit Python 3.11 oder neuer.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip \
  tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng libgl1 libglib2.0-0

git clone https://github.com/Futoro/ManaVault.git
cd ManaVault
bash INSTALLIEREN.sh
./scripts/import-scryfall.sh
```

Danach ist ManaVault im lokalen Netzwerk unter `http://<server-ip>:8000` erreichbar. Der erste Scryfall-Import kann mehrere Minuten dauern.

## Projektstruktur

```text
backend/          FastAPI-Anwendung, Datenbank und Kartenimport
frontend/         Weboberflaeche
scripts/          Installation, Betrieb, Import und Backups
deploy/systemd/   optionale systemd-Beispiele
docs/             Installation und externer Zugriff
data/             lokale Laufzeitdaten; wird nicht versioniert
```

Historische Update-ZIPs, Windows-Starter, Datenbanken und persoenliche Exporte gehoeren nicht in das Repository. Ein frischer Checkout enthaelt nur die Dateien, die fuer Installation und Betrieb benoetigt werden.

Bei einem Versionstag erzeugt GitHub automatisch saubere ZIP- und TAR-Pakete unter [Releases](https://github.com/Futoro/ManaVault/releases). Diese Artefakte werden nicht im Quellbaum gespeichert.

## Dokumentation

- [Installation und Betrieb](docs/INSTALLATION.md)
- [Externer Zugriff und QR-Deckseiten](docs/REMOTE_ACCESS.md)
- [ManaVault Assistent einrichten](docs/AI_ASSISTANT.md)
- [Sicherheit](SECURITY.md)
- [Aenderungen](CHANGELOG.md)
- [Mitwirken](CONTRIBUTING.md)

## Sicherheit

Die lokale Verwaltungsoberflaeche auf Port `8000` besitzt keinen Login und darf nicht direkt ins Internet gestellt werden. Fuer externe Nutzung stellt ManaVault getrennte Dienste fuer schreibgeschuetzte Deckseiten und die passwortgeschuetzte Verwaltung bereit.

Der Ordner `data/` enthaelt die Sammlung und Zugangsdaten. Er wird von Git ignoriert und muss separat gesichert werden.

## Drittanbieter und Lizenz

ManaVault verwendet die oeffentliche Scryfall-API, Scryfall-Bulk-Daten und von Scryfall bereitgestellte Bild-URLs. Scryfall ist nicht mit diesem Projekt verbunden.

Magic: The Gathering, Kartennamen, Kartentexte, Symbole und Illustrationen sind Eigentum ihrer jeweiligen Rechteinhaber. Dieses Repository lizenziert ausschliesslich den ManaVault-Quellcode unter der [MIT-Lizenz](LICENSE).
