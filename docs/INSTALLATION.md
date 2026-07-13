# Installation und Betrieb

Diese Anleitung richtet einen eigenen ManaVault-Server unter Debian, Ubuntu oder einem vergleichbaren Linux-System ein. Fuer den normalen Betrieb ist keine grafische Oberflaeche auf dem Server notwendig.

## Voraussetzungen

- Python 3.11 oder neuer
- systemd fuer den dauerhaften Serverbetrieb
- Internetzugriff fuer Python-Pakete und Scryfall-Daten
- etwa 3 GB freier Speicher fuer Umgebung, Modelle und Kartendaten

Systempakete installieren:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip \
  tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng libgl1 libglib2.0-0
```

## 1. Projekt laden

Empfohlen wird Git, weil spaetere Aktualisierungen dadurch einfach bleiben:

```bash
cd ~
git clone https://github.com/Futoro/ManaVault.git
cd ManaVault
chmod +x scripts/*.sh
```

Alternativ kann das GitHub-Quellpaket entpackt werden. Der Projektordner darf beliebig heissen und muss dem spaeteren Benutzer gehoeren.

## 2. Dienste installieren

```bash
sudo ./scripts/install.sh
```

Das Skript erstellt `.venv`, installiert die Python-Abhaengigkeiten und richtet drei systemd-Dienste ein:

| Dienst | Adresse | Zweck |
|---|---|---|
| `manavault` | `0.0.0.0:8000` | lokale Verwaltung |
| `manavault-public` | `127.0.0.1:8001` | schreibgeschuetzte Deckfreigaben |
| `manavault-remote` | `127.0.0.1:8002` | Verwaltung mit Login |

Nur Port `8000` ist danach im lokalen Netzwerk erreichbar. Die beiden anderen Dienste lauschen ausschliesslich auf dem Server selbst und werden nur bei Bedarf ueber einen HTTPS-Tunnel bereitgestellt.

Status und Logs:

```bash
sudo systemctl status manavault --no-pager
journalctl -u manavault -f
```

## 3. Kartendaten importieren

```bash
./scripts/import-scryfall.sh
```

Der Import laedt Scryfalls Bulk-Daten, Tokens und Embleme. Kartenbilder werden nicht gesammelt heruntergeladen; ManaVault speichert nur deren URLs.

Nur Tokens und Karten-Token-Beziehungen aktualisieren:

```bash
./scripts/import-scryfall.sh --tokens-only
```

## Scanner pruefen

Wenn die OCR-Systempakete beim Schnellstart nicht installiert wurden:

```bash
sudo ./scripts/install-scanner.sh
```

Die Live-Kamera benoetigt im Browser HTTPS oder `localhost`. Fuer Mobilgeraete empfiehlt sich der in [REMOTE_ACCESS.md](REMOTE_ACCESS.md) beschriebene Tailscale-Zugang.

## Manueller Start ohne systemd

```bash
./scripts/start.sh
```

Der Prozess laeuft im Vordergrund und endet mit `Strg+C`.

## Backups

Ein sofortiges SQLite-Backup erstellen:

```bash
./scripts/backup.sh
```

Backups werden unter `data/backups/` gespeichert. Ein taeglicher systemd-Timer kann so eingerichtet werden:

```bash
sudo ./scripts/install-backup-timer.sh
```

Ein optionales rclone-Ziel wird in `/etc/default/manavault-backup` eingetragen, beispielsweise `pcloud:ManaVault`.

## Aktualisieren

Vor jeder Aktualisierung zuerst sichern:

```bash
cd ~/ManaVault
./scripts/backup.sh
git pull --ff-only
sudo ./scripts/install.sh
./scripts/import-scryfall.sh --tokens-only
```

Bei einer Installation aus einem GitHub-Quellpaket muss der neue Quellcode ueber die alten Programmdateien kopiert werden. Der komplette Ordner `data/` muss dabei erhalten bleiben.

## Deinstallation

```bash
sudo ./scripts/uninstall.sh
```

Das entfernt die systemd-Dienste. Projektdateien, Sammlung und Backups bleiben erhalten und koennen anschliessend bewusst geloescht oder archiviert werden.
