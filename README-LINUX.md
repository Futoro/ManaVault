# ManaVault auf Linux / Raspberry Pi

Diese Anleitung laesst die Windows-Version unveraendert. Fuer Linux gibt es eigene Shell-Skripte:

- `start-linux.sh`
- `import-scryfall-linux.sh`
- `install-linux-service.sh`
- `uninstall-linux-service.sh`
- `backup-linux.sh`
- `install-linux-backup-timer.sh`
- optional: `linux/manavault.service.example` fuer systemd

## Server-Kurzvariante ohne Oberflaeche

Auf einem Raspberry Pi oder Linux-Server muss kein Browser gestartet werden. ManaVault laeuft dort einfach als Webdienst.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip

cd /home/pi/MagicVault
chmod +x start-linux.sh import-scryfall-linux.sh install-linux-service.sh uninstall-linux-service.sh backup-linux.sh install-linux-backup-timer.sh
sudo ./install-linux-service.sh
```

Danach laeuft ManaVault im Hintergrund und ist erreichbar unter:

```text
http://<server-ip>:8000
```

Status:

```bash
sudo systemctl status manavault
```

Logs:

```bash
journalctl -u manavault -f
```

## 1. Projekt auf den Pi kopieren

Kopiere den Projektordner auf den Raspberry Pi, z.B. nach:

```bash
/home/pi/MagicVault
```

Wenn du die bestehende Sammlung mitnehmen willst, kopiere auch:

```text
data/manavault.sqlite3
```

Wichtig: Die Windows-`.venv` nicht verwenden. Auf Linux wird eine neue `.venv` erstellt.

## 2. Systempakete installieren

Auf Raspberry Pi OS / Debian / Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

## 3. Skripte ausfuehrbar machen

Im Projektordner:

```bash
cd /home/pi/MagicVault
chmod +x start-linux.sh import-scryfall-linux.sh backup-linux.sh install-linux-backup-timer.sh
```

## 4. ManaVault starten

```bash
./start-linux.sh
```

Das Skript erstellt automatisch `.venv`, installiert die Python-Abhaengigkeiten und startet ManaVault auf Port `8000`.

Im Browser auf einem anderen Geraet im selben Netzwerk:

```text
http://<raspberry-pi-ip>:8000
```

Die IP findest du auf dem Pi mit:

```bash
hostname -I
```

## 5. Scryfall-Daten importieren

Einmalig oder wenn du die Kartendaten aktualisieren willst:

```bash
./import-scryfall-linux.sh
```

Das laedt Scryfall Bulk Data und importiert die Karten in:

```text
data/manavault.sqlite3
```

## Optional: Port oder Host aendern

Standard:

```text
Host: 0.0.0.0
Port: 8000
```

Anderer Port:

```bash
MANAVAULT_PORT=8080 ./start-linux.sh
```

Nur lokal auf dem Pi:

```bash
MANAVAULT_HOST=127.0.0.1 ./start-linux.sh
```

## Optional: Als systemd-Service dauerhaft laufen lassen

Einfachste Variante aus dem Projektordner:

```bash
sudo ./install-linux-service.sh
```

Das Skript erstellt die Python-Umgebung, installiert die Abhaengigkeiten und richtet `manavault.service` ein.

Service entfernen:

```bash
sudo ./uninstall-linux-service.sh
```

Manuelle Variante, Beispiel mit Projekt unter `/opt/manavault`:

```bash
sudo mkdir -p /opt
sudo cp -r /home/pi/MagicVault /opt/manavault
cd /opt/manavault
sudo chown -R pi:pi /opt/manavault
chmod +x start-linux.sh import-scryfall-linux.sh
./start-linux.sh
```

Wenn der erste Start funktioniert, mit `Strg+C` stoppen und Service einrichten:

```bash
sudo cp linux/manavault.service.example /etc/systemd/system/manavault.service
sudo systemctl daemon-reload
sudo systemctl enable manavault
sudo systemctl start manavault
```

Status pruefen:

```bash
sudo systemctl status manavault
```

Logs ansehen:

```bash
journalctl -u manavault -f
```

## Updates

Wenn du neue Projektdateien auf den Pi kopierst:

```bash
cd /home/pi/MagicVault
./start-linux.sh
```

Das Skript prueft die Abhaengigkeiten erneut und startet dann die App.

## Backup

Die wichtigste Datei ist:

```text
data/manavault.sqlite3
```

Diese Datei regelmaessig sichern. Sie enthaelt Sammlung, Decks, Orte und importierte Kartendaten.

## Backup in der Weboberflaeche

In ManaVault gibt es den Bereich **Backup**.

- **Export** laedt eine komplette `.sqlite3`-Sicherung herunter.
- **Import** spielt eine `.sqlite3`-Sicherung ein. Vor dem Ersetzen legt ManaVault automatisch ein Server-Backup unter `data/backups/` an.

## Tägliches Autobackup mit pCloud

ManaVault nutzt fuer Cloud-Backups `rclone`. Einmalig auf dem Linux-Server installieren:

```bash
sudo apt update
sudo apt install -y rclone
```

pCloud verbinden:

```bash
rclone config
```

Dabei ein neues Remote anlegen, z.B. mit dem Namen:

```text
pcloud
```

Dann im ManaVault-Ordner:

```bash
cd /home/adrian/MagicVault
chmod +x backup-linux.sh install-linux-backup-timer.sh
sudo ./install-linux-backup-timer.sh
```

Cloud-Ziel eintragen:

```bash
sudo nano /etc/default/manavault-backup
```

Dort z.B. setzen:

```text
RCLONE_REMOTE=pcloud:ManaVault
MANAVAULT_KEEP_LOCAL_BACKUPS=14
```

Testlauf:

```bash
sudo systemctl start manavault-backup.service
journalctl -u manavault-backup.service -n 80
```

Der Timer laeuft taeglich um 03:30 Uhr:

```bash
systemctl list-timers manavault-backup.timer
```
