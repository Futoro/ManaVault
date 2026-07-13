# ManaVault extern erreichbar machen

ManaVault verwendet zwei getrennte Dienste:

- `manavault` auf Port 8000: vollstaendige lokale Verwaltung
- `manavault-public` auf `127.0.0.1:8001`: nur freigegebene Deckansichten

Der Cloudflare Tunnel darf ausschliesslich auf `http://localhost:8001` zeigen.
Port 8000 darf nicht als oeffentlicher Tunnel eingetragen werden.

## Einrichtung

1. Domain in ein Cloudflare-Konto aufnehmen.
2. Im Cloudflare-Dashboard `Networking > Tunnels` oeffnen.
3. Einen Tunnel namens `manavault-public` erstellen.
4. Den angezeigten Linux-Installationsbefehl auf dem ManaVault-Server ausfuehren.
5. Eine `Published application` hinzufuegen:
   - Hostname: beispielsweise `decks.example.com`
   - Service: `http://localhost:8001`
6. Anschliessend im ManaVault-Ordner ausfuehren:

   `./configure-public-url.sh https://decks.example.com`

Danach erzeugt der QR-Button dauerhafte externe Freigabelinks. Jeder Link enthaelt
einen zufaelligen Schluessel. Nicht freigegebene Decks und alle Schreibfunktionen
sind ueber den oeffentlichen Dienst nicht erreichbar.

## Optional: komplette Verwaltung extern

Fuer die vollstaendige ManaVault-Oberflaeche kann im gleichen Tunnel ein zweiter
Hostname, beispielsweise `vault.example.com`, auf `http://localhost:8000` zeigen.
Dieser Hostname muss vor der Freigabe mit Cloudflare Access geschuetzt werden.
Die Access-Regel darf nur die eigene E-Mail-Adresse zulassen. Port 8000 darf nie
ohne diese Anmeldung oeffentlich erreichbar sein.
