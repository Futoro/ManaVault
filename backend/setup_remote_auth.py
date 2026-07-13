from __future__ import annotations

import getpass
import json
import os
import secrets
from pathlib import Path

from backend.remote import AUTH_FILE, b64encode, password_hash


def main() -> None:
    print("ManaVault externer Login")
    username = input("Benutzername [adrian]: ").strip() or "adrian"
    while True:
        password = getpass.getpass("Passwort (mindestens 12 Zeichen): ")
        if len(password) < 12:
            print("Das Passwort ist zu kurz.")
            continue
        confirmation = getpass.getpass("Passwort wiederholen: ")
        if password != confirmation:
            print("Die Passwoerter stimmen nicht ueberein.")
            continue
        break

    salt = secrets.token_bytes(16)
    payload = {
        "version": 1,
        "username": username,
        "salt": b64encode(salt),
        "password_hash": b64encode(password_hash(password, salt)),
        "session_secret": b64encode(secrets.token_bytes(32)),
    }
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = AUTH_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(AUTH_FILE)
    print(f"Login gespeichert: {AUTH_FILE}")


if __name__ == "__main__":
    main()
