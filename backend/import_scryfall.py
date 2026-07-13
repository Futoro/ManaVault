from __future__ import annotations

import argparse

from backend.main import import_scryfall_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Scryfall Bulk Data in ManaVault importieren.")
    parser.add_argument("--local-file", help="Optional: vorhandene Scryfall JSON-Datei importieren.")
    parser.add_argument("--limit", type=int, help="Optional: nur die ersten N Karten importieren.")
    parser.add_argument(
        "--tokens-only",
        action="store_true",
        help="Nur Tokens und Embleme laden; der grosse Kartenimport wird uebersprungen.",
    )
    args = parser.parse_args()

    if args.tokens_only:
        print("Lade Scryfall Tokens und Embleme...")
    else:
        print("Lade Scryfall Bulk Data. Das kann beim ersten Mal einige Minuten dauern...")
    result = import_scryfall_data(
        local_file=args.local_file,
        limit=args.limit,
        tokens_only=args.tokens_only,
    )
    print(f"Fertig: {result['imported']} Eintraege importiert oder aktualisiert.")
    if result.get("tokens_imported") is not None:
        print(f"Davon Tokens/Embleme: {result['tokens_imported']}")
    print(f"Quelle: {result['source']}")


if __name__ == "__main__":
    main()
