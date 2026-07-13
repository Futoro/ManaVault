# ManaVault

[![Release](https://img.shields.io/github/v/release/Futoro/ManaVault)](https://github.com/Futoro/ManaVault/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Public Beta](https://img.shields.io/badge/status-public%20beta-orange.svg)](CHANGELOG.md)

ManaVault ist ein selbst gehosteter Sammlungs- und Deckmanager fuer **Magic: The Gathering**. Der Schwerpunkt liegt auf der physischen Sammlung: ManaVault weiss, welche konkrete Karte frei ist, in welchem Deck sie steckt oder fuer eine Deckliste noch fehlt.

> **Projektstatus:** Public Beta. Backups vor Updates werden ausdruecklich empfohlen.

## Funktionen

- lokale Sammlung mit einzelnen Originalen und Proxys
- schneller Kartenimport ueber Scryfalls Bulk-Daten
- Karten-Scanner fuer Setcode und Sammlernummer
- Deckbuilder mit physischen Karten-Zuordnungen und Fehlkarten
- benannte Deckvarianten mit genau einer aktiven, physisch belegenden Variante
- getrennte Bereiche fuer Hauptdeck, Sideboard und Tokens
- automatische Token-Empfehlungen und Deckzubehoer-Hinweise
- Deckwerte, Planung, Einkaufsliste und Cardmarket-Wants-Export
- QR-Codes und separater schreibgeschuetzter Dienst fuer Deckfreigaben
- kleine Nutzerdaten-Backups sowie vollstaendige SQLite-Backups
- Windows-, Linux-, Raspberry-Pi- und systemd-Skripte

## Schnellstart unter Windows

Voraussetzung: eine aktuelle Python-3-Installation.

```powershell
git clone https://github.com/Futoro/ManaVault.git
cd ManaVault
```

Danach `ManaVault starten.bat` doppelt anklicken. Das Skript erstellt die virtuelle Python-Umgebung, installiert die Abhaengigkeiten und oeffnet ManaVault unter:

```text
http://127.0.0.1:8000
```

## Schnellstart unter Linux oder auf einem Raspberry Pi

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip unzip
git clone https://github.com/Futoro/ManaVault.git
cd ManaVault
chmod +x start-linux.sh
./start-linux.sh
```

Im lokalen Netzwerk ist die App danach unter `http://<server-ip>:8000` erreichbar.

Fuer den dauerhaften Betrieb als systemd-Dienst:

```bash
chmod +x install-linux-service.sh
sudo ./install-linux-service.sh
```

Die ausfuehrliche Anleitung steht in [README-LINUX.md](README-LINUX.md). Fuer eine extern erreichbare, ausschliesslich lesende Deckansicht siehe [README-PUBLIC.md](README-PUBLIC.md).

## Erster Kartenimport

Unter Windows kann `Scryfall Daten laden.bat` gestartet werden. Unter Linux:

```bash
chmod +x import-scryfall-linux.sh
./import-scryfall-linux.sh
```

Alternativ kann der Import in der laufenden Weboberflaeche unter **Daten** gestartet werden. ManaVault verwendet Scryfalls Bulk-Data-Endpunkt und speichert Kartendaten lokal in SQLite. Kartenbilder werden nicht vorab heruntergeladen; gespeichert werden lediglich die Bild-URLs.

Wenn die Karten bereits importiert wurden und nur Tokens oder Embleme aktualisiert werden sollen:

```bash
./import-scryfall-linux.sh --tokens-only
```

## Deckvarianten und Sideboard

Ein neues Deck besitzt zunaechst nur seinen aktuellen Stand. Im Deckbuilder stehen drei Aktionen zur Verfuegung:

- **Speichern** aktualisiert den aktiven Deckstand.
- **Verwerfen** stellt den Zustand beim Oeffnen wieder her.
- **Als neue Variante** bewahrt den bisherigen Stand und aktiviert eine neue benannte Variante.

Beim ersten Aufteilen wird der vorherige Stand automatisch als `Original` gespeichert. Nur die aktive Variante belegt Karten aus der Sammlung. Beim Aktivieren einer unvollstaendigen Variante bleiben nicht verfuegbare Karten sichtbar als fehlend markiert.

Hauptdeck und Sideboard werden getrennt gespeichert und angezeigt, gehoeren bei der aktiven Variante aber beide zum physischen Deck.

## Backups und Updates

Die lokale Datenbank liegt standardmaessig unter:

```text
data/manavault.sqlite3
```

Dieser Ordner wird von Git ignoriert. Sammlungsdaten gehoeren niemals in Commits oder Issues.

Im Bereich **Daten** koennen ein kleines Nutzerdaten-Backup und ein vollstaendiges Datenbank-Backup erstellt werden. Linux-Update-Skripte sichern die Datenbank vor der Installation automatisch.

Fertige Versionen und Linux-Update-Pakete erscheinen unter [GitHub Releases](https://github.com/Futoro/ManaVault/releases).

## Sicherheit

Die Verwaltungsoberflaeche auf Port `8000` besitzt aktuell keine Benutzeranmeldung. Sie ist fuer ein vertrauenswuerdiges lokales Netzwerk gedacht und darf nicht direkt ins Internet gestellt werden.

Fuer oeffentliche QR-Decklinks stellt ManaVault einen getrennten Nur-Lese-Dienst bereit. Weitere Hinweise stehen in [SECURITY.md](SECURITY.md).

## Entwicklung

Manueller Entwicklungsstart:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Die wichtigsten Schnittstellen sind ueber FastAPIs automatisch erzeugte Dokumentation unter `/docs` einsehbar. Hinweise fuer Beitraege stehen in [CONTRIBUTING.md](CONTRIBUTING.md).

## Drittanbieter und rechtlicher Hinweis

ManaVault verwendet die oeffentliche Scryfall-API, Scryfall-Bulk-Daten und von Scryfall bereitgestellte Bild-URLs. Scryfall ist nicht mit diesem Projekt verbunden.

ManaVault ist inoffizieller Fan-Content und weder von Wizards genehmigt noch unterstuetzt. Teile der verwendeten Materialien sind Eigentum von Wizards of the Coast. © Wizards of the Coast LLC.

Magic: The Gathering, Kartennamen, Kartentexte, Symbole und Illustrationen sind Eigentum ihrer jeweiligen Rechteinhaber. Dieses Repository lizenziert ausschliesslich den ManaVault-Quellcode; heruntergeladene Kartendaten und Kartenbilder sind nicht Bestandteil der MIT-Lizenz.

## Lizenz

Der ManaVault-Quellcode steht unter der [MIT-Lizenz](LICENSE).
