# ManaVault Assistent

Der ManaVault Assistent ist vollständig optional. Ohne Einrichtung funktionieren Sammlung, Scanner, Decks, Statistiken und alle übrigen Funktionen unverändert. Die normale ManaVault-Installation lädt weder Ollama noch ein KI-Modell herunter und reserviert keinen zusätzlichen Arbeitsspeicher.

Der Assistent kann ausschließlich lesend auf lokale Sammlungs-, Deck- und Scryfall-Daten zugreifen. Er kann keine Karten, Decks oder Einstellungen verändern.

## Kostenlose lokale Einrichtung mit Ollama

Diese Variante verarbeitet alle Anfragen auf dem eigenen ManaVault-Server. Sie benötigt keinen OpenAI-Schlüssel und verursacht keine API-Kosten.

Empfohlen für einen Mini-PC mit 16 GB RAM:

```bash
chmod +x scripts/*.sh
./scripts/configure-local-ai.sh
```

Das separate Skript installiert Ollama nur nach diesem ausdrücklichen Aufruf und lädt standardmäßig `qwen3:4b`. Das Modell belegt während der Benutzung typischerweise einige Gigabyte Arbeitsspeicher. ManaVault lässt es nach ungefähr fünf Minuten ohne Anfrage automatisch aus dem RAM entladen.

Ein anderes Modell kann beim Einrichten angegeben werden:

```bash
./scripts/configure-local-ai.sh qwen3:8b
```

Ein 8B-Modell liefert häufig bessere Antworten, benötigt aber mehr RAM und ist auf kleinen CPUs langsamer. Raspberry Pis und schwache Server sollten den Assistenten deaktiviert lassen oder nur ein sehr kleines Modell ausprobieren.

## Alternative Einrichtung mit OpenAI

Wer stattdessen die kostenpflichtige OpenAI API verwenden möchte, führt aus:

```bash
./scripts/configure-openai.sh
```

Der Schlüssel wird in `data/openai-api-key.txt` mit eingeschränkten Dateirechten gespeichert und niemals an den Browser geschickt. OpenAI-API-Anfragen verwenden `store: false`. Das OpenAI-Modell kann über `MANAVAULT_OPENAI_MODEL` geändert werden.

## Assistent deaktivieren

```bash
./scripts/disable-ai-assistant.sh
```

Das deaktiviert den Assistenten, löscht aber bewusst keine bereits heruntergeladenen Modelle. Ollama kann unabhängig von ManaVault deinstalliert werden.

## Datenschutz und Grenzen

- Bei Ollama bleiben Fragen und lokale Werkzeugergebnisse auf dem eigenen Server.
- Bei OpenAI werden nur die für eine Frage benötigten Werkzeugergebnisse an die API übertragen.
- Der Gesprächsverlauf liegt nur für die aktuelle Browsersitzung im `sessionStorage`.
- Antworten lokaler und externer Sprachmodelle können Fehler enthalten. Wichtige Kartentexte und Regeln sollten geprüft werden.
