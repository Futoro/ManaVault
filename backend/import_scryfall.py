from __future__ import annotations

import argparse

from backend.main import import_scryfall_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Scryfall Bulk Data in ManaVault importieren.")
    parser.add_argument("--local-file", help="Optional: vorhandene Scryfall JSON-Datei importieren.")
    parser.add_argument("--limit", type=int, help="Optional: nur die ersten N Karten importieren.")
    args = parser.parse_args()

    print("Lade Scryfall Bulk Data. Das kann beim ersten Mal einige Minuten dauern...")
    result = import_scryfall_data(local_file=args.local_file, limit=args.limit)
    print(f"Fertig: {result['imported']} Karten importiert.")
    print(f"Quelle: {result['source']}")


if __name__ == "__main__":
    main()
