# Sicherheit

## Sicherheitsmeldungen

Bitte veroeffentliche potenzielle Sicherheitsprobleme nicht sofort als oeffentliches Issue. Nutze stattdessen GitHubs private Security-Advisory-Funktion im Repository.

Beschreibe nach Moeglichkeit:

- betroffene ManaVault-Version
- nachvollziehbare Schritte
- moegliche Auswirkungen
- bekannte Gegenmassnahmen

## Betriebshinweis

ManaVault trennt drei Dienste:

- Port `8000`: lokale Verwaltungsoberflaeche ohne Login; niemals direkt ins Internet stellen.
- Port `8001`: schreibgeschuetzte, tokenbasierte Deckfreigaben; nur ueber einen HTTPS-Tunnel veroeffentlichen.
- Port `8002`: vollstaendige Verwaltung mit eigenem Login; nur ueber HTTPS veroeffentlichen.

Passwoerter des externen Zugangs werden mit Scrypt gehasht. Sitzungen verwenden signierte, zeitlich begrenzte Secure-/HttpOnly-/SameSite-Cookies. Trotzdem ersetzt der Login weder HTTPS noch sichere, individuelle Passwoerter.

Die Dateien unter `data/` enthalten Sammlung, Decks, Freigabeschluessel und Zugangsdaten. Dieser Ordner wird von Git ignoriert und darf weder in Commits noch in Fehlerberichte aufgenommen werden.
