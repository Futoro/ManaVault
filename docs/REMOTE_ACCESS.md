# Externer Zugriff und QR-Deckseiten

ManaVault trennt oeffentliche Deckansichten und die vollstaendige Verwaltung technisch voneinander. Dadurch koennen QR-Codes ohne Login geoeffnet werden, ohne Schreibfunktionen oder die Sammlung freizugeben.

## Dienste

| Port | Zugriff | Inhalt |
|---|---|---|
| `8000` | lokales Netzwerk | vollstaendige Verwaltung ohne Login |
| `8001` | nur `127.0.0.1` | freigegebene Deckseiten, ausschliesslich lesend |
| `8002` | nur `127.0.0.1` | vollstaendige Verwaltung mit Login |

Port `8000` darf niemals direkt ueber einen Router oder Tunnel ins Internet gestellt werden.

## Tailscale Funnel

Die folgenden Beispiele verwenden Tailscale Funnel. Der Server muss bereits mit Tailscale verbunden sein und Funnel fuer das eigene Tailnet erlauben.

### Oeffentliche Deckseiten

```bash
sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8001
```

Tailscale zeigt danach die oeffentliche HTTPS-Adresse an. Diese Adresse einmal in ManaVault speichern:

```bash
./scripts/configure-public-url.sh https://server.tailnet-name.ts.net:8443
```

Neu erstellte QR-Codes verwenden nun dauerhafte Freigabelinks unter dieser Adresse. Ein Freigabelink enthaelt einen langen zufaelligen Schluessel und zeigt nur das betreffende Deck. Er kann in ManaVault erneuert oder widerrufen werden.

### Vollstaendige Verwaltung mit Login

Zuerst Benutzername und ein langes, individuelles Passwort einrichten:

```bash
./scripts/configure-remote-login.sh
```

Danach den getrennten Dienst veroeffentlichen:

```bash
sudo tailscale funnel --bg --https=10000 http://127.0.0.1:8002
```

Die vollstaendige Oberflaeche ist dann unter `https://server.tailnet-name.ts.net:10000` erreichbar. Tailscale muss auf den zugreifenden Geraeten fuer Funnel-Adressen nicht aktiv sein.

## Kontrolle und Abschalten

Aktive Funnel-Konfiguration anzeigen:

```bash
tailscale funnel status
```

Deckfreigaben abschalten:

```bash
sudo tailscale funnel --https=8443 off
```

Externen Login abschalten:

```bash
sudo tailscale funnel --https=10000 off
```

## Sicherheitsregeln

- Ausschliesslich HTTPS-Adressen verwenden.
- Port `8000` nie oeffentlich weiterleiten.
- Fuer die Verwaltung ein eigenes, langes Passwort verwenden.
- Freigabelinks nur an Personen weitergeben, die das Deck sehen duerfen.
- `data/remote-auth.json`, `data/public-url.txt` und die Datenbank niemals ins Repository laden.
