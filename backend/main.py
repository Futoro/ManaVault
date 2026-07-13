from __future__ import annotations

import json
import base64
import io
import os
import re
import secrets
import shutil
import sqlite3
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("MANAVAULT_DB_PATH", DATA_DIR / "manavault.sqlite3"))
BACKUP_DIR = DATA_DIR / "backups"
FRONTEND_DIR = BASE_DIR / "frontend"
VERSION_FILE = BASE_DIR / "VERSION"
PUBLIC_URL_FILE = DATA_DIR / "public-url.txt"
SCRYFALL_BULK_URL = "https://api.scryfall.com/bulk-data"
SCRYFALL_TOKEN_SEARCH_URL = (
    "https://api.scryfall.com/cards/search?unique=prints&order=set&include_multilingual=true&q="
    "%28layout%3Atoken%20or%20layout%3Adouble_faced_token%20or%20layout%3Aemblem%29"
)
USER_AGENT = "ManaVault/0.1 (local collection manager; no api keys)"
CARDMARKET_SEARCH_URL = "https://www.cardmarket.com/en/Magic/Products/Search?searchString="
SCRYFALL_BULK_TYPE = "all_cards"
SCRYFALL_IMPORT_LOCK = Lock()
RAPID_OCR_LOCK = Lock()
RAPID_OCR_ENGINE: Any = None
SCRYFALL_IMPORT_STATUS: dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "message": "Bereit.",
    "imported": None,
    "error": None,
    "started_at": None,
    "finished_at": None,
}

app = FastAPI(title="ManaVault", version="0.1.0")


@app.middleware("http")
async def no_cache_for_local_frontend(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


class ImportRequest(BaseModel):
    local_file: str | None = None
    limit: int | None = None
    bulk_type: str | None = None
    tokens_only: bool = False


def set_scryfall_import_status(**updates: Any) -> None:
    SCRYFALL_IMPORT_STATUS.update(updates)


def scryfall_import_status() -> dict[str, Any]:
    return dict(SCRYFALL_IMPORT_STATUS)


class LocationIn(BaseModel):
    name: str
    type: str = "Stock"


class LocationPatch(BaseModel):
    name: str | None = None
    type: str | None = None


class DeckIn(BaseModel):
    name: str
    format: str = "Commander"
    commander_card_id: int | None = None
    notes: str | None = None


class DeckPatch(BaseModel):
    name: str | None = None
    format: str | None = None
    commander_card_id: int | None = None
    notes: str | None = None


class CopyIn(BaseModel):
    card_id: int
    is_proxy: bool = False
    condition: str | None = "NM"
    language: str | None = "en"
    foil: bool = False
    location_id: int | None = None
    assigned_deck_id: int | None = None
    note: str | None = None


class CopyBatchIn(CopyIn):
    quantity: int = 1


class ScannerFrameIn(BaseModel):
    image_data: str
    collector_data: str | None = None
    collector_wide_data: str | None = None
    full_image_data: str | None = None
    live: bool = False


class ScannerReportIn(BaseModel):
    image_data: str
    expected: str | None = None
    result: dict[str, Any] | None = None


class CopyPatch(BaseModel):
    card_id: int | None = None
    is_proxy: bool | None = None
    condition: str | None = None
    language: str | None = None
    foil: bool | None = None
    location_id: int | None = None
    assigned_deck_id: int | None = None
    note: str | None = None


class DeckSlotIn(BaseModel):
    card_id: int
    quantity: int = 1
    allow_proxy: bool = True
    note: str | None = None
    zone: str = "mainboard"


class DeckAddCardIn(BaseModel):
    card_id: int
    quantity: int = 1
    action: str = "auto"
    copy_id: int | None = None
    allow_proxy: bool = True
    zone: str = "mainboard"


class DeckSlotZoneIn(BaseModel):
    zone: str


class DeckVariantCreateIn(BaseModel):
    name: str
    base_name: str = "Original"


class DeckVariantPatchIn(BaseModel):
    name: str


DECK_ZONES = {"mainboard", "sideboard"}


def normalized_deck_zone(value: str | None) -> str:
    zone = str(value or "mainboard").strip().lower()
    if zone not in DECK_ZONES:
        raise HTTPException(status_code=400, detail="Unbekannter Deckbereich.")
    return zone


class DeckAssignFreeIn(BaseModel):
    card_id: int | None = None
    scope: str = "cards"


class DeckListImport(BaseModel):
    text: str
    replace: bool = False


class CardTagsPatch(BaseModel):
    manual_tags: list[str] = []
    rejected_auto_tags: list[str] = []


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 30000")
    return db


def db_dep():
    db = get_db()
    try:
        yield db
    finally:
        db.close()


def backup_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def checkpoint_database() -> None:
    if not DB_PATH.exists():
        return
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def create_database_backup(prefix: str = "manavault-backup") -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"{prefix}-{backup_timestamp()}.sqlite3"
    with sqlite3.connect(DB_PATH, timeout=30) as source:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)
    return backup_path


def validate_backup_database(path: Path) -> None:
    required_tables = {"cards", "locations", "decks", "card_copies", "deck_slots"}
    try:
        with sqlite3.connect(path) as db:
            integrity = db.execute("PRAGMA quick_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise HTTPException(status_code=400, detail="Backup-Datei ist keine gueltige SQLite-Datenbank.")
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
    except sqlite3.DatabaseError as error:
        raise HTTPException(status_code=400, detail="Backup-Datei konnte nicht gelesen werden.") from error
    missing = required_tables - tables
    if missing:
        raise HTTPException(status_code=400, detail="Backup-Datei passt nicht zu ManaVault.")


def rows_as_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def table_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def insert_backup_rows(db: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    allowed_columns = set(table_columns(db, table))
    for row in rows:
        columns = [column for column in row.keys() if column in allowed_columns]
        if not columns:
            continue
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        values = [row[column] for column in columns]
        db.execute(
            f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})",
            values,
        )


def build_user_data_backup(db: sqlite3.Connection) -> dict[str, Any]:
    card_ids = {
        row["card_id"]
        for row in db.execute(
            """
            SELECT card_id FROM card_copies
            UNION
            SELECT card_id FROM deck_slots
            UNION
            SELECT card_id FROM deck_variant_slots
            UNION
            SELECT commander_card_id AS card_id FROM decks WHERE commander_card_id IS NOT NULL
            UNION
            SELECT commander_card_id AS card_id FROM deck_variants WHERE commander_card_id IS NOT NULL
            """
        ).fetchall()
        if row["card_id"] is not None
    }
    card_rows: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    if card_ids:
        placeholders = ", ".join("?" for _ in card_ids)
        card_rows = rows_as_dicts(
            db.execute(f"SELECT * FROM cards WHERE id IN ({placeholders}) ORDER BY id", tuple(card_ids)).fetchall()
        )
        tag_rows = rows_as_dicts(
            db.execute(f"SELECT * FROM card_tags WHERE card_id IN ({placeholders}) ORDER BY card_id", tuple(card_ids)).fetchall()
        )
    return {
        "kind": "manavault-userdata-backup",
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "cards": card_rows,
        "card_tags": tag_rows,
        "locations": rows_as_dicts(db.execute("SELECT * FROM locations ORDER BY id").fetchall()),
        "decks": rows_as_dicts(db.execute("SELECT * FROM decks ORDER BY id").fetchall()),
        "card_copies": rows_as_dicts(db.execute("SELECT * FROM card_copies ORDER BY id").fetchall()),
        "deck_slots": rows_as_dicts(db.execute("SELECT * FROM deck_slots ORDER BY id").fetchall()),
        "deck_variants": rows_as_dicts(db.execute("SELECT * FROM deck_variants ORDER BY id").fetchall()),
        "deck_variant_slots": rows_as_dicts(db.execute("SELECT * FROM deck_variant_slots ORDER BY id").fetchall()),
        "copy_history": rows_as_dicts(db.execute("SELECT * FROM copy_history ORDER BY id").fetchall()),
    }


def restore_user_data_backup(payload: dict[str, Any]) -> dict[str, int]:
    if payload.get("kind") != "manavault-userdata-backup" or payload.get("version") != 1:
        raise HTTPException(status_code=400, detail="Diese Datei ist kein ManaVault-Datenbackup.")
    expected_lists = ["cards", "card_tags", "locations", "decks", "card_copies", "deck_slots"]
    for key in expected_lists:
        if not isinstance(payload.get(key), list):
            raise HTTPException(status_code=400, detail="Datenbackup ist unvollstaendig.")
    history_rows = payload.get("copy_history", [])
    if not isinstance(history_rows, list):
        raise HTTPException(status_code=400, detail="Historie im Datenbackup ist ungueltig.")
    for key in ("deck_variants", "deck_variant_slots"):
        if not isinstance(payload.get(key, []), list):
            raise HTTPException(status_code=400, detail="Variantendaten im Datenbackup sind ungueltig.")
    if DB_PATH.exists():
        checkpoint_database()
        create_database_backup("manavault-before-data-import")
    with get_db() as db:
        db.executescript(
            """
            DELETE FROM deck_slots;
            DELETE FROM deck_variant_slots;
            DELETE FROM deck_variants;
            DELETE FROM card_copies;
            DELETE FROM decks;
            DELETE FROM locations;
            DELETE FROM card_tags;
            DELETE FROM cards;
            """
        )
        insert_backup_rows(db, "cards", payload["cards"])
        insert_backup_rows(db, "card_tags", payload["card_tags"])
        insert_backup_rows(db, "locations", payload["locations"])
        insert_backup_rows(db, "decks", payload["decks"])
        insert_backup_rows(db, "card_copies", payload["card_copies"])
        insert_backup_rows(db, "deck_slots", payload["deck_slots"])
        insert_backup_rows(db, "deck_variants", payload.get("deck_variants", []))
        insert_backup_rows(db, "deck_variant_slots", payload.get("deck_variant_slots", []))
        db.execute("DELETE FROM copy_history")
        insert_backup_rows(db, "copy_history", history_rows)
        db.commit()
    init_db()
    return {
        **{key: len(payload[key]) for key in expected_lists},
        "deck_variants": len(payload.get("deck_variants", [])),
        "deck_variant_slots": len(payload.get("deck_variant_slots", [])),
        "copy_history": len(history_rows),
    }


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with get_db() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scryfall_id TEXT NOT NULL UNIQUE,
                oracle_id TEXT,
                name TEXT NOT NULL,
                printed_name TEXT,
                lang TEXT,
                released_at TEXT,
                mana_cost TEXT,
                cmc REAL,
                type_line TEXT,
                printed_type_line TEXT,
                oracle_text TEXT,
                printed_text TEXT,
                power TEXT,
                toughness TEXT,
                loyalty TEXT,
                colors TEXT,
                color_identity TEXT,
                legalities TEXT,
                set_code TEXT,
                set_name TEXT,
                collector_number TEXT,
                rarity TEXT,
                image_url TEXT,
                prices_json TEXT,
                layout TEXT,
                is_token INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                format TEXT,
                commander_card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
                notes TEXT,
                public_share_token TEXT
            );

            CREATE TABLE IF NOT EXISTS card_copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                is_proxy INTEGER NOT NULL DEFAULT 0,
                condition TEXT,
                language TEXT,
                foil INTEGER NOT NULL DEFAULT 0,
                location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
                assigned_deck_id INTEGER REFERENCES decks(id) ON DELETE SET NULL,
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS copy_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                copy_id INTEGER,
                card_id INTEGER NOT NULL,
                card_name TEXT NOT NULL,
                action TEXT NOT NULL,
                from_name TEXT,
                to_name TEXT,
                is_proxy INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS deck_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 1,
                allow_proxy INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                zone TEXT NOT NULL DEFAULT 'mainboard',
                UNIQUE(deck_id, card_id, zone)
            );

            CREATE TABLE IF NOT EXISTS deck_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                commander_card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE(deck_id, name)
            );

            CREATE TABLE IF NOT EXISTS deck_variant_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                variant_id INTEGER NOT NULL REFERENCES deck_variants(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 1,
                allow_proxy INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                zone TEXT NOT NULL DEFAULT 'mainboard',
                UNIQUE(variant_id, card_id, zone)
            );

            CREATE TABLE IF NOT EXISTS deck_edit_sessions (
                deck_id INTEGER PRIMARY KEY REFERENCES decks(id) ON DELETE CASCADE,
                base_variant_id INTEGER,
                baseline_slots_json TEXT NOT NULL,
                baseline_commander_card_id INTEGER,
                started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS card_tags (
                card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
                auto_tags TEXT NOT NULL DEFAULT '[]',
                manual_tags TEXT NOT NULL DEFAULT '[]',
                rejected_auto_tags TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS card_token_links (
                source_scryfall_id TEXT NOT NULL,
                token_scryfall_id TEXT NOT NULL,
                token_name TEXT NOT NULL,
                token_type_line TEXT,
                PRIMARY KEY (source_scryfall_id, token_scryfall_id)
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
            CREATE INDEX IF NOT EXISTS idx_cards_printed_name ON cards(printed_name);
            CREATE INDEX IF NOT EXISTS idx_cards_lang ON cards(lang);
            CREATE INDEX IF NOT EXISTS idx_cards_lang_set_collector ON cards(lang, set_code, collector_number);
            CREATE INDEX IF NOT EXISTS idx_cards_oracle_lang_set ON cards(oracle_id, lang, set_code);
            CREATE INDEX IF NOT EXISTS idx_cards_lang_name_set ON cards(lang, name, set_code);
            CREATE INDEX IF NOT EXISTS idx_cards_rarity ON cards(rarity);
            CREATE INDEX IF NOT EXISTS idx_cards_oracle_id ON cards(oracle_id);
            CREATE INDEX IF NOT EXISTS idx_copies_card ON card_copies(card_id);
            CREATE INDEX IF NOT EXISTS idx_copies_deck ON card_copies(assigned_deck_id);
            CREATE INDEX IF NOT EXISTS idx_copy_history_created ON copy_history(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_copy_history_card ON copy_history(card_id);
            CREATE INDEX IF NOT EXISTS idx_slots_deck ON deck_slots(deck_id);
            CREATE INDEX IF NOT EXISTS idx_variants_deck ON deck_variants(deck_id);
            CREATE INDEX IF NOT EXISTS idx_variant_slots_variant ON deck_variant_slots(variant_id);
            CREATE INDEX IF NOT EXISTS idx_card_token_links_source ON card_token_links(source_scryfall_id);
            CREATE INDEX IF NOT EXISTS idx_card_token_links_token ON card_token_links(token_scryfall_id);

            CREATE TRIGGER IF NOT EXISTS history_copy_insert
            AFTER INSERT ON card_copies
            BEGIN
                INSERT INTO copy_history (copy_id, card_id, card_name, action, to_name, is_proxy)
                VALUES (
                    NEW.id,
                    NEW.card_id,
                    (SELECT COALESCE(printed_name, name) FROM cards WHERE id = NEW.card_id),
                    CASE WHEN NEW.assigned_deck_id IS NOT NULL THEN 'deck_added' ELSE 'added' END,
                    CASE
                        WHEN NEW.assigned_deck_id IS NOT NULL THEN (SELECT name FROM decks WHERE id = NEW.assigned_deck_id)
                        WHEN NEW.location_id IS NOT NULL THEN (SELECT name FROM locations WHERE id = NEW.location_id)
                        ELSE 'Sammlung'
                    END,
                    NEW.is_proxy
                );
            END;

            CREATE TRIGGER IF NOT EXISTS history_copy_move
            AFTER UPDATE OF location_id, assigned_deck_id ON card_copies
            WHEN OLD.location_id IS NOT NEW.location_id OR OLD.assigned_deck_id IS NOT NEW.assigned_deck_id
            BEGIN
                INSERT INTO copy_history (copy_id, card_id, card_name, action, from_name, to_name, is_proxy)
                VALUES (
                    NEW.id,
                    NEW.card_id,
                    (SELECT COALESCE(printed_name, name) FROM cards WHERE id = NEW.card_id),
                    CASE
                        WHEN OLD.assigned_deck_id IS NULL AND NEW.assigned_deck_id IS NOT NULL THEN 'deck_added'
                        WHEN OLD.assigned_deck_id IS NOT NULL AND NEW.assigned_deck_id IS NULL THEN 'deck_removed'
                        WHEN OLD.assigned_deck_id IS NOT NEW.assigned_deck_id THEN 'deck_moved'
                        ELSE 'moved'
                    END,
                    CASE
                        WHEN OLD.assigned_deck_id IS NOT NULL THEN (SELECT name FROM decks WHERE id = OLD.assigned_deck_id)
                        WHEN OLD.location_id IS NOT NULL THEN (SELECT name FROM locations WHERE id = OLD.location_id)
                        ELSE 'Sammlung'
                    END,
                    CASE
                        WHEN NEW.assigned_deck_id IS NOT NULL THEN (SELECT name FROM decks WHERE id = NEW.assigned_deck_id)
                        WHEN NEW.location_id IS NOT NULL THEN (SELECT name FROM locations WHERE id = NEW.location_id)
                        ELSE 'Sammlung'
                    END,
                    NEW.is_proxy
                );
            END;

            CREATE TRIGGER IF NOT EXISTS history_copy_delete
            BEFORE DELETE ON card_copies
            BEGIN
                INSERT INTO copy_history (copy_id, card_id, card_name, action, from_name, is_proxy)
                VALUES (
                    OLD.id,
                    OLD.card_id,
                    (SELECT COALESCE(printed_name, name) FROM cards WHERE id = OLD.card_id),
                    'deleted',
                    CASE
                        WHEN OLD.assigned_deck_id IS NOT NULL THEN (SELECT name FROM decks WHERE id = OLD.assigned_deck_id)
                        WHEN OLD.location_id IS NOT NULL THEN (SELECT name FROM locations WHERE id = OLD.location_id)
                        ELSE 'Sammlung'
                    END,
                    OLD.is_proxy
                );
            END;
            """
        )
        existing_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(cards)").fetchall()
        }
        for column_name, column_type in [
            ("printed_name", "TEXT"),
            ("printed_type_line", "TEXT"),
            ("printed_text", "TEXT"),
            ("layout", "TEXT"),
            ("is_token", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if column_name not in existing_columns:
                db.execute(f"ALTER TABLE cards ADD COLUMN {column_name} {column_type}")
        if "is_token" not in existing_columns:
            db.execute(
                """
                UPDATE cards
                SET is_token = CASE
                    WHEN lower(COALESCE(layout, '')) IN ('token', 'double_faced_token', 'emblem') THEN 1
                    WHEN lower(COALESCE(type_line, '')) LIKE 'token %' THEN 1
                    WHEN lower(COALESCE(type_line, '')) = 'emblem' THEN 1
                    WHEN lower(COALESCE(type_line, '')) LIKE 'emblem %' THEN 1
                    ELSE 0
                END
                """
            )
        db.execute("CREATE INDEX IF NOT EXISTS idx_cards_is_token ON cards(is_token)")
        deck_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(decks)").fetchall()
        }
        if "public_share_token" not in deck_columns:
            db.execute("ALTER TABLE decks ADD COLUMN public_share_token TEXT")
        if "active_variant_id" not in deck_columns:
            db.execute("ALTER TABLE decks ADD COLUMN active_variant_id INTEGER")
        variant_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(deck_variants)").fetchall()
        }
        if "commander_card_id" not in variant_columns:
            db.execute("ALTER TABLE deck_variants ADD COLUMN commander_card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL")
        slot_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(deck_slots)").fetchall()
        }
        if "zone" not in slot_columns:
            db.executescript(
                """
                CREATE TABLE deck_slots_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    allow_proxy INTEGER NOT NULL DEFAULT 1,
                    note TEXT,
                    zone TEXT NOT NULL DEFAULT 'mainboard',
                    UNIQUE(deck_id, card_id, zone)
                );
                INSERT INTO deck_slots_migrated (id, deck_id, card_id, quantity, allow_proxy, note, zone)
                SELECT id, deck_id, card_id, quantity, allow_proxy, note, 'mainboard' FROM deck_slots;
                DROP TABLE deck_slots;
                ALTER TABLE deck_slots_migrated RENAME TO deck_slots;
                CREATE INDEX IF NOT EXISTS idx_slots_deck ON deck_slots(deck_id);
                """
            )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_decks_public_share_token "
            "ON decks(public_share_token) WHERE public_share_token IS NOT NULL"
        )
        location_count = db.execute("SELECT COUNT(*) AS count FROM locations").fetchone()["count"]
        seeded_defaults = db.execute(
            "SELECT value FROM app_meta WHERE key = 'default_locations_seeded'"
        ).fetchone()
        if not seeded_defaults and location_count == 0:
            for name, type_ in [
                ("Stock", "Stock"),
                ("Binder", "Binder"),
                ("Box", "Box"),
                ("Trade Binder", "Trade Binder"),
                ("Deck", "Deck"),
            ]:
                db.execute(
                    "INSERT INTO locations (name, type) VALUES (?, ?)",
                    (name, type_),
                )
        if not seeded_defaults:
            db.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('default_locations_seeded', '1')"
            )
        db.commit()
        missing = db.execute(
            """
            SELECT c.id, c.type_line, c.oracle_text
            FROM cards c
            LEFT JOIN card_tags ct ON ct.card_id = c.id
            WHERE ct.card_id IS NULL
            LIMIT 2000
            """
        ).fetchall()
        for row in missing:
            ensure_card_tags(db, row["id"], row["type_line"], row["oracle_text"])
        db.commit()


@app.on_event("startup")
def startup() -> None:
    init_db()


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def json_load(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


TAG_CATALOG = [
    "Removal",
    "Boardwipe",
    "Counterspell",
    "Tutor",
    "Ramp",
    "Card Draw",
    "Recursion",
    "Reanimation",
    "Protection",
    "Token Maker",
    "Sac Outlet",
    "Graveyard",
    "Lifegain",
    "Stax",
    "Finisher",
    "Land",
]


TAG_RULES: list[tuple[str, list[str]]] = [
    ("Boardwipe", ["destroy all", "exile all", "return all", "all creatures", "each creature", "each nonland"]),
    ("Counterspell", ["counter target spell", "counter target activated", "counter target triggered"]),
    ("Tutor", ["search your library", "search their library", "search target player's library"]),
    ("Ramp", ["add {", "add one mana", "add two mana", "search your library for a land", "put a land card", "put a basic land"]),
    ("Card Draw", ["draw a card", "draw two cards", "draw three cards", "draw x cards", "draw that many cards"]),
    ("Removal", ["destroy target", "exile target", "return target", "deals damage to target", "fight target", "target creature gets -", "sacrifice target"]),
    ("Recursion", ["return target card from your graveyard", "return target permanent card", "from your graveyard to your hand"]),
    ("Reanimation", ["return target creature card from your graveyard to the battlefield", "put target creature card from a graveyard onto the battlefield"]),
    ("Protection", ["hexproof", "indestructible", "protection from", "phase out", "prevent all damage"]),
    ("Token Maker", ["create a", "create two", "create x", "token"]),
    ("Sac Outlet", ["sacrifice another", "sacrifice a creature", "sacrifice an artifact", "sacrifice a permanent"]),
    ("Graveyard", ["graveyard", "mill", "surveil", "escape", "flashback", "delirium"]),
    ("Lifegain", ["gain life", "you gain", "lifelink"]),
    ("Stax", ["can't cast", "can't attack", "doesn't untap", "players can't", "opponents can't", "tax", "costs {1} more"]),
    ("Finisher", ["you win the game", "double strike", "trample", "extra turn", "combat phase"]),
]


def clean_tags(tags: list[str]) -> list[str]:
    known = set(TAG_CATALOG)
    result = []
    for tag in tags:
        value = str(tag).strip()
        match = next((known_tag for known_tag in known if known_tag.lower() == value.lower()), value)
        if match and match not in result:
            result.append(match)
    return result


def infer_tags_from_values(type_line: str | None, oracle_text: str | None) -> list[str]:
    text = f"{type_line or ''}\n{oracle_text or ''}".lower()
    tags = []
    if "land" in (type_line or "").lower():
        tags.append("Land")
    for tag, needles in TAG_RULES:
        if any(needle in text for needle in needles):
            tags.append(tag)
    if "destroy all" in text or "exile all" in text:
        tags = [tag for tag in tags if tag != "Removal"]
    return clean_tags(tags)


def effective_tags(auto_tags: list[str], manual_tags: list[str], rejected_auto_tags: list[str]) -> list[str]:
    rejected = {tag.lower() for tag in rejected_auto_tags}
    combined = [tag for tag in auto_tags if tag.lower() not in rejected]
    combined.extend(manual_tags)
    return clean_tags(combined)


def cardmarket_url(card_name: str) -> str:
    return f"{CARDMARKET_SEARCH_URL}{urllib.parse.quote_plus(card_name)}"


def price_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def card_price_eur(prices: dict[str, Any], foil: bool = False) -> float:
    if foil:
        return price_float(prices.get("eur_foil")) or price_float(prices.get("eur")) or 0.0
    return price_float(prices.get("eur")) or price_float(prices.get("eur_foil")) or 0.0


def card_price_eur_with_fallback(db: sqlite3.Connection, card: dict[str, Any]) -> tuple[float, str]:
    own_price = card_price_eur(json_load(card.get("prices_json"), {}))
    if own_price > 0:
        return own_price, "own"

    priced_where = """
      AND (
        CAST(NULLIF(json_extract(prices_json, '$.eur'), '') AS REAL) > 0
        OR CAST(NULLIF(json_extract(prices_json, '$.eur_foil'), '') AS REAL) > 0
      )
    """

    def first_price(sql: str, params: tuple[Any, ...], source: str) -> tuple[float, str] | None:
        row = db.execute(sql, params).fetchone()
        if not row:
            return None
        price = card_price_eur(json_load(row["prices_json"], {}))
        return (price, source) if price > 0 else None

    set_code = str(card.get("set_code") or "").strip()
    collector_number = str(card.get("collector_number") or "").strip()
    if set_code and collector_number:
        result = first_price(
            f"""
            SELECT prices_json
            FROM cards
            WHERE lang = 'en'
              AND set_code = ?
              AND collector_number = ?
              {priced_where}
            ORDER BY released_at DESC
            LIMIT 1
            """,
            (set_code.lower(), collector_number),
            "english_same_printing",
        )
        if result:
            return result

    oracle_id = card.get("oracle_id")
    if oracle_id:
        result = first_price(
            f"""
            SELECT prices_json
            FROM cards
            WHERE oracle_id = ?
              AND lang = 'en'
              AND set_code = ?
              {priced_where}
            ORDER BY released_at DESC
            LIMIT 1
            """,
            (oracle_id, set_code.lower()),
            "english_same_set",
        )
        if result:
            return result
        result = first_price(
            f"""
            SELECT prices_json
            FROM cards
            WHERE oracle_id = ? AND lang = 'en'
              {priced_where}
            ORDER BY released_at DESC
            LIMIT 1
            """,
            (oracle_id,),
            "english_oracle",
        )
        if result:
            return result

    english_name = str(card.get("name") or "").strip()
    if english_name:
        result = first_price(
            f"""
            SELECT prices_json
            FROM cards
            WHERE lang = 'en'
              AND name = ?
              {priced_where}
            ORDER BY
              CASE WHEN set_code = ? THEN 0 ELSE 1 END,
              released_at DESC
            LIMIT 1
            """,
            (english_name, set_code.lower()),
            "english_name",
        )
        if result:
            return result
    return 0.0, "missing"


def tag_payload(row: sqlite3.Row | None) -> dict[str, list[str]]:
    auto_tags = clean_tags(json_load(row["auto_tags"], []) if row else [])
    manual_tags = clean_tags(json_load(row["manual_tags"], []) if row else [])
    rejected_auto_tags = clean_tags(json_load(row["rejected_auto_tags"], []) if row else [])
    return {
        "auto_tags": auto_tags,
        "manual_tags": manual_tags,
        "rejected_auto_tags": rejected_auto_tags,
        "tags": effective_tags(auto_tags, manual_tags, rejected_auto_tags),
    }


def readonly_card_tags(db: sqlite3.Connection, card_id: int, type_line: str | None, oracle_text: str | None) -> dict[str, list[str]]:
    existing = db.execute("SELECT * FROM card_tags WHERE card_id = ?", (card_id,)).fetchone()
    if existing:
        return tag_payload(existing)
    auto_tags = infer_tags_from_values(type_line, oracle_text)
    return {
        "auto_tags": auto_tags,
        "manual_tags": [],
        "rejected_auto_tags": [],
        "tags": auto_tags,
    }


def ensure_card_tags(db: sqlite3.Connection, card_id: int, type_line: str | None, oracle_text: str | None) -> dict[str, list[str]]:
    existing = db.execute("SELECT * FROM card_tags WHERE card_id = ?", (card_id,)).fetchone()
    auto_tags = infer_tags_from_values(type_line, oracle_text)
    if existing:
        db.execute("UPDATE card_tags SET auto_tags = ? WHERE card_id = ?", (json_dump(auto_tags), card_id))
        existing = db.execute("SELECT * FROM card_tags WHERE card_id = ?", (card_id,)).fetchone()
    else:
        db.execute(
            "INSERT INTO card_tags (card_id, auto_tags, manual_tags, rejected_auto_tags) VALUES (?, ?, '[]', '[]')",
            (card_id, json_dump(auto_tags)),
        )
        existing = db.execute("SELECT * FROM card_tags WHERE card_id = ?", (card_id,)).fetchone()
    return tag_payload(existing)


def card_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["colors"] = json_load(data.get("colors"), [])
    data["color_identity"] = json_load(data.get("color_identity"), [])
    data["legalities"] = json_load(data.get("legalities"), {})
    data["prices_json"] = json_load(data.get("prices_json"), {})
    data["price_eur"] = card_price_eur(data["prices_json"])
    return data


def card_collection_counts(db: sqlite3.Connection, card_id: int) -> dict[str, int]:
    row = db.execute(
        """
        SELECT COUNT(*) AS total_count,
               COALESCE(SUM(CASE WHEN is_proxy = 0 THEN 1 ELSE 0 END), 0) AS owned_count,
               COALESCE(SUM(CASE WHEN is_proxy = 1 THEN 1 ELSE 0 END), 0) AS proxy_count,
               COALESCE(SUM(CASE WHEN assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_count,
               COALESCE(SUM(CASE WHEN is_proxy = 0 AND assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_original_count,
               COALESCE(SUM(CASE WHEN is_proxy = 1 AND assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_proxy_count,
               COALESCE(SUM(CASE WHEN assigned_deck_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS deck_count
        FROM card_copies
        WHERE card_id = ?
        """,
        (card_id,),
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def card_collection_counts_bulk(db: sqlite3.Connection, card_ids: list[int]) -> dict[int, dict[str, int]]:
    if not card_ids:
        return {}
    placeholders = ",".join("?" for _ in card_ids)
    rows = db.execute(
        f"""
        SELECT card_id,
               COUNT(*) AS total_count,
               COALESCE(SUM(CASE WHEN is_proxy = 0 THEN 1 ELSE 0 END), 0) AS owned_count,
               COALESCE(SUM(CASE WHEN is_proxy = 1 THEN 1 ELSE 0 END), 0) AS proxy_count,
               COALESCE(SUM(CASE WHEN assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_count,
               COALESCE(SUM(CASE WHEN is_proxy = 0 AND assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_original_count,
               COALESCE(SUM(CASE WHEN is_proxy = 1 AND assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_proxy_count,
               COALESCE(SUM(CASE WHEN assigned_deck_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS deck_count
        FROM card_copies
        WHERE card_id IN ({placeholders})
        GROUP BY card_id
        """,
        card_ids,
    ).fetchall()
    empty = {
        "total_count": 0,
        "owned_count": 0,
        "proxy_count": 0,
        "free_count": 0,
        "free_original_count": 0,
        "free_proxy_count": 0,
        "deck_count": 0,
    }
    result = {card_id: dict(empty) for card_id in card_ids}
    for row in rows:
        result[int(row["card_id"])] = {
            key: int(row[key] or 0)
            for key in empty
        }
    return result


def planned_rows_for_card(db: sqlite3.Connection, card_id: int) -> list[dict[str, Any]]:
    free_row = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM card_copies
        WHERE card_id = ? AND assigned_deck_id IS NULL
        """,
        (card_id,),
    ).fetchone()
    free_remaining = free_row["count"] if free_row else 0
    rows = db.execute(
        """
        SELECT d.name AS deck_name,
               ds.quantity - COUNT(cc.id) AS missing_quantity
        FROM deck_slots ds
        JOIN decks d ON d.id = ds.deck_id
        LEFT JOIN card_copies cc
          ON cc.card_id = ds.card_id
         AND cc.assigned_deck_id = ds.deck_id
        WHERE ds.card_id = ?
        GROUP BY ds.id, d.name, ds.quantity
        HAVING missing_quantity > 0
        ORDER BY d.name
        """,
        (card_id,),
    ).fetchall()
    planned = []
    for row in rows:
        missing = row["missing_quantity"]
        covered_by_collection = min(free_remaining, missing)
        free_remaining -= covered_by_collection
        planned_quantity = missing - covered_by_collection
        if planned_quantity <= 0:
            continue
        planned.append({
            "state": "Online",
            "place_name": row["deck_name"],
            "place_type": "Geplant",
            "is_proxy": 0,
            "quantity": planned_quantity,
        })
    return planned


def card_identity(card: dict[str, Any]) -> tuple[str, str, str]:
    faces = card.get("card_faces") or []
    image_url = ""
    if card.get("image_uris"):
        image_url = card["image_uris"].get("normal") or card["image_uris"].get("large") or ""
    elif faces and faces[0].get("image_uris"):
        image_url = faces[0]["image_uris"].get("normal") or faces[0]["image_uris"].get("large") or ""

    if faces:
        oracle_text = "\n\n".join(face.get("oracle_text", "") for face in faces if face.get("oracle_text"))
        mana_cost = " // ".join(face.get("mana_cost", "") for face in faces if face.get("mana_cost"))
    else:
        oracle_text = card.get("oracle_text") or ""
        mana_cost = card.get("mana_cost") or ""
    return image_url, mana_cost, oracle_text


def scryfall_card_is_token(card: dict[str, Any]) -> bool:
    layout = str(card.get("layout") or "").lower()
    type_line = str(card.get("type_line") or "").lower()
    return (
        layout in {"token", "double_faced_token", "emblem"}
        or type_line.startswith("token ")
        or type_line == "emblem"
        or type_line.startswith("emblem ")
    )


def upsert_cards(db: sqlite3.Connection, cards: list[dict[str, Any]]) -> int:
    rows = []
    tag_sources = []
    token_links: list[tuple[str, str, str, str | None]] = []
    for card in cards:
        if card.get("object") != "card" or not card.get("id") or not card.get("name"):
            continue
        image_url, mana_cost, oracle_text = card_identity(card)
        card_is_token = scryfall_card_is_token(card)
        rows.append(
            (
                card.get("id"),
                card.get("oracle_id"),
                card.get("name"),
                card.get("printed_name"),
                card.get("lang"),
                card.get("released_at"),
                mana_cost,
                card.get("cmc"),
                card.get("type_line"),
                card.get("printed_type_line"),
                oracle_text,
                card.get("printed_text"),
                card.get("power"),
                card.get("toughness"),
                card.get("loyalty"),
                json_dump(card.get("colors")),
                json_dump(card.get("color_identity")),
                json.dumps(card.get("legalities") or {}, ensure_ascii=False),
                card.get("set"),
                card.get("set_name"),
                card.get("collector_number"),
                card.get("rarity"),
                image_url,
                json.dumps(card.get("prices") or {}, ensure_ascii=False),
                card.get("layout"),
                int(card_is_token),
            )
        )
        tag_sources.append((card.get("id"), card.get("type_line"), oracle_text))
        related_parts = [part for part in (card.get("all_parts") or []) if part.get("object") == "related_card"]
        if card_is_token:
            for part in related_parts:
                if part.get("component") != "combo_piece" or not part.get("id"):
                    continue
                token_links.append((
                    str(part["id"]),
                    str(card["id"]),
                    str(card.get("name") or "Token"),
                    card.get("type_line"),
                ))
        else:
            for part in related_parts:
                if part.get("component") != "token" or not part.get("id"):
                    continue
                token_links.append((
                    str(card["id"]),
                    str(part["id"]),
                    str(part.get("name") or "Token"),
                    part.get("type_line"),
                ))
    db.executemany(
        """
        INSERT INTO cards (
            scryfall_id, oracle_id, name, printed_name, lang, released_at, mana_cost, cmc,
            type_line, printed_type_line, oracle_text, printed_text, power, toughness, loyalty, colors,
            color_identity, legalities, set_code, set_name, collector_number,
            rarity, image_url, prices_json, layout, is_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id) DO UPDATE SET
            oracle_id=excluded.oracle_id,
            name=excluded.name,
            printed_name=excluded.printed_name,
            lang=excluded.lang,
            released_at=excluded.released_at,
            mana_cost=excluded.mana_cost,
            cmc=excluded.cmc,
            type_line=excluded.type_line,
            printed_type_line=excluded.printed_type_line,
            oracle_text=excluded.oracle_text,
            printed_text=excluded.printed_text,
            power=excluded.power,
            toughness=excluded.toughness,
            loyalty=excluded.loyalty,
            colors=excluded.colors,
            color_identity=excluded.color_identity,
            legalities=excluded.legalities,
            set_code=excluded.set_code,
            set_name=excluded.set_name,
            collector_number=excluded.collector_number,
            rarity=excluded.rarity,
            image_url=excluded.image_url,
            prices_json=excluded.prices_json,
            layout=excluded.layout,
            is_token=excluded.is_token
        """,
        rows,
    )
    if token_links:
        db.executemany(
            """
            INSERT INTO card_token_links (source_scryfall_id, token_scryfall_id, token_name, token_type_line)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_scryfall_id, token_scryfall_id) DO UPDATE SET
                token_name=excluded.token_name,
                token_type_line=excluded.token_type_line
            """,
            token_links,
        )
    if tag_sources:
        id_to_card = {}
        for start in range(0, len(tag_sources), 500):
            chunk = tag_sources[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            id_to_card.update(
                {
                    row["scryfall_id"]: row["id"]
                    for row in db.execute(
                        f"SELECT id, scryfall_id FROM cards WHERE scryfall_id IN ({placeholders})",
                        [source[0] for source in chunk],
                    ).fetchall()
                }
            )
        for scryfall_id, type_line, oracle_text in tag_sources:
            card_id = id_to_card.get(scryfall_id)
            if card_id:
                ensure_card_tags(db, card_id, type_line, oracle_text)
    return len(rows)


def request_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def import_scryfall_tokens(db: sqlite3.Connection) -> int:
    """Import all separately listed token, double-faced-token and emblem printings."""
    imported = 0
    page = 0
    next_url: str | None = SCRYFALL_TOKEN_SEARCH_URL
    while next_url:
        page += 1
        set_scryfall_import_status(
            phase="tokens",
            message=f"Scryfall Tokens und Embleme werden importiert (Seite {page}).",
            imported=imported,
        )
        result = request_json(next_url)
        cards = result.get("data") or []
        imported += upsert_cards(db, cards)
        db.commit()
        next_url = result.get("next_page") if result.get("has_more") else None
        if next_url:
            time.sleep(0.1)
    expand_token_links_across_printings(db)
    db.commit()
    return imported


def expand_token_links_across_printings(db: sqlite3.Connection) -> int:
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO card_token_links (
            source_scryfall_id, token_scryfall_id, token_name, token_type_line
        )
        SELECT sibling.scryfall_id, link.token_scryfall_id, link.token_name, link.token_type_line
        FROM card_token_links link
        JOIN cards linked_source ON linked_source.scryfall_id = link.source_scryfall_id
        JOIN cards sibling ON sibling.oracle_id = linked_source.oracle_id
                          AND COALESCE(sibling.is_token, 0) = 0
        WHERE linked_source.oracle_id IS NOT NULL
        """
    )
    return max(0, int(cursor.rowcount or 0))


def download_file(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as response, target.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            if total:
                set_scryfall_import_status(
                    phase="download",
                    message=f"Scryfall-Daten werden geladen: {downloaded // 1024 // 1024} / {total // 1024 // 1024} MB",
                )
            else:
                set_scryfall_import_status(
                    phase="download",
                    message=f"Scryfall-Daten werden geladen: {downloaded // 1024 // 1024} MB",
                )


def iter_json_array(path: Path):
    decoder = json.JSONDecoder()
    buffer = ""
    in_array = False
    eof = False
    with path.open("r", encoding="utf-8") as handle:
        while True:
            if not eof and len(buffer) < 1024 * 1024:
                chunk = handle.read(1024 * 1024)
                if chunk:
                    buffer += chunk
                else:
                    eof = True
            buffer = buffer.lstrip()
            if not in_array:
                if buffer.startswith("\ufeff"):
                    buffer = buffer.lstrip("\ufeff")
                if not buffer:
                    if eof:
                        return
                    continue
                if buffer[0] != "[":
                    raise ValueError("Scryfall-Datei ist kein JSON-Array.")
                buffer = buffer[1:]
                in_array = True
                continue
            if not buffer:
                if eof:
                    return
                continue
            if buffer[0] == "]":
                return
            if buffer[0] == ",":
                buffer = buffer[1:]
                continue
            try:
                item, index = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if eof:
                    raise
                chunk = handle.read(1024 * 1024)
                if chunk:
                    buffer += chunk
                    continue
                eof = True
                continue
            yield item
            buffer = buffer[index:]


def import_scryfall_data(
    local_file: str | None = None,
    limit: int | None = None,
    bulk_type: str | None = None,
    tokens_only: bool = False,
) -> dict[str, Any]:
    set_scryfall_import_status(phase="prepare", message="Import wird vorbereitet.", error=None)
    init_db()
    if tokens_only:
        with get_db() as db:
            tokens_imported = import_scryfall_tokens(db)
        set_scryfall_import_status(
            phase="done",
            message=f"{tokens_imported} Tokens und Embleme importiert.",
            imported=tokens_imported,
        )
        return {
            "imported": tokens_imported,
            "cards_imported": 0,
            "tokens_imported": tokens_imported,
            "source": "Scryfall Kartensuche (Tokens und Embleme)",
        }
    if local_file:
        source = Path(local_file)
        if not source.exists():
            raise FileNotFoundError(f"local_file wurde nicht gefunden: {source}")
    else:
        selected_bulk_type = bulk_type or SCRYFALL_BULK_TYPE
        set_scryfall_import_status(phase="metadata", message="Scryfall-Metadaten werden abgefragt.")
        bulk = request_json(SCRYFALL_BULK_URL)
        entries = bulk.get("data", [])
        bulk_entry = next((item for item in entries if item.get("type") == selected_bulk_type), None)
        if not bulk_entry or not bulk_entry.get("download_uri"):
            raise RuntimeError(f"Scryfall Bulk Data konnte nicht gefunden werden: {selected_bulk_type}")
        source = DATA_DIR / f"scryfall-{selected_bulk_type}.json"
        set_scryfall_import_status(phase="download", message="Scryfall-Datendatei wird geladen.")
        download_file(bulk_entry["download_uri"], source)

    set_scryfall_import_status(phase="read", message="Kartendaten werden stueckweise gelesen.")
    imported = 0
    seen = 0
    batch: list[dict[str, Any]] = []
    with get_db() as db:
        for card in iter_json_array(source):
            seen += 1
            if limit and seen > limit:
                break
            batch.append(card)
            if len(batch) >= 1000:
                set_scryfall_import_status(
                    phase="database",
                    message=f"{seen} Karten gelesen, {imported} Karten importiert.",
                    imported=imported,
                )
                imported += upsert_cards(db, batch)
                db.commit()
                batch = []
        if batch:
            set_scryfall_import_status(
                phase="database",
                message=f"{seen} Karten gelesen, {imported} Karten importiert.",
                imported=imported,
            )
            imported += upsert_cards(db, batch)
            db.commit()
    tokens_imported = 0
    if limit is None:
        with get_db() as db:
            tokens_imported = import_scryfall_tokens(db)
    total_imported = imported + tokens_imported
    set_scryfall_import_status(
        phase="done",
        message=f"{imported} Karten und {tokens_imported} Tokens/Embleme importiert.",
        imported=total_imported,
    )
    return {
        "imported": total_imported,
        "cards_imported": imported,
        "tokens_imported": tokens_imported,
        "source": str(source),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/deck/{deck_id}")
def public_deck_page(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> FileResponse:
    if not db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    return FileResponse(FRONTEND_DIR / "index.html")


def configured_public_base_url() -> str | None:
    configured = os.environ.get("MANAVAULT_PUBLIC_URL", "").strip()
    if not configured and PUBLIC_URL_FILE.exists():
        configured = PUBLIC_URL_FILE.read_text(encoding="utf-8").strip()
    if not configured:
        return None
    parsed = urllib.parse.urlparse(configured)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return configured.rstrip("/")


def ensure_deck_share_token(deck_id: int, db: sqlite3.Connection) -> tuple[sqlite3.Row, str]:
    deck = db.execute(
        "SELECT id, name, public_share_token FROM decks WHERE id = ?",
        (deck_id,),
    ).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    token = str(deck["public_share_token"] or "").strip()
    if not token:
        token = secrets.token_urlsafe(24)
        db.execute("UPDATE decks SET public_share_token = ? WHERE id = ?", (token, deck_id))
        db.commit()
    return deck, token


@app.post("/api/decks/{deck_id}/share")
def create_deck_share(
    deck_id: int,
    request: Request,
    db: sqlite3.Connection = Depends(db_dep),
) -> dict[str, Any]:
    deck, token = ensure_deck_share_token(deck_id, db)
    base_url = configured_public_base_url()
    if not base_url:
        raise HTTPException(
            status_code=409,
            detail="Oeffentliche Adresse noch nicht eingerichtet.",
        )
    return {
        "deck_id": deck_id,
        "name": deck["name"],
        "token": token,
        "url": f"{base_url}/share/{token}",
    }


@app.post("/api/decks/{deck_id}/share/rotate")
def rotate_deck_share(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    if not db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    token = secrets.token_urlsafe(24)
    db.execute("UPDATE decks SET public_share_token = ? WHERE id = ?", (token, deck_id))
    db.commit()
    base_url = configured_public_base_url()
    return {"token": token, "url": f"{base_url}/share/{token}" if base_url else None}


@app.delete("/api/decks/{deck_id}/share")
def revoke_deck_share(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, bool]:
    cur = db.execute("UPDATE decks SET public_share_token = NULL WHERE id = ?", (deck_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    return {"revoked": True}


@app.get("/api/version")
def app_version() -> dict[str, str]:
    version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else app.version
    return {"version": version}


@app.get("/api/backups/download")
def download_backup() -> FileResponse:
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Noch keine ManaVault-Datenbank gefunden.")
    backup_path = create_database_backup()
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename=backup_path.name,
    )


@app.get("/api/backups/user-data")
def download_user_data_backup(db: sqlite3.Connection = Depends(db_dep)) -> Response:
    payload = build_user_data_backup(db)
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    filename = f"manavault-daten-{backup_timestamp()}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/backups/user-data/import")
async def import_user_data_backup(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Keine Backup-Datei empfangen.")
    if len(body) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Datenbackup ist groesser als 100 MB.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Datenbackup konnte nicht gelesen werden.") from error
    counts = restore_user_data_backup(payload)
    return {"status": "ok", "message": "Datenbackup importiert.", "counts": counts}


@app.post("/api/backups/import")
async def import_backup(request: Request) -> dict[str, str]:
    DATA_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)
    upload_path = BACKUP_DIR / f"manavault-upload-{backup_timestamp()}.sqlite3"
    size = 0
    with upload_path.open("wb") as file:
        async for chunk in request.stream():
            size += len(chunk)
            if size > 4 * 1024 * 1024 * 1024:
                upload_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Backup-Datei ist groesser als 4 GB.")
            file.write(chunk)
    if size == 0:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Keine Backup-Datei empfangen.")
    validate_backup_database(upload_path)
    if DB_PATH.exists():
        checkpoint_database()
        create_database_backup("manavault-before-import")
    for suffix in ("-wal", "-shm"):
        DB_PATH.with_name(f"{DB_PATH.name}{suffix}").unlink(missing_ok=True)
    shutil.copy2(upload_path, DB_PATH)
    init_db()
    return {"status": "ok", "message": "Backup importiert."}


@app.get("/api/cards/search")
def search_cards(
    q: str = "",
    colors: str = "",
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    card_type: str = "",
    tag: str = "",
    legal_format: str = "",
    rarity: str = "",
    set_code: str = "",
    langs: str = "en,de",
    sort: str = "name",
    min_price_eur: float | None = None,
    limit: int = 250,
    offset: int = 0,
    db: sqlite3.Connection = Depends(db_dep),
) -> list[dict[str, Any]]:
    conditions, params, order = card_filter_sql(q, colors, cmc_min, cmc_max, card_type, tag, legal_format, rarity, set_code, langs, sort)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    safe_limit = max(1, min(limit, 1000))
    safe_offset = max(0, offset)
    rows = db.execute(
        f"""
        SELECT c.*
        FROM cards c
        {where}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        [*params, safe_limit, safe_offset],
    ).fetchall()
    counts_by_card = card_collection_counts_bulk(db, [int(row["id"]) for row in rows])
    result = []
    for row in rows:
        card = card_row(row)
        card.update(counts_by_card.get(int(row["id"]), {}))
        card["price_source"] = "own" if card.get("price_eur", 0) > 0 else "missing"
        if min_price_eur is not None and card.get("price_eur", 0) < min_price_eur:
            continue
        card["tags"] = []
        result.append(card)
    return result


def normalized_card_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def scanner_card_matches(db: sqlite3.Connection, raw_text: str, limit: int = 8) -> tuple[str, list[dict[str, Any]]]:
    lines = [re.sub(r"\s+", " ", line).strip(" ._|[]{}") for line in raw_text.splitlines()]
    lines = [line for line in lines if 2 < len(line) < 70 and re.search(r"[A-Za-zÀ-ž]", line)]
    if not lines:
        return "", []
    query = lines[0]
    normalized_query = normalized_card_name(query)
    token = max(normalized_query.split(), key=len, default="")
    params: list[Any] = []
    where = "WHERE c.lang IN ('en', 'de')"
    if len(token) >= 3:
        where += " AND (LOWER(c.name) LIKE ? OR LOWER(COALESCE(c.printed_name, '')) LIKE ?)"
        params = [f"%{token}%", f"%{token}%"]
    rows = db.execute(
        f"""
        SELECT c.* FROM cards c
        {where}
        ORDER BY ABS(LENGTH(COALESCE(c.printed_name, c.name)) - ?) ASC,
                 COALESCE(c.printed_name, c.name), c.released_at DESC
        LIMIT 5000
        """,
        [*params, len(query)],
    ).fetchall()
    if not rows and token:
        rows = db.execute("SELECT c.* FROM cards c WHERE c.lang IN ('en', 'de') ORDER BY c.name LIMIT 50000").fetchall()
    scored = []
    for row in rows:
        names = [row["name"], row["printed_name"] or ""]
        score = max(SequenceMatcher(None, normalized_query, normalized_card_name(name)).ratio() for name in names if name)
        if score >= 0.74:
            scored.append((score, row))
    scored.sort(key=lambda item: item[1]["released_at"] or "", reverse=True)
    scored.sort(key=lambda item: (-item[0], item[1]["name"]))
    result = []
    seen: set[int] = set()
    for score, row in scored:
        card_id = int(row["id"])
        if card_id in seen:
            continue
        seen.add(card_id)
        card = card_row(row)
        card.update(card_collection_counts(db, card_id))
        card["scanner_score"] = round(score, 3)
        result.append(card)
        if len(result) >= limit:
            break
    return query, result


def normalized_collector_number(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
    match = re.fullmatch(r"0*([0-9]+)([A-Z]*)", value)
    return f"{int(match.group(1))}{match.group(2)}" if match else value


def scanner_print_matches(db: sqlite3.Connection, raw_text: str, limit: int = 8) -> tuple[str, list[dict[str, Any]]]:
    clean = re.sub(r"[^A-Z0-9/]+", " ", (raw_text or "").upper()).strip()
    tokens = clean.split()
    if not tokens:
        return clean, []
    known_sets = {str(row["set_code"]).upper() for row in db.execute("SELECT DISTINCT set_code FROM cards WHERE set_code IS NOT NULL")}
    set_codes = [token for token in tokens if token in known_sets]
    for token in tokens:
        if len(token) > 3 and token[-2:] in {"DE", "EN"} and token[:-2] in known_sets:
            set_codes.append(token[:-2])
    for token in list(set_codes):
        for index, char in enumerate(token):
            if char not in {"A", "E"}:
                continue
            alternative = f"{token[:index]}{'E' if char == 'A' else 'A'}{token[index + 1:]}"
            if alternative in known_sets and alternative not in set_codes:
                set_codes.append(alternative)
    if not set_codes:
        for token in tokens:
            if not 2 <= len(token) <= 6:
                continue
            token_as_letters = token.replace("0", "O").replace("1", "I").replace("5", "S")
            best = max(known_sets, key=lambda code: SequenceMatcher(None, token_as_letters, code).ratio(), default="")
            if best and SequenceMatcher(None, token_as_letters, best).ratio() >= 0.66:
                set_codes.append(best)
    set_codes = list(dict.fromkeys(set_codes))
    marked_numbers = []
    print_marker = ""
    for marked_match in re.finditer(r"(?:^|\s)([TCURML])\s*(0*[0-9O]{2,5})(?=\s|$)", clean):
        marked_token = f"{marked_match.group(1)}{marked_match.group(2)}"
        if marked_token in known_sets:
            continue
        if not print_marker:
            print_marker = marked_match.group(1)
        marked_numbers.append(marked_match.group(2))
    fraction = re.search(r"([0-9O]{1,5})\s*/\s*([0-9O]{2,5})", clean)
    number_tokens = marked_numbers or ([fraction.group(1)] if fraction else re.findall(r"[0-9O]{1,5}[A-Z]?", clean))
    numbers = [normalized_collector_number(token.replace("O", "0")) for token in number_tokens]
    upper_text = (raw_text or "").upper()
    language_hits = re.findall(r"(?:^|[^A-Z])(DE|EN)(?=$|[^A-Z])", upper_text)
    for set_code in set_codes:
        language_hits.extend(re.findall(rf"{re.escape(set_code)}[^A-Z0-9]{{0,3}}(DE|EN)", upper_text))
    languages = list(dict.fromkeys(token.lower() for token in language_hits))
    if not set_codes or not numbers:
        return clean, []
    result = []
    for set_code in set_codes:
        kind_sql = " AND c.is_token = 1" if print_marker == "T" else (" AND c.is_token = 0" if print_marker else "")
        rows = db.execute(
            f"SELECT c.* FROM cards c WHERE UPPER(c.set_code) = ? AND c.lang IN ('en', 'de'){kind_sql} ORDER BY c.released_at DESC",
            (set_code,),
        ).fetchall()
        rows = sorted(
            rows,
            key=lambda row: numbers.index(normalized_collector_number(row["collector_number"] or ""))
            if normalized_collector_number(row["collector_number"] or "") in numbers else len(numbers),
        )
        exact_rows = [
            row for row in rows
            if normalized_collector_number(row["collector_number"] or "") in numbers
        ]
        localized_rows = [row for row in exact_rows if not languages or row["lang"] in languages]
        language_inferred = bool(languages and not localized_rows and exact_rows)
        for row in localized_rows or exact_rows:
            card = card_row(row)
            if language_inferred:
                # Newly released sets sometimes reach the local Scryfall dump before
                # their localized row does.  The printed DE/EN marker is still more
                # trustworthy than silently rejecting an otherwise exact printing.
                card["lang"] = languages[0]
                card["scanner_language_inferred"] = True
            card.update(card_collection_counts(db, int(row["id"])))
            card["scanner_score"] = 1.0
            result.append(card)
            if len(result) >= limit:
                return clean, result
    return clean, result


def cards_matched_by_name_and_number(
    db: sqlite3.Connection,
    raw_name: str,
    raw_collector: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Resolve old frames that print a collector number but no set code."""
    normalized_name = normalized_card_name(raw_name)
    if len(normalized_name) < 3:
        return []
    number_tokens = re.findall(r"(?<![0-9])([0-9O]{2,4})(?![0-9])", raw_collector.upper())
    numbers = {
        normalized_collector_number(token.replace("O", "0"))
        for token in number_tokens
        if not (1993 <= int(token.replace("O", "0")) <= 2100)
    }
    if not numbers:
        return []
    rows = db.execute(
        "SELECT c.* FROM cards c WHERE c.lang IN ('en', 'de') AND CAST(c.collector_number AS INTEGER) IN (%s)"
        % ",".join("?" for _ in numbers),
        [int(number) for number in numbers if number.isdigit()],
    ).fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        if normalized_collector_number(row["collector_number"] or "") not in numbers:
            continue
        score = max(
            SequenceMatcher(None, normalized_name, normalized_card_name(name)).ratio()
            for name in (row["name"], row["printed_name"] or "") if name
        )
        if score >= 0.74:
            scored.append((score, row))
    if not scored:
        return []
    best_score = max(score for score, _ in scored)
    matches = []
    for score, row in scored:
        if score < best_score - 0.04:
            continue
        card = card_row(row)
        card.update(card_collection_counts(db, int(row["id"])))
        card["scanner_score"] = round(score, 3)
        matches.append(card)
    unique_prints = {
        (str(card.get("set_code") or ""), str(card.get("collector_number") or ""))
        for card in matches
    }
    # A number without a set is accepted only when the recognized card name makes
    # the physical printing unique.  This prevents copyright years from guessing.
    return matches[:limit] if len(unique_prints) == 1 else []


def cards_matched_by_name_and_set(
    db: sqlite3.Connection,
    raw_name: str,
    raw_text: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Resolve a printing when OCR has a strong name and set but damaged digits."""
    _, name_cards = scanner_card_matches(db, raw_name, limit=120)
    if not name_cards:
        return []
    upper_text = (raw_text or "").upper()
    clean_tokens = re.sub(r"[^A-Z0-9]+", " ", upper_text).split()
    known_sets = {str(row["set_code"]).upper() for row in db.execute("SELECT DISTINCT set_code FROM cards WHERE set_code IS NOT NULL")}
    set_codes = {token for token in clean_tokens if token in known_sets}
    languages = set(re.findall(r"(?:^|[^A-Z])(DE|EN)(?=$|[^A-Z])", upper_text))
    for token in clean_tokens:
        if len(token) > 3 and token[-2:] in {"DE", "EN"} and token[:-2] in known_sets:
            set_codes.add(token[:-2])
            languages.add(token[-2:])
    if not set_codes:
        return []
    matches = [
        card for card in name_cards
        if str(card.get("set_code") or "").upper() in set_codes
        and (not languages or str(card.get("lang") or "").upper() in languages)
    ]
    if not matches:
        return []
    best_score = max(float(card.get("scanner_score") or 0) for card in matches)
    matches = [card for card in matches if float(card.get("scanner_score") or 0) >= best_score - 0.04]
    unique_prints = {
        (str(card.get("set_code") or ""), normalized_collector_number(card.get("collector_number") or ""))
        for card in matches
    }
    return matches[:limit] if len(unique_prints) == 1 else []


def decode_scanner_image(image_data: str, Image) -> Any:
    encoded = image_data.split(",", 1)[-1]
    if len(encoded) > 3_000_000:
        raise HTTPException(status_code=413, detail="Kamerabild ist zu gross.")
    try:
        return Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))).convert("L")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Kamerabild konnte nicht gelesen werden.") from exc


def detect_and_warp_card(image: Any) -> tuple[Any | None, float]:
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return None, 0.0
    rgb = np.array(image.convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, 1400 / max(width, height))
    if scale < 1:
        rgb = cv2.resize(rgb, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    frame_area = height * width
    candidates: dict[tuple[int, ...], tuple[float, Any]] = {}
    # A dark card on a light/white surface is the most common scanner setup.
    # Segmenting it directly is much less sensitive to autofocus and motion blur
    # than relying on one perfectly closed Canny contour.
    border = np.concatenate((gray[:20, :].ravel(), gray[-20:, :].ravel(), gray[:, :20].ravel(), gray[:, -20:].ravel()))
    background_level = float(np.median(border))
    if background_level >= 150:
        for offset in (18, 32, 48):
            cutoff = max(45, min(242, round(background_level - offset)))
            mask = cv2.threshold(gray, cutoff, 255, cv2.THRESH_BINARY_INV)[1]
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8), iterations=2)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < frame_area * 0.018 or area > frame_area * 0.95:
                    continue
                rectangle = cv2.minAreaRect(contour)
                rect_width, rect_height = rectangle[1]
                if rect_width <= 0 or rect_height <= 0:
                    continue
                ratio = min(rect_width, rect_height) / max(rect_width, rect_height)
                rectangularity = area / max(1.0, rect_width * rect_height)
                if not 0.58 <= ratio <= 0.82 or rectangularity < 0.58:
                    continue
                points = cv2.boxPoints(rectangle).astype("float32")
                sums = points.sum(axis=1)
                diffs = np.diff(points, axis=1).ravel()
                ordered = np.array([
                    points[np.argmin(sums)], points[np.argmin(diffs)],
                    points[np.argmax(sums)], points[np.argmax(diffs)],
                ], dtype="float32")
                ratio_score = max(0.0, 1.0 - abs(ratio - 0.716) / 0.14)
                area_score = (rect_width * rect_height) / frame_area
                preview_target = np.array([[0, 0], [119, 0], [119, 167], [0, 167]], dtype="float32")
                preview_matrix = cv2.getPerspectiveTransform(ordered, preview_target)
                preview = cv2.warpPerspective(gray, preview_matrix, (120, 168))
                border_pixels = np.concatenate((
                    preview[:7, :].ravel(), preview[-7:, :].ravel(),
                    preview[:, :7].ravel(), preview[:, -7:].ravel(),
                ))
                border_darkness = max(0.0, min(1.0, (220.0 - float(np.mean(border_pixels))) / 180.0))
                score = (
                    (area_score ** 0.5)
                    * (ratio_score ** 2)
                    * (0.9 + 0.1 * rectangularity)
                    * (0.5 + border_darkness)
                    * 1.1
                )
                key = tuple(int(value / 8) for value in ordered.ravel())
                if key not in candidates or score > candidates[key][0]:
                    candidates[key] = (score, ordered)
    for low, high in ((25, 75), (45, 135), (70, 210)):
        edges = cv2.Canny(gray, low, high)
        for kernel_size in (3, 7, 11):
            closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((kernel_size, kernel_size), np.uint8), iterations=1)
            contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < frame_area * 0.025 or area > frame_area * 0.95:
                    continue
                perimeter = cv2.arcLength(contour, True)
                for epsilon in (0.015, 0.025, 0.04, 0.06):
                    polygon = cv2.approxPolyDP(contour, epsilon * perimeter, True)
                    if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                        continue
                    points = polygon.reshape(4, 2).astype("float32")
                    sums = points.sum(axis=1)
                    diffs = np.diff(points, axis=1).ravel()
                    ordered = np.array([
                        points[np.argmin(sums)], points[np.argmin(diffs)],
                        points[np.argmax(sums)], points[np.argmax(diffs)],
                    ], dtype="float32")
                    top_left, top_right, bottom_right, bottom_left = ordered
                    card_width = (np.linalg.norm(top_right - top_left) + np.linalg.norm(bottom_right - bottom_left)) / 2
                    card_height = (np.linalg.norm(bottom_left - top_left) + np.linalg.norm(bottom_right - top_right)) / 2
                    if card_width <= 0 or card_height <= 0:
                        continue
                    ratio = min(card_width, card_height) / max(card_width, card_height)
                    if not 0.56 <= ratio <= 0.84:
                        continue
                    border_hits = sum(
                        x < 5 or y < 5 or x > width - 6 or y > height - 6
                        for x, y in ordered
                    )
                    if border_hits >= 3:
                        continue
                    ratio_score = max(0.0, 1.0 - abs(ratio - 0.716) / 0.16)
                    area_score = area / frame_area
                    score = (area_score ** 0.5) * (ratio_score ** 4)
                    key = tuple(int(value / 8) for value in ordered.ravel())
                    if key not in candidates or score > candidates[key][0]:
                        candidates[key] = (score, ordered)
    if not candidates:
        edges = cv2.Canny(gray, 35, 130)
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8), iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            contour_area = cv2.contourArea(contour)
            if contour_area < frame_area * 0.02 or contour_area > frame_area * 0.95:
                continue
            rectangle = cv2.minAreaRect(contour)
            rect_width, rect_height = rectangle[1]
            if rect_width <= 0 or rect_height <= 0:
                continue
            ratio = min(rect_width, rect_height) / max(rect_width, rect_height)
            if not 0.56 <= ratio <= 0.84:
                continue
            points = cv2.boxPoints(rectangle).astype("float32")
            sums = points.sum(axis=1)
            diffs = np.diff(points, axis=1).ravel()
            ordered = np.array([
                points[np.argmin(sums)], points[np.argmin(diffs)],
                points[np.argmax(sums)], points[np.argmax(diffs)],
            ], dtype="float32")
            ratio_score = max(0.0, 1.0 - abs(ratio - 0.716) / 0.16)
            area_score = (rect_width * rect_height) / frame_area
            score = (area_score ** 0.5) * (ratio_score ** 4) * 0.82
            key = tuple(int(value / 8) for value in ordered.ravel())
            candidates[key] = (score, ordered)
    if not candidates:
        return None, 0.0
    score, source_points = max(candidates.values(), key=lambda item: item[0])
    target_width, target_height = 744, 1039
    target_points = np.array(
        [[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(source_points, target_points)
    warped = cv2.warpPerspective(rgb, matrix, (target_width, target_height), flags=cv2.INTER_CUBIC)
    return Image.fromarray(warped), float(min(1.0, score / 0.38))


def scanner_debug_data_url(image: Any) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def rapid_ocr_lines(image: Any) -> tuple[list[str], list[float]]:
    global RAPID_OCR_ENGINE
    try:
        import numpy as np
        from rapidocr import RapidOCR
    except ImportError:
        return [], []
    try:
        with RAPID_OCR_LOCK:
            if RAPID_OCR_ENGINE is None:
                RAPID_OCR_ENGINE = RapidOCR()
            output = RAPID_OCR_ENGINE(np.array(image.convert("RGB")), text_score=0.25, box_thresh=0.2)
        texts = [str(text).strip() for text in (output.txts or []) if str(text).strip()]
        scores = [float(score) for score in (output.scores or [])]
        return texts, scores
    except Exception:
        return [], []


def rapid_ocr_text(image: Any) -> tuple[str, float]:
    texts, scores = rapid_ocr_lines(image)
    return " ".join(texts).strip(), (sum(scores) / len(scores) if scores else 0.0)


def cards_confirmed_by_name(cards: list[dict[str, Any]], raw_name: str) -> tuple[list[dict[str, Any]], float]:
    normalized_read = normalized_card_name(raw_name)
    if len(normalized_read) < 3:
        return [], 0.0
    scored: list[tuple[float, dict[str, Any]]] = []
    unverifiable: list[dict[str, Any]] = []
    for card in cards:
        if card.get("lang") != "en" and not card.get("printed_name"):
            unverifiable.append(card)
        names = [card.get("name") or "", card.get("printed_name") or ""]
        score = max((SequenceMatcher(None, normalized_read, normalized_card_name(name)).ratio() for name in names if name), default=0.0)
        scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    best = scored[0][0] if scored else 0.0
    if best < 0.58:
        if unverifiable:
            return unverifiable, 0.72
        return [], best
    return [card for score, card in scored if score >= max(0.58, best - 0.06)], best


def full_frame_card_match(db: sqlite3.Connection, image: Any) -> dict[str, Any] | None:
    lines, line_scores = rapid_ocr_lines(image)
    if not lines:
        return None
    known_sets = {str(row["set_code"]).upper() for row in db.execute("SELECT DISTINCT set_code FROM cards WHERE set_code IS NOT NULL")}
    best_result: dict[str, Any] | None = None
    for set_index, set_line in enumerate(lines):
        set_tokens = re.sub(r"[^A-Z0-9]+", " ", set_line.upper()).split()
        if not any(token in known_sets for token in set_tokens):
            continue
        preceding = range(max(0, set_index - 4), set_index + 1)
        number_indexes = [
            index for index in preceding
            if re.search(r"(?:^|\s)[CURM]?\s*0*[0-9]{2,5}(?:\s*/\s*[0-9]{2,5})?", lines[index].upper())
            and not re.fullmatch(r"\s*[0-9]{1,2}\s*/\s*[0-9]{1,2}\s*", lines[index])
        ]
        for number_index in number_indexes:
            collector_text = f"{lines[number_index]} {set_line}"
            _, candidates = scanner_print_matches(db, collector_text)
            if not candidates:
                continue
            for name_line in lines:
                confirmed, name_score = cards_confirmed_by_name(candidates, name_line)
                if not confirmed:
                    continue
                relevant_scores = [line_scores[number_index], line_scores[set_index]]
                collector_score = sum(relevant_scores) / len(relevant_scores)
                combined = min(collector_score, name_score)
                if best_result is None or combined > best_result["score"]:
                    best_result = {
                        "cards": confirmed,
                        "collector_text": collector_text,
                        "name_text": name_line,
                        "score": combined,
                        "all_text": " | ".join(lines),
                    }
    return best_result


@app.post("/api/cards/scan-frame")
def scan_card_frame(payload: ScannerFrameIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        import pytesseract
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Live-OCR ist auf dem Server noch nicht vollstaendig installiert.") from exc
    try:
        import cv2  # noqa: F401 -- required by detect_and_warp_card
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="OpenCV fuer die Kartenkontur fehlt oder kann auf dem Linux-Server nicht geladen werden. Bitte Scanner-Abhaengigkeiten installieren.",
        ) from exc
    detected_card = None
    detection_score = 0.0
    detected_name_image = None
    detected_collector_image = None
    detected_collector_wide_image = None
    full_source_image = None
    if payload.full_image_data:
        full_source_image = decode_scanner_image(payload.full_image_data, Image)
        detected_card, detection_score = detect_and_warp_card(full_source_image)
        if detected_card is None:
            fallback = full_frame_card_match(db, full_source_image)
            if fallback:
                return {
                    "recognized_text": fallback["all_text"],
                    "collector_text": fallback["collector_text"],
                    "query": fallback["collector_text"],
                    "match_type": "collector",
                    "ocr_engine": "rapidocr-full-frame",
                    "ocr_score": round(fallback["score"], 3),
                    "name_text": fallback["name_text"],
                    "name_match_score": round(fallback["score"], 3),
                    "card_detected": False,
                    "detection_mode": "full-frame-text",
                    "cards": fallback["cards"],
                }
            if payload.live:
                return {
                    "recognized_text": "", "collector_text": "", "query": "",
                    "match_type": "none", "ocr_engine": "rapidocr", "ocr_score": 0.0,
                    "card_detected": False, "cards": [],
                }
        else:
            card_width, card_height = detected_card.size
            detected_name_image = detected_card.crop((
                round(card_width * 0.02), 0,
                round(card_width * 0.96), round(card_height * 0.15),
            ))
            detected_collector_image = detected_card.crop((
                round(card_width * 0.01), round(card_height * 0.85),
                round(card_width * 0.60), round(card_height * 0.995),
            ))
            detected_collector_wide_image = detected_card.crop((
                round(card_width * 0.01), round(card_height * 0.85),
                round(card_width * 0.99), round(card_height * 0.995),
            ))
    if detected_name_image is not None and detected_collector_wide_image is not None:
        name_rgb = detected_name_image.convert("RGB")
        collector_rgb = detected_collector_wide_image.convert("RGB")
        combined_image = Image.new(
            "RGB",
            (max(name_rgb.width, collector_rgb.width), name_rgb.height + 20 + collector_rgb.height),
            "white",
        )
        combined_image.paste(name_rgb, (0, 0))
        combined_image.paste(collector_rgb, (0, name_rgb.height + 20))
        combined_lines, combined_scores = rapid_ocr_lines(combined_image)
        if combined_lines:
            combined_text = " | ".join(combined_lines)
            combined_query, print_cards = scanner_print_matches(db, combined_text)
            matched_cards: list[dict[str, Any]] = []
            matched_name = ""
            matched_name_score = 0.0
            if print_cards:
                for line in combined_lines:
                    confirmed_cards, name_score = cards_confirmed_by_name(print_cards, line)
                    if confirmed_cards and name_score > matched_name_score:
                        matched_cards = confirmed_cards
                        matched_name = line
                        matched_name_score = name_score
            if not matched_cards:
                for line in combined_lines:
                    number_cards = cards_matched_by_name_and_number(db, line, combined_text)
                    if number_cards:
                        matched_cards = number_cards
                        matched_name = line
                        matched_name_score = float(number_cards[0].get("scanner_score") or 0.8)
                        break
            if not matched_cards:
                for line in combined_lines:
                    set_cards = cards_matched_by_name_and_set(db, line, combined_text)
                    if set_cards:
                        matched_cards = set_cards
                        matched_name = line
                        matched_name_score = float(set_cards[0].get("scanner_score") or 0.8)
                        break
            if matched_cards:
                ocr_score = sum(combined_scores) / len(combined_scores) if combined_scores else 0.0
                return {
                    "recognized_text": combined_text,
                    "collector_text": combined_text,
                    "query": combined_query or combined_text,
                    "match_type": "collector",
                    "ocr_engine": "rapidocr-combined",
                    "ocr_layout": "detected-card-combined",
                    "ocr_score": round(min(ocr_score, matched_name_score), 3),
                    "name_text": matched_name,
                    "name_match_score": round(matched_name_score, 3),
                    "card_detected": True,
                    "card_detection_score": round(detection_score, 3),
                    "debug_name_image": scanner_debug_data_url(detected_name_image),
                    "debug_collector_image": scanner_debug_data_url(detected_collector_wide_image),
                    "cards": matched_cards,
                }
    detected_name_text = ""
    detected_name_score = 0.0
    if detected_name_image is not None:
        detected_name_text, detected_name_score = rapid_ocr_text(detected_name_image)
    rapid_reads: list[str] = []
    if detected_collector_image is not None:
        rapid_sources = (
            (detected_collector_image, "detected-card-left"),
            (detected_collector_wide_image, "detected-card-wide"),
        )
    else:
        source_data = ((payload.collector_wide_data, "wide"),) if payload.live else (
            (payload.collector_wide_data, "wide"),
            (payload.collector_data, "narrow"),
        )
        rapid_sources = tuple(
            (decode_scanner_image(image_data, Image), layout)
            for image_data, layout in source_data if image_data
        )
    for collector_image, layout in rapid_sources:
        if collector_image is None:
            continue
        rapid_text, rapid_score = rapid_ocr_text(collector_image)
        if not rapid_text:
            continue
        rapid_reads.append(rapid_text)
        rapid_query, rapid_cards = scanner_print_matches(db, rapid_text)
        if rapid_cards:
            name_text = ""
            name_match_score = 0.0
            name_image = detected_name_image if detected_name_image is not None else (
                decode_scanner_image(payload.image_data, Image) if payload.image_data else None
            )
            if name_image is not None:
                if detected_name_image is not None:
                    name_text = detected_name_text
                else:
                    name_text, _ = rapid_ocr_text(name_image)
                confirmed_cards, name_match_score = cards_confirmed_by_name(rapid_cards, name_text)
                if payload.live and not confirmed_cards:
                    continue
                if confirmed_cards:
                    rapid_cards = confirmed_cards
            combined_score = min(rapid_score, name_match_score) if name_match_score else rapid_score * (0.72 if payload.live else 1.0)
            return {
                "recognized_text": rapid_text,
                "collector_text": " | ".join(rapid_reads),
                "query": rapid_query,
                "match_type": "collector",
                "ocr_engine": "rapidocr",
                "ocr_layout": layout,
                "ocr_score": round(combined_score, 3),
                "name_text": name_text,
                "name_match_score": round(name_match_score, 3),
                "card_detected": detected_card is not None,
                "card_detection_score": round(detection_score, 3),
                "debug_name_image": scanner_debug_data_url(detected_name_image) if detected_name_image is not None else None,
                "debug_collector_image": scanner_debug_data_url(detected_collector_image) if detected_collector_image is not None else None,
                "cards": rapid_cards,
            }
    if detected_name_image is not None and rapid_reads:
        name_text, name_score = detected_name_text, detected_name_score
        name_number_cards = cards_matched_by_name_and_number(db, name_text, " | ".join(rapid_reads))
        if name_number_cards:
            rapid_text = " | ".join(rapid_reads)
            return {
                "recognized_text": rapid_text,
                "collector_text": rapid_text,
                "query": rapid_text,
                "match_type": "collector",
                "ocr_engine": "rapidocr-name-number",
                "ocr_score": round(name_score, 3),
                "name_text": name_text,
                "name_match_score": round(name_score, 3),
                "card_detected": True,
                "card_detection_score": round(detection_score, 3),
                "debug_name_image": scanner_debug_data_url(detected_name_image),
                "debug_collector_image": scanner_debug_data_url(detected_collector_image),
                "cards": name_number_cards,
            }
    if payload.live:
        if full_source_image is not None and detected_card is None:
            fallback = full_frame_card_match(db, full_source_image)
            if fallback:
                return {
                    "recognized_text": fallback["all_text"],
                    "collector_text": fallback["collector_text"],
                    "query": fallback["collector_text"],
                    "match_type": "collector",
                    "ocr_engine": "rapidocr-full-frame",
                    "ocr_score": round(fallback["score"], 3),
                    "name_text": fallback["name_text"],
                    "name_match_score": round(fallback["score"], 3),
                    "card_detected": detected_card is not None,
                    "detection_mode": "full-frame-text",
                    "cards": fallback["cards"],
                }
        rapid_text = " | ".join(rapid_reads)
        return {
            "recognized_text": rapid_text,
            "collector_text": rapid_text,
            "query": "",
            "match_type": "none",
            "ocr_engine": "rapidocr",
            "ocr_score": 0.0,
            "card_detected": detected_card is not None,
            "card_detection_score": round(detection_score, 3),
            "debug_name_image": scanner_debug_data_url(detected_name_image) if detected_name_image is not None else None,
            "debug_collector_image": scanner_debug_data_url(detected_collector_image) if detected_collector_image is not None else None,
            "name_text": detected_name_text,
            "cards": [],
        }
    def read_collector(image_data: str, wide: bool) -> tuple[list[str], list[dict[str, Any]], bool]:
        source = decode_scanner_image(image_data, Image).convert("L")
        source = ImageOps.autocontrast(source)
        source = source.resize((min(2000, source.width * 4), min(520, source.height * 4)))
        source = ImageOps.invert(source).filter(ImageFilter.SHARPEN)
        variants = [source, source.point(lambda value: 255 if value > 125 else 0), source.point(lambda value: 255 if value > 165 else 0)]
        page_modes = (7, 13, 6) if wide else (6, 11, 7)
        read_attempts: list[str] = []
        votes: dict[int, int] = {}
        cards_by_id: dict[int, dict[str, Any]] = {}
        saw_fraction = False
        for attempt_image, page_mode in zip(variants, page_modes):
            attempt_image = ImageOps.expand(attempt_image, border=18, fill=255)
            try:
                attempt_text = pytesseract.image_to_string(
                    attempt_image,
                    lang="eng",
                    config=(
                        f"--psm {page_mode} "
                        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/- "
                        "-c load_system_dawg=0 -c load_freq_dawg=0"
                    ),
                ).strip()
            except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError):
                attempt_text = ""
            if not attempt_text:
                continue
            read_attempts.append(attempt_text)
            cards = scanner_print_matches(db, attempt_text)[1]
            for card in cards:
                card_id = int(card["id"])
                votes[card_id] = votes.get(card_id, 0) + 1
                cards_by_id[card_id] = card
            if cards and re.search(r"[0-9O]\s*/\s*[0-9O]", attempt_text):
                saw_fraction = True
        ranked_ids = sorted(votes, key=lambda card_id: (-votes[card_id], card_id))
        return read_attempts, [cards_by_id[card_id] for card_id in ranked_ids[:8]], saw_fraction

    collector_texts: list[str] = list(rapid_reads)
    wide_cards: list[dict[str, Any]] = []
    if payload.collector_wide_data:
        wide_texts, wide_cards, saw_fraction = read_collector(payload.collector_wide_data, True)
        collector_texts.extend(wide_texts)
        if wide_cards and saw_fraction:
            collector_text = " | ".join(collector_texts)
            return {"recognized_text": collector_text, "collector_text": collector_text, "query": collector_text, "match_type": "collector", "cards": wide_cards}
    if payload.collector_data:
        narrow_texts, narrow_cards, _ = read_collector(payload.collector_data, False)
        collector_texts.extend(narrow_texts)
        if narrow_cards:
            collector_text = " | ".join(collector_texts)
            return {"recognized_text": collector_text, "collector_text": collector_text, "query": collector_text, "match_type": "collector", "cards": narrow_cards}
    if wide_cards:
        collector_text = " | ".join(collector_texts)
        return {"recognized_text": collector_text, "collector_text": collector_text, "query": collector_text, "match_type": "collector", "cards": wide_cards}
    collector_text = " | ".join(collector_texts)
    image = decode_scanner_image(payload.image_data, Image)
    if image.width < 120 or image.height < 30:
        raise HTTPException(status_code=400, detail="Namensbereich ist zu klein.")
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.8)
    image = image.resize((min(1800, image.width * 2), min(400, image.height * 2)))
    image = image.filter(ImageFilter.SHARPEN)
    try:
        text = pytesseract.image_to_string(image, lang="deu+eng", config="--psm 7").strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Tesseract OCR ist auf dem Server nicht installiert.") from exc
    except pytesseract.TesseractError as exc:
        raise HTTPException(status_code=503, detail="Deutsche/englische OCR-Sprachdaten fehlen auf dem Server.") from exc
    query, cards = scanner_card_matches(db, text)
    return {"recognized_text": text, "collector_text": collector_text, "query": query, "match_type": "name", "cards": cards}


@app.post("/api/cards/scan-reports")
def save_scanner_report(payload: ScannerReportIn) -> dict[str, Any]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Bildverarbeitung ist auf dem Server nicht installiert.") from exc
    result = payload.result or {}
    if len(json.dumps(result, ensure_ascii=False)) > 200_000:
        raise HTTPException(status_code=413, detail="Scanner-Report ist zu gross.")
    report_dir = DATA_DIR / "scanner-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_id = f"scan-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{uuid.uuid4().hex[:8]}"
    image = decode_scanner_image(payload.image_data, Image).convert("RGB")
    image_path = report_dir / f"{report_id}.jpg"
    metadata_path = report_dir / f"{report_id}.json"
    image.save(image_path, format="JPEG", quality=92)
    version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else app.version
    metadata = {
        "report_id": report_id,
        "reported_at": datetime.now().isoformat(timespec="milliseconds"),
        "manavault_version": version,
        "expected": (payload.expected or "").strip(),
        "image_file": image_path.name,
        "result": result,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report_id": report_id, "saved": True}


@app.get("/api/cards/scan-reports/export")
def export_scanner_reports() -> Response:
    report_dir = DATA_DIR / "scanner-reports"
    files = sorted(path for path in report_dir.glob("scan-*.*") if path.suffix.lower() in {".jpg", ".json"}) if report_dir.exists() else []
    if not files:
        raise HTTPException(status_code=404, detail="Noch keine Scanner-Reports gespeichert.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    filename = f"ManaVault-scanner-reports-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def run_scryfall_import(payload: ImportRequest) -> None:
    try:
        result = import_scryfall_data(payload.local_file, payload.limit, payload.bulk_type, payload.tokens_only)
        cards_imported = result.get("cards_imported", result["imported"])
        tokens_imported = result.get("tokens_imported", 0)
        set_scryfall_import_status(
            running=False,
            phase="done",
            message=f"{cards_imported} Karten und {tokens_imported} Tokens/Embleme importiert.",
            imported=result["imported"],
            error=None,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
    except FileNotFoundError as exc:
        set_scryfall_import_status(
            running=False,
            phase="error",
            message="Scryfall Import fehlgeschlagen.",
            error=str(exc),
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
    except (RuntimeError, ValueError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
        set_scryfall_import_status(
            running=False,
            phase="error",
            message="Scryfall Import fehlgeschlagen.",
            error=str(exc),
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        set_scryfall_import_status(
            running=False,
            phase="error",
            message="Scryfall Import fehlgeschlagen.",
            error=str(exc),
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
    finally:
        SCRYFALL_IMPORT_LOCK.release()


@app.post("/api/cards/import-scryfall")
def import_scryfall(payload: ImportRequest | None = None) -> dict[str, Any]:
    payload = payload or ImportRequest()
    if not SCRYFALL_IMPORT_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Scryfall Import laeuft bereits.")
    set_scryfall_import_status(
        running=True,
        phase="start",
        message="Scryfall Import startet im Hintergrund.",
        imported=None,
        error=None,
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=None,
    )
    Thread(target=run_scryfall_import, args=(payload,), daemon=True).start()
    return {"started": True, "message": "Scryfall Import laeuft im Hintergrund."}


@app.get("/api/cards/import-scryfall/status")
def import_scryfall_status() -> dict[str, Any]:
    return scryfall_import_status()


@app.get("/api/collection")
def collection(db: sqlite3.Connection = Depends(db_dep)) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT cc.*, c.name AS card_name, c.printed_name, c.lang, c.image_url, c.mana_cost, c.type_line,
               c.printed_type_line,
               l.name AS location_name, l.type AS location_type,
               d.name AS assigned_deck_name
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id
        LEFT JOIN locations l ON l.id = cc.location_id
        LEFT JOIN decks d ON d.id = cc.assigned_deck_id
        ORDER BY c.name, cc.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def card_filter_sql(
    q: str = "",
    colors: str = "",
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    card_type: str = "",
    tag: str = "",
    legal_format: str = "",
    rarity: str = "",
    set_code: str = "",
    langs: str = "en,de",
    sort: str = "name",
) -> tuple[list[str], list[Any], str]:
    conditions = []
    params: list[Any] = []
    if langs.strip().lower() not in {"all", "*"}:
        allowed_langs = {"en", "de", "fr", "it", "es", "pt", "ja", "ko", "ru", "zhs", "zht"}
        selected_langs = [lang.strip().lower() for lang in langs.split(",") if lang.strip().lower() in allowed_langs]
        if not selected_langs:
            selected_langs = ["en", "de"]
        placeholders = ",".join("?" for _ in selected_langs)
        conditions.append(f"c.lang IN ({placeholders})")
        params.extend(selected_langs)
    query = q.strip().lower()
    identifier = parse_print_identifier(q)
    if identifier:
        conditions.append("upper(c.set_code) = ?")
        params.append(identifier["set_code"])
        conditions.append("upper(ltrim(c.collector_number, '0')) = ?")
        params.append(identifier["collector_number"])
        if identifier.get("lang"):
            conditions.append("c.lang = ?")
            params.append(identifier["lang"])
        if identifier.get("rarity"):
            conditions.append("c.rarity = ?")
            params.append(identifier["rarity"])
        if identifier.get("kind") == "token":
            conditions.append("c.is_token = 1")
        elif identifier.get("kind") == "card":
            conditions.append("c.is_token = 0")
    elif query:
        term = f"%{query}%"
        conditions.append(
            """
            (
                (c.lang = 'en' AND lower(c.name) LIKE ?)
                OR lower(COALESCE(c.printed_name, '')) LIKE ?
                OR (lower(c.type_line) LIKE ? OR lower(COALESCE(c.printed_type_line, '')) LIKE ?)
                OR (lower(c.oracle_text) LIKE ? OR lower(COALESCE(c.printed_text, '')) LIKE ?)
            )
            """
        )
        params.extend([term, term, term, term, term, term])

    selected_colors = [color for color in colors.split(",") if color in {"W", "U", "B", "R", "G", "C"}]
    if "C" in selected_colors:
        conditions.append("c.colors = '[]'")
    else:
        for color in selected_colors:
            conditions.append("c.colors LIKE ?")
            params.append(f'%"{color}"%')

    if cmc_min is not None:
        conditions.append("c.cmc >= ?")
        params.append(cmc_min)
    if cmc_max is not None:
        conditions.append("c.cmc <= ?")
        params.append(cmc_max)
    if card_type.strip():
        conditions.append("lower(c.type_line) LIKE ?")
        params.append(f"%{card_type.strip().lower()}%")
    if tag.strip():
        tag_value = tag.strip()
        conditions.append(
            """
            c.id IN (
                SELECT card_id FROM card_tags
                WHERE auto_tags LIKE ? OR manual_tags LIKE ?
            )
            """
        )
        params.extend([f'%"{tag_value}"%', f'%"{tag_value}"%'])
    legal_key = legal_format.strip().lower()
    allowed_formats = {"standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper", "brawl", "historic"}
    if legal_key in allowed_formats:
        conditions.append(f"json_extract(c.legalities, '$.{legal_key}') = ?")
        params.append("legal")
    rarity_key = rarity.strip().lower()
    allowed_rarities = {"common", "uncommon", "rare", "mythic", "special", "bonus"}
    if rarity_key in allowed_rarities:
        conditions.append("c.rarity = ?")
        params.append(rarity_key)
    set_key = set_code.strip().lower()
    if set_key:
        conditions.append("lower(c.set_code) = ?")
        params.append(set_key)
    name_order = "lower(COALESCE(c.printed_name, c.name)), lower(c.name), c.set_code, c.collector_number"
    name_order_desc = "lower(COALESCE(c.printed_name, c.name)) DESC, lower(c.name) DESC, c.set_code, c.collector_number"
    price_order = "COALESCE(CAST(NULLIF(json_extract(c.prices_json, '$.eur'), '') AS REAL), CAST(NULLIF(json_extract(c.prices_json, '$.eur_foil'), '') AS REAL), 0)"
    rarity_order = "CASE c.rarity WHEN 'mythic' THEN 0 WHEN 'rare' THEN 1 WHEN 'uncommon' THEN 2 WHEN 'common' THEN 3 ELSE 4 END"
    rarity_order_asc = "CASE c.rarity WHEN 'common' THEN 0 WHEN 'uncommon' THEN 1 WHEN 'rare' THEN 2 WHEN 'mythic' THEN 3 ELSE 4 END"
    sort_orders = {
        "name": name_order,
        "name_desc": name_order_desc,
        "cmc": f"c.cmc ASC, {name_order}",
        "cmc_desc": f"c.cmc DESC, {name_order}",
        "price": f"{price_order} DESC, {name_order}",
        "price_asc": f"{price_order} ASC, {name_order}",
        "rarity": f"{rarity_order}, {name_order}",
        "rarity_asc": f"{rarity_order_asc}, {name_order}",
        "set": f"c.set_code, CAST(c.collector_number AS INTEGER), c.collector_number, {name_order}",
        "released": f"c.released_at DESC, {name_order}",
    }
    order = sort_orders.get(sort, name_order)
    if query and not identifier and sort == "name":
        order = f"CASE WHEN lower(c.name) LIKE ? OR lower(COALESCE(c.printed_name, '')) LIKE ? THEN 0 ELSE 1 END, {order}"
        params.append(f"{query}%")
        params.append(f"{query}%")
    return conditions, params, order


def parse_print_identifier(value: str) -> dict[str, str] | None:
    prepared = re.sub(r"\b([TCURML])(?=0*[0-9])", r"\1 ", (value or "").upper())
    tokens = re.findall(r"[A-Z0-9]+", prepared)
    number_index = next((index for index, token in enumerate(tokens) if re.fullmatch(r"0*[0-9]+[A-Z]?", token)), None)
    if number_index is None:
        return None
    collector_number = normalized_collector_number(tokens[number_index])
    languages = {"DE", "EN", "FR", "IT", "ES", "PT", "JA", "KO", "RU", "ZHS", "ZHT"}
    rarity_codes = {"C": "common", "U": "uncommon", "R": "rare", "M": "mythic"}
    print_markers = {*rarity_codes, "T", "L"}
    set_candidates = [
        token for index, token in enumerate(tokens)
        if index != number_index
        and token not in languages
        and token not in print_markers
        and re.fullmatch(r"[A-Z0-9]{2,6}", token)
        and re.search(r"[A-Z]", token)
    ]
    if not set_candidates:
        return None
    language = next((token.lower() for token in tokens if token in languages), "")
    rarity = rarity_codes.get(tokens[0], "") if tokens and tokens[0] in rarity_codes else ""
    marker = tokens[number_index - 1] if number_index > 0 and tokens[number_index - 1] in print_markers else ""
    if not marker and tokens and tokens[0] in print_markers:
        marker = tokens[0]
    return {
        "collector_number": collector_number,
        "set_code": set_candidates[0],
        "lang": language,
        "rarity": rarity,
        "kind": "token" if marker == "T" else ("card" if marker else ""),
    }


def collector_sort_value(value: Any) -> tuple[int, str]:
    text = str(value or "")
    match = re.match(r"(\d+)", text)
    return (int(match.group(1)) if match else 999999, text)


def rarity_rank(value: Any, low_first: bool = False) -> int:
    high_first = {"mythic": 0, "rare": 1, "uncommon": 2, "common": 3}
    low_order = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}
    table = low_order if low_first else high_first
    return table.get(str(value or "").lower(), 9)


def display_sort_name(item: dict[str, Any]) -> str:
    return str(item.get("printed_name") or item.get("name") or "").lower()


def sort_collection_items(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    sort_key = sort.strip().lower()
    if sort_key == "name_desc":
        return sorted(items, key=display_sort_name, reverse=True)
    if sort_key == "cmc":
        return sorted(items, key=lambda item: (item.get("cmc") if item.get("cmc") is not None else 999, display_sort_name(item)))
    if sort_key == "cmc_desc":
        return sorted(items, key=lambda item: (-(item.get("cmc") or 0), display_sort_name(item)))
    if sort_key == "price":
        return sorted(items, key=lambda item: (-(item.get("price_eur") or 0), display_sort_name(item)))
    if sort_key == "price_asc":
        return sorted(items, key=lambda item: (item.get("price_eur") or 0, display_sort_name(item)))
    if sort_key == "value":
        return sorted(items, key=lambda item: (-(item.get("collection_value_eur") or 0), -(item.get("price_eur") or 0), display_sort_name(item)))
    if sort_key == "value_asc":
        return sorted(items, key=lambda item: (item.get("collection_value_eur") or 0, display_sort_name(item)))
    if sort_key == "count":
        return sorted(items, key=lambda item: (-(item.get("total_count") or 0), display_sort_name(item)))
    if sort_key == "free":
        return sorted(items, key=lambda item: (-(item.get("free_count") or 0), display_sort_name(item)))
    if sort_key == "rarity":
        return sorted(items, key=lambda item: (rarity_rank(item.get("rarity")), display_sort_name(item)))
    if sort_key == "rarity_asc":
        return sorted(items, key=lambda item: (rarity_rank(item.get("rarity"), low_first=True), display_sort_name(item)))
    if sort_key == "set":
        return sorted(items, key=lambda item: (str(item.get("set_code") or ""), collector_sort_value(item.get("collector_number")), display_sort_name(item)))
    if sort_key == "released":
        return sorted(items, key=lambda item: (str(item.get("released_at") or ""), display_sort_name(item)), reverse=True)
    return sorted(items, key=display_sort_name)


@app.get("/api/collection/stats")
def collection_stats(db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    rows = db.execute(
        """
        SELECT c.*,
               COUNT(cc.id) AS total_count,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS owned_count,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxy_count
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id
        GROUP BY c.id
        """
    ).fetchall()
    color_counts = {color: 0 for color in ["W", "U", "B", "R", "G", "C"]}
    color_groups = {"colorless": 0, "mono": 0, "multi": 0}
    rarity_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}
    total_copies = 0
    original_copies = 0
    proxy_copies = 0
    total_value = 0.0
    priced_originals = 0
    fallback_originals = 0
    top_value_cards = []
    for row in rows:
        card = card_row(row)
        count = int(row["total_count"] or 0)
        originals = int(row["owned_count"] or 0)
        proxies = int(row["proxy_count"] or 0)
        total_copies += count
        original_copies += originals
        proxy_copies += proxies
        colors = card.get("colors") or []
        if not colors:
            color_counts["C"] += count
            color_groups["colorless"] += count
        else:
            for color in colors:
                if color in color_counts:
                    color_counts[color] += count
            color_groups["mono" if len(colors) == 1 else "multi"] += count
        rarity = str(card.get("rarity") or "unknown").lower()
        rarity_counts[rarity] = rarity_counts.get(rarity, 0) + count
        lang = str(card.get("lang") or "unknown").lower()
        language_counts[lang] = language_counts.get(lang, 0) + count
        price_eur, price_source = card_price_eur_with_fallback(db, card)
        value = round(price_eur * originals, 2)
        total_value += value
        if originals and price_eur > 0:
            priced_originals += originals
            if price_source != "own":
                fallback_originals += originals
        if value > 0:
            top_value_cards.append({
                "name": card.get("printed_name") or card.get("name"),
                "set_code": card.get("set_code"),
                "count": originals,
                "price_eur": price_eur,
                "value_eur": value,
            })
    top_value_cards.sort(key=lambda item: item["value_eur"], reverse=True)
    set_totals = {
        row["code"]: dict(row)
        for row in db.execute(
            """
            SELECT lower(set_code) AS code,
                   COALESCE(MAX(set_name), upper(set_code)) AS name,
                   COUNT(DISTINCT collector_number) AS total_prints
            FROM cards
            WHERE set_code IS NOT NULL AND set_code != '' AND lang = 'en'
              AND collector_number NOT LIKE 'A-%'
            GROUP BY lower(set_code)
            """
        ).fetchall()
    }
    if not set_totals:
        set_totals = {
            row["code"]: dict(row)
            for row in db.execute(
                """
                SELECT lower(set_code) AS code,
                       COALESCE(MAX(set_name), upper(set_code)) AS name,
                       COUNT(DISTINCT collector_number) AS total_prints
                FROM cards
                WHERE set_code IS NOT NULL AND set_code != ''
                  AND collector_number NOT LIKE 'A-%'
                GROUP BY lower(set_code)
                """
            ).fetchall()
        }
    owned_sets = {
        row["code"]: dict(row)
        for row in db.execute(
            """
            SELECT lower(c.set_code) AS code,
                   COUNT(DISTINCT c.collector_number) AS owned_prints,
                   COUNT(cc.id) AS owned_copies
            FROM card_copies cc
            JOIN cards c ON c.id = cc.card_id
            WHERE cc.is_proxy = 0 AND c.set_code IS NOT NULL AND c.set_code != ''
            GROUP BY lower(c.set_code)
            """
        ).fetchall()
    }
    proxy_sets = {
        row["code"]: dict(row)
        for row in db.execute(
            """
            SELECT lower(c.set_code) AS code,
                   COUNT(DISTINCT c.collector_number) AS proxy_prints,
                   COUNT(cc.id) AS proxy_copies
            FROM card_copies cc
            JOIN cards c ON c.id = cc.card_id
            WHERE cc.is_proxy = 1 AND c.set_code IS NOT NULL AND c.set_code != ''
            GROUP BY lower(c.set_code)
            """
        ).fetchall()
    }
    set_stats = []
    visible_set_codes = sorted(set(owned_sets.keys()) | set(proxy_sets.keys()))
    for code in visible_set_codes:
        owned = owned_sets.get(code, {})
        proxy = proxy_sets.get(code, {})
        owned_copies = int(owned.get("owned_copies") or 0)
        proxy_copies = int(proxy.get("proxy_copies") or 0)
        if owned_copies + proxy_copies <= 0:
            continue
        total = set_totals.get(code, {"code": code, "name": code.upper(), "total_prints": owned.get("owned_prints") or proxy.get("proxy_prints") or 0})
        total_prints = int(total.get("total_prints") or 0)
        owned_prints = int(owned.get("owned_prints") or 0)
        missing_prints = max(0, total_prints - owned_prints)
        set_stats.append({
            "code": code,
            "name": total.get("name") or code.upper(),
            "total_prints": total_prints,
            "owned_prints": owned_prints,
            "owned_copies": owned_copies,
            "proxy_prints": int(proxy.get("proxy_prints") or 0),
            "proxy_copies": proxy_copies,
            "missing_prints": missing_prints,
            "completion_percent": round((owned_prints / total_prints) * 100, 1) if total_prints else 0,
        })
    set_stats.sort(key=lambda item: (item["completion_percent"], item["owned_prints"]), reverse=True)
    for item in set_stats[:24]:
        missing_rows = db.execute(
            """
            SELECT name, collector_number, rarity
            FROM cards
            WHERE lang = 'en'
              AND lower(set_code) = ?
              AND collector_number NOT LIKE 'A-%'
              AND collector_number NOT IN (
                SELECT owned.collector_number
                FROM card_copies cc
                JOIN cards owned ON owned.id = cc.card_id
                WHERE cc.is_proxy = 0 AND lower(owned.set_code) = ?
              )
            GROUP BY collector_number
            ORDER BY CAST(collector_number AS INTEGER), collector_number
            LIMIT 8
            """,
            (item["code"], item["code"]),
        ).fetchall()
        item["missing_examples"] = [dict(row) for row in missing_rows]
    deck_value_stats = []
    deck_rows = db.execute("SELECT id, name, format FROM decks ORDER BY name").fetchall()
    for deck in deck_rows:
        slot_rows = db.execute(
            """
            SELECT ds.quantity, c.*
            FROM deck_slots ds
            JOIN cards c ON c.id = ds.card_id
            WHERE ds.deck_id = ?
            ORDER BY c.name
            """,
            (deck["id"],),
        ).fetchall()
        deck_list_value = 0.0
        assigned_original_value = 0.0
        assigned_proxy_value = 0.0
        missing_value = 0.0
        slot_quantity = 0
        assigned_originals = 0
        assigned_proxies = 0
        missing_cards = 0
        for slot in slot_rows:
            card = card_row(slot)
            price_eur, price_source = card_price_eur_with_fallback(db, card)
            quantity = int(slot["quantity"] or 0)
            assigned = db.execute(
                """
                SELECT
                  COALESCE(SUM(CASE WHEN is_proxy = 0 THEN 1 ELSE 0 END), 0) AS originals,
                  COALESCE(SUM(CASE WHEN is_proxy = 1 THEN 1 ELSE 0 END), 0) AS proxies
                FROM card_copies
                WHERE card_id = ? AND assigned_deck_id = ?
                """,
                (slot["id"], deck["id"]),
            ).fetchone()
            originals = int(assigned["originals"] or 0)
            proxies = int(assigned["proxies"] or 0)
            covered = min(quantity, originals + proxies)
            missing = max(0, quantity - covered)
            slot_quantity += quantity
            assigned_originals += originals
            assigned_proxies += proxies
            missing_cards += missing
            deck_list_value += price_eur * quantity
            assigned_original_value += price_eur * min(originals, quantity)
            assigned_proxy_value += price_eur * min(proxies, max(0, quantity - originals))
            missing_value += price_eur * missing
        deck_value_stats.append({
            "deck_id": deck["id"],
            "name": deck["name"],
            "format": deck["format"],
            "slot_quantity": slot_quantity,
            "assigned_originals": assigned_originals,
            "assigned_proxies": assigned_proxies,
            "missing_cards": missing_cards,
            "deck_list_value_eur": round(deck_list_value, 2),
            "assigned_original_value_eur": round(assigned_original_value, 2),
            "assigned_proxy_value_eur": round(assigned_proxy_value, 2),
            "missing_value_eur": round(missing_value, 2),
        })
    deck_value_stats.sort(key=lambda item: item["deck_list_value_eur"], reverse=True)
    rarity_order = ["common", "uncommon", "rare", "mythic", "special", "bonus", "unknown"]
    return {
        "total_copies": total_copies,
        "unique_prints": len(rows),
        "original_copies": original_copies,
        "proxy_copies": proxy_copies,
        "total_value_eur": round(total_value, 2),
        "priced_originals": priced_originals,
        "fallback_priced_originals": fallback_originals,
        "color_counts": color_counts,
        "color_groups": color_groups,
        "rarity_counts": {key: rarity_counts.get(key, 0) for key in rarity_order if key in rarity_counts},
        "language_counts": dict(sorted(language_counts.items())),
        "top_value_cards": top_value_cards[:8],
        "set_stats": set_stats[:24],
        "deck_value_stats": deck_value_stats,
    }


@app.get("/api/collection/summary")
def collection_summary(
    q: str = "",
    colors: str = "",
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    card_type: str = "",
    tag: str = "",
    legal_format: str = "",
    rarity: str = "",
    set_code: str = "",
    langs: str = "en,de",
    min_price_eur: float | None = None,
    sort: str = "name",
    limit: int = 120,
    offset: int = 0,
    db: sqlite3.Connection = Depends(db_dep),
) -> list[dict[str, Any]]:
    conditions, params, order = card_filter_sql(q, colors, cmc_min, cmc_max, card_type, tag, legal_format, rarity, set_code, langs, sort)
    where = f"AND {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(
        f"""
        SELECT c.id, c.name, c.printed_name, c.lang, c.mana_cost, c.type_line, c.printed_type_line, c.is_token,
               c.cmc, c.image_url, c.set_code, c.collector_number, c.rarity, c.released_at, c.prices_json,
               COUNT(cc.id) AS total_count,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS owned_count,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxy_count,
               SUM(CASE WHEN cc.assigned_deck_id IS NULL THEN 1 ELSE 0 END) AS free_count,
               SUM(CASE WHEN cc.assigned_deck_id IS NULL AND cc.is_proxy = 0 THEN 1 ELSE 0 END) AS free_original_count,
               SUM(CASE WHEN cc.assigned_deck_id IS NULL AND cc.is_proxy = 1 THEN 1 ELSE 0 END) AS free_proxy_count,
               SUM(CASE WHEN cc.assigned_deck_id IS NOT NULL THEN 1 ELSE 0 END) AS deck_count
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id
        WHERE 1 = 1
        {where}
        GROUP BY c.id
        ORDER BY {order}
        """,
        params,
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        prices = json_load(item.get("prices_json"), {})
        price_eur, price_source = card_price_eur_with_fallback(db, item)
        owned_count = item.get("owned_count") or 0
        item["price_eur"] = price_eur
        item["price_source"] = price_source
        item["collection_value_eur"] = round(price_eur * owned_count, 2)
        item["prices_json"] = prices
        if min_price_eur is not None and price_eur < min_price_eur:
            continue
        items.append(item)
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    sorted_items = sort_collection_items(items, sort)
    return sorted_items[safe_offset:safe_offset + safe_limit]


@app.get("/api/collection/export")
@app.get("/api/collection/export-ai", include_in_schema=False)
def export_collection_for_ai(format: str = "jsonl", db: sqlite3.Connection = Depends(db_dep)) -> PlainTextResponse:
    rows = db.execute(
        """
        SELECT c.*,
               COUNT(cc.id) AS total_count,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS original_count,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxy_count,
               SUM(CASE WHEN cc.assigned_deck_id IS NULL THEN 1 ELSE 0 END) AS free_count,
               SUM(CASE WHEN cc.assigned_deck_id IS NOT NULL THEN 1 ELSE 0 END) AS deck_count
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id
        GROUP BY c.id
        ORDER BY COALESCE(c.printed_name, c.name), c.set_code, c.collector_number
        """
    ).fetchall()
    items = []
    for row in rows:
        card = card_row(row)
        price_eur, price_source = card_price_eur_with_fallback(db, card)
        card["price_eur"] = price_eur
        card["price_source"] = price_source
        places = db.execute(
            """
            SELECT CASE WHEN cc.assigned_deck_id IS NOT NULL THEN 'deck' ELSE 'collection' END AS zone,
                   CASE WHEN cc.assigned_deck_id IS NOT NULL THEN d.name ELSE COALESCE(l.name, 'Ohne Ort') END AS place,
                   cc.is_proxy,
                   COUNT(*) AS quantity
            FROM card_copies cc
            LEFT JOIN locations l ON l.id = cc.location_id
            LEFT JOIN decks d ON d.id = cc.assigned_deck_id
            WHERE cc.card_id = ?
            GROUP BY zone, place, cc.is_proxy
            ORDER BY zone, place
            """,
            (row["id"],),
        ).fetchall()
        tags = readonly_card_tags(db, row["id"], row["type_line"], row["oracle_text"])["tags"]
        original_count = row["original_count"] or 0
        place_items = [
            {
                "zone": place["zone"],
                "place": place["place"],
                "is_proxy": bool(place["is_proxy"]),
                "quantity": place["quantity"],
            }
            for place in places
        ]
        item = {
            "name": card.get("printed_name") or card["name"],
            "oracle_name": card["name"],
            "scryfall_id": card.get("scryfall_id"),
            "oracle_id": card.get("oracle_id"),
            "language": card.get("lang"),
            "set": card.get("set_code"),
            "set_name": card.get("set_name"),
            "collector_number": card.get("collector_number"),
            "rarity": card.get("rarity"),
            "mana_cost": card.get("mana_cost"),
            "mana_value": card.get("cmc"),
            "type_line": card.get("printed_type_line") or card.get("type_line"),
            "oracle_text": card.get("printed_text") or card.get("oracle_text"),
            "colors": card.get("colors"),
            "color_identity": card.get("color_identity"),
            "legalities": card.get("legalities"),
            "tags": tags,
            "counts": {
                "total": row["total_count"] or 0,
                "originals": original_count,
                "proxies": row["proxy_count"] or 0,
                "free": row["free_count"] or 0,
                "in_decks": row["deck_count"] or 0,
            },
            "places": place_items,
            "price_eur": card.get("price_eur"),
            "price_source": card.get("price_source"),
            "collection_value_eur": round((card.get("price_eur") or 0) * original_count, 2),
        }
        items.append(item)

    export_format = format.strip().lower()
    if export_format == "markdown":
        lines = ["# ManaVault Collection Export", ""]
        for item in items:
            lines.append(f"## {item['counts']['total']}x {item['name']}")
            if item["oracle_name"] != item["name"]:
                lines.append(f"- Oracle name: {item['oracle_name']}")
            lines.extend(
                [
                    f"- Language: {item['language']}",
                    f"- Set: {item['set']} #{item['collector_number']}",
                    f"- Type: {item['type_line']}",
                    f"- Mana cost/value: {item['mana_cost']} / {item['mana_value']}",
                    f"- Counts: {item['counts']}",
                    f"- Tags: {', '.join(item['tags']) if item['tags'] else 'none'}",
                    f"- Price EUR: {item['price_eur']}",
                    f"- Places: {item['places']}",
                    "",
                    item["oracle_text"] or "",
                    "",
                ]
            )
        content = "\n".join(lines)
        media_type = "text/markdown; charset=utf-8"
    else:
        content = "\n".join(json.dumps(item, ensure_ascii=False) for item in items)
        media_type = "application/x-ndjson; charset=utf-8"
    return PlainTextResponse(content, media_type=media_type)


@app.get("/api/collection/cards/{card_id}")
def collection_card_detail(card_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    card = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden.")
    copies = db.execute(
        """
        SELECT cc.*, l.name AS location_name, l.type AS location_type,
               d.name AS assigned_deck_name
        FROM card_copies cc
        LEFT JOIN locations l ON l.id = cc.location_id
        LEFT JOIN decks d ON d.id = cc.assigned_deck_id
        WHERE cc.card_id = ?
        ORDER BY cc.is_proxy, l.name, d.name, cc.id
        """,
        (card_id,),
    ).fetchall()
    places = db.execute(
        """
        SELECT CASE
                 WHEN cc.assigned_deck_id IS NOT NULL THEN 'Deck'
                 ELSE 'Sammlung'
               END AS state,
               CASE
                 WHEN cc.assigned_deck_id IS NOT NULL THEN d.name
                 ELSE 'Sammlung'
               END AS place_name,
               CASE
                 WHEN cc.assigned_deck_id IS NOT NULL THEN 'Deck'
                 ELSE 'Sammlung'
               END AS place_type,
               cc.is_proxy,
               COUNT(*) AS quantity
        FROM card_copies cc
        LEFT JOIN decks d ON d.id = cc.assigned_deck_id
        WHERE cc.card_id = ?
        GROUP BY state, place_name, place_type, cc.is_proxy
        ORDER BY state, place_name
        """,
        (card_id,),
    ).fetchall()
    places_data = [dict(row) for row in places]
    places_data.extend(planned_rows_for_card(db, card_id))
    card_data = card_row(card)
    price_eur, price_source = card_price_eur_with_fallback(db, card_data)
    original_count = sum(1 for copy in copies if not copy["is_proxy"])
    card_data["price_eur"] = price_eur
    card_data["price_source"] = price_source
    card_data["collection_value_eur"] = round(price_eur * original_count, 2)
    card_data["original_count"] = original_count
    return {
        "card": card_data,
        "tags": readonly_card_tags(db, card["id"], card["type_line"], card["oracle_text"]),
        "copies": [dict(row) for row in copies],
        "places": places_data,
    }


@app.get("/api/tags/catalog")
def tags_catalog() -> list[str]:
    return TAG_CATALOG


@app.get("/api/sets/catalog")
def sets_catalog(db: sqlite3.Connection = Depends(db_dep)) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT lower(set_code) AS code,
               COALESCE(MAX(set_name), upper(set_code)) AS name,
               MAX(released_at) AS released_at,
               COUNT(*) AS card_count
        FROM cards
        WHERE set_code IS NOT NULL AND set_code != ''
        GROUP BY lower(set_code)
        ORDER BY released_at DESC, code DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/cards/{card_id}/tags")
def get_card_tags(card_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    card = db.execute("SELECT id, type_line, oracle_text FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden.")
    tags = ensure_card_tags(db, card["id"], card["type_line"], card["oracle_text"])
    db.commit()
    return tags


@app.patch("/api/cards/{card_id}/tags")
def patch_card_tags(card_id: int, payload: CardTagsPatch, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    card = db.execute("SELECT id, type_line, oracle_text FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden.")
    ensure_card_tags(db, card["id"], card["type_line"], card["oracle_text"])
    db.execute(
        """
        UPDATE card_tags
        SET manual_tags = ?, rejected_auto_tags = ?
        WHERE card_id = ?
        """,
        (json_dump(clean_tags(payload.manual_tags)), json_dump(clean_tags(payload.rejected_auto_tags)), card_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM card_tags WHERE card_id = ?", (card_id,)).fetchone()
    return tag_payload(row)


@app.post("/api/cards/refresh-tags")
def refresh_card_tags(limit: int | None = None, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, int]:
    sql = "SELECT id, type_line, oracle_text FROM cards ORDER BY id"
    params: list[Any] = []
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = db.execute(sql, params).fetchall()
    for row in rows:
        ensure_card_tags(db, row["id"], row["type_line"], row["oracle_text"])
    db.commit()
    return {"updated": len(rows)}


@app.get("/api/cards/{card_id}/availability")
def card_availability(card_id: int, deck_id: int | None = None, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    card = db.execute("SELECT id, name, image_url, mana_cost, type_line FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden.")
    copies = db.execute(
        """
        SELECT cc.*, l.name AS location_name, l.type AS location_type,
               d.name AS assigned_deck_name
        FROM card_copies cc
        LEFT JOIN locations l ON l.id = cc.location_id
        LEFT JOIN decks d ON d.id = cc.assigned_deck_id
        WHERE cc.card_id = ?
        ORDER BY cc.is_proxy, cc.assigned_deck_id, l.name, cc.id
        """,
        (card_id,),
    ).fetchall()
    free_real = []
    free_proxy = []
    in_other_decks = []
    in_this_deck = []
    for row in copies:
        item = dict(row)
        if deck_id and row["assigned_deck_id"] == deck_id:
            in_this_deck.append(item)
        elif row["assigned_deck_id"]:
            in_other_decks.append(item)
        elif row["is_proxy"]:
            free_proxy.append(item)
        else:
            free_real.append(item)
    return {
        "card": dict(card),
        "free_real": free_real,
        "free_proxy": free_proxy,
        "in_other_decks": in_other_decks,
        "in_this_deck": in_this_deck,
        "counts": {
            "free_real": len(free_real),
            "free_proxy": len(free_proxy),
            "in_other_decks": len(in_other_decks),
            "in_this_deck": len(in_this_deck),
            "total": len(copies),
        },
    }


@app.post("/api/collection/copies")
def create_copy(payload: CopyIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    card = db.execute("SELECT id FROM cards WHERE id = ?", (payload.card_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden.")
    location_id = None if payload.assigned_deck_id else payload.location_id
    cur = db.execute(
        """
        INSERT INTO card_copies
            (card_id, is_proxy, condition, language, foil, location_id, assigned_deck_id, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.card_id,
            int(payload.is_proxy),
            payload.condition,
            payload.language,
            int(payload.foil),
            location_id,
            payload.assigned_deck_id,
            payload.note,
        ),
    )
    db.commit()
    return {"id": cur.lastrowid, "card_id": payload.card_id, "counts": card_collection_counts(db, payload.card_id)}


@app.post("/api/collection/copies/batch")
def create_copies(payload: CopyBatchIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    card = db.execute("SELECT id FROM cards WHERE id = ?", (payload.card_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden.")
    quantity = max(1, min(payload.quantity, 100))
    location_id = None if payload.assigned_deck_id else payload.location_id
    values = [(
        payload.card_id, int(payload.is_proxy), payload.condition, payload.language,
        int(payload.foil), location_id, payload.assigned_deck_id, payload.note,
    ) for _ in range(quantity)]
    db.executemany(
        """
        INSERT INTO card_copies
            (card_id, is_proxy, condition, language, foil, location_id, assigned_deck_id, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    db.commit()
    return {"created": quantity, "card_id": payload.card_id, "counts": card_collection_counts(db, payload.card_id)}


@app.patch("/api/collection/copies/{copy_id}")
def patch_copy(copy_id: int, payload: CopyPatch, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    existing = db.execute("SELECT id FROM card_copies WHERE id = ?", (copy_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Copy nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return {"id": copy_id, "updated": False}
    if "assigned_deck_id" in data and data.get("assigned_deck_id") is not None:
        data["location_id"] = None
    elif "location_id" in data:
        data["assigned_deck_id"] = None
    bool_fields = {"is_proxy", "foil"}
    columns = []
    values = []
    for key, value in data.items():
        columns.append(f"{key} = ?")
        values.append(int(value) if key in bool_fields and value is not None else value)
    values.append(copy_id)
    db.execute(f"UPDATE card_copies SET {', '.join(columns)} WHERE id = ?", values)
    db.commit()
    return {"id": copy_id, "updated": True}


@app.delete("/api/collection/copies/{copy_id}")
def delete_copy(copy_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    cur = db.execute("DELETE FROM card_copies WHERE id = ?", (copy_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Copy nicht gefunden.")
    return {"deleted": True}


@app.get("/api/locations")
def locations(db: sqlite3.Connection = Depends(db_dep)) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute("SELECT * FROM locations ORDER BY name").fetchall()]


@app.get("/api/history")
def copy_history(
    q: str = "",
    action: str = "",
    limit: int = 500,
    db: sqlite3.Connection = Depends(db_dep),
) -> list[dict[str, Any]]:
    conditions = []
    params: list[Any] = []
    if q.strip():
        conditions.append("lower(card_name) LIKE ?")
        params.append(f"%{q.strip().lower()}%")
    allowed_actions = {"added", "deck_added", "deck_removed", "deck_moved", "moved", "deleted"}
    if action in allowed_actions:
        conditions.append("action = ?")
        params.append(action)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(
        f"SELECT * FROM copy_history {where} ORDER BY created_at DESC, id DESC LIMIT ?",
        [*params, max(1, min(limit, 2000))],
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/locations")
def create_location(payload: LocationIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    cur = db.execute("INSERT INTO locations (name, type) VALUES (?, ?)", (payload.name, payload.type))
    db.commit()
    return {"id": cur.lastrowid}


@app.get("/api/locations/{location_id}")
def location_detail(location_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    location = db.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if not location:
        raise HTTPException(status_code=404, detail="Location nicht gefunden.")
    copies = db.execute(
        """
        SELECT cc.*, c.name AS card_name, c.printed_name, c.lang, c.mana_cost, c.type_line,
               c.printed_type_line, c.image_url,
               c.set_code, c.collector_number, c.rarity
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id
        WHERE cc.location_id = ? AND cc.assigned_deck_id IS NULL
        ORDER BY c.name, cc.is_proxy, cc.id
        """,
        (location_id,),
    ).fetchall()
    summary = db.execute(
        """
        SELECT c.id AS card_id, c.name, c.printed_name, c.lang, c.mana_cost, c.type_line,
               c.printed_type_line, c.image_url,
               COUNT(cc.id) AS total_count,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS owned_count,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxy_count
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id
        WHERE cc.location_id = ? AND cc.assigned_deck_id IS NULL
        GROUP BY c.id
        ORDER BY c.name
        """,
        (location_id,),
    ).fetchall()
    return {
        "location": dict(location),
        "summary": [dict(row) for row in summary],
        "copies": [dict(row) for row in copies],
    }


@app.patch("/api/locations/{location_id}")
def patch_location(location_id: int, payload: LocationPatch, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    existing = db.execute("SELECT id FROM locations WHERE id = ?", (location_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Location nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return {"id": location_id, "updated": False}
    columns = []
    values = []
    for key, value in data.items():
        columns.append(f"{key} = ?")
        values.append(value)
    values.append(location_id)
    db.execute(f"UPDATE locations SET {', '.join(columns)} WHERE id = ?", values)
    db.commit()
    return {"id": location_id, "updated": True}


@app.delete("/api/locations/{location_id}")
def delete_location(
    location_id: int,
    move_to_location_id: int | None = None,
    detach_copies: bool = False,
    db: sqlite3.Connection = Depends(db_dep),
) -> dict[str, Any]:
    in_use = db.execute("SELECT COUNT(*) AS count FROM card_copies WHERE location_id = ?", (location_id,)).fetchone()
    if in_use and in_use["count"]:
        if move_to_location_id:
            target = db.execute("SELECT id FROM locations WHERE id = ? AND id != ?", (move_to_location_id, location_id)).fetchone()
            if not target:
                raise HTTPException(status_code=400, detail="Ziel-Location nicht gefunden.")
            db.execute("UPDATE card_copies SET location_id = ? WHERE location_id = ?", (move_to_location_id, location_id))
        elif detach_copies:
            db.execute("UPDATE card_copies SET location_id = NULL WHERE location_id = ?", (location_id,))
        else:
            raise HTTPException(
                status_code=409,
                detail={"message": "Location wird noch von Copies benutzt.", "copy_count": in_use["count"]},
            )
    cur = db.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Location nicht gefunden.")
    return {"deleted": True}


@app.get("/api/decks")
def decks(db: sqlite3.Connection = Depends(db_dep)) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT d.*, c.name AS commander_name, c.image_url AS commander_image_url,
               COALESCE(SUM(CASE WHEN COALESCE(dc.is_token, 0) = 0 THEN ds.quantity ELSE 0 END), 0) AS slot_quantity,
               COALESCE(SUM(CASE WHEN COALESCE(dc.is_token, 0) = 1 THEN ds.quantity ELSE 0 END), 0) AS token_quantity
        FROM decks d
        LEFT JOIN cards c ON c.id = d.commander_card_id
        LEFT JOIN deck_slots ds ON ds.deck_id = d.id
        LEFT JOIN cards dc ON dc.id = ds.card_id
        GROUP BY d.id
        ORDER BY d.name
        """
    ).fetchall()
    result = []
    for row in rows:
        deck = dict(row)
        slot_rows = db.execute(
            """
            SELECT ds.quantity, c.*
            FROM deck_slots ds
            JOIN cards c ON c.id = ds.card_id
            WHERE ds.deck_id = ?
            """,
            (row["id"],),
        ).fetchall()
        colors: set[str] = set()
        types: set[str] = set()
        deck_value = 0.0
        for slot in slot_rows:
            card = card_row(slot)
            if card.get("is_token"):
                continue
            identity = card.get("color_identity") or card.get("colors") or []
            if identity:
                colors.update(color for color in identity if color in {"W", "U", "B", "R", "G"})
            else:
                colors.add("C")
            type_line = str(card.get("type_line") or "")
            for type_name in ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Land"]:
                if type_name in type_line:
                    types.add(type_name)
            price_eur, _price_source = card_price_eur_with_fallback(db, card)
            deck_value += price_eur * int(slot["quantity"] or 0)
        deck["colors"] = sorted(colors)
        deck["types"] = sorted(types)
        deck["deck_list_value_eur"] = round(deck_value, 2)
        result.append(deck)
    return result


@app.post("/api/decks")
def create_deck(payload: DeckIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    cur = db.execute(
        "INSERT INTO decks (name, format, commander_card_id, notes) VALUES (?, ?, ?, ?)",
        (payload.name, payload.format, payload.commander_card_id, payload.notes),
    )
    db.commit()
    return {"id": cur.lastrowid}


@app.patch("/api/decks/{deck_id}")
def patch_deck(deck_id: int, payload: DeckPatch, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    existing = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return {"id": deck_id, "updated": False}
    columns = []
    values = []
    for key, value in data.items():
        columns.append(f"{key} = ?")
        values.append(value)
    values.append(deck_id)
    db.execute(f"UPDATE decks SET {', '.join(columns)} WHERE id = ?", values)
    if "commander_card_id" in data:
        sync_active_variant_if_not_editing(deck_id, db)
    db.commit()
    return {"id": deck_id, "updated": True}


def deck_slot_snapshot(deck_id: int, db: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        db.execute(
            """
            SELECT card_id, quantity, allow_proxy, note, zone
            FROM deck_slots
            WHERE deck_id = ?
            ORDER BY zone, card_id
            """,
            (deck_id,),
        ).fetchall()
    )


def replace_working_deck_slots(deck_id: int, slots: list[dict[str, Any]], db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM deck_slots WHERE deck_id = ?", (deck_id,))
    for slot in slots:
        db.execute(
            """
            INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy, note, zone)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deck_id,
                int(slot["card_id"]),
                max(1, int(slot.get("quantity") or 1)),
                int(bool(slot.get("allow_proxy", True))),
                slot.get("note"),
                normalized_deck_zone(slot.get("zone")),
            ),
        )


def replace_variant_slots(variant_id: int, slots: list[dict[str, Any]], db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM deck_variant_slots WHERE variant_id = ?", (variant_id,))
    for slot in slots:
        db.execute(
            """
            INSERT INTO deck_variant_slots (variant_id, card_id, quantity, allow_proxy, note, zone)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                variant_id,
                int(slot["card_id"]),
                max(1, int(slot.get("quantity") or 1)),
                int(bool(slot.get("allow_proxy", True))),
                slot.get("note"),
                normalized_deck_zone(slot.get("zone")),
            ),
        )


def create_variant_snapshot(
    deck_id: int,
    name: str,
    slots: list[dict[str, Any]],
    db: sqlite3.Connection,
    commander_card_id: int | None = None,
) -> int:
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Bitte einen Variantennamen angeben.")
    try:
        cur = db.execute(
            "INSERT INTO deck_variants (deck_id, name, commander_card_id) VALUES (?, ?, ?)",
            (deck_id, clean_name, commander_card_id),
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Eine Variante mit diesem Namen existiert bereits.") from error
    replace_variant_slots(int(cur.lastrowid), slots, db)
    return int(cur.lastrowid)


def sync_active_variant_if_not_editing(deck_id: int, db: sqlite3.Connection) -> None:
    editing = db.execute("SELECT 1 FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,)).fetchone()
    if editing:
        return
    deck = db.execute("SELECT active_variant_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck and deck["active_variant_id"]:
        replace_variant_slots(int(deck["active_variant_id"]), deck_slot_snapshot(deck_id, db), db)
        db.execute(
            """
            UPDATE deck_variants
            SET commander_card_id = (SELECT commander_card_id FROM decks WHERE id = ?),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (deck_id, deck["active_variant_id"]),
        )


def deck_edit_is_dirty(deck_id: int, db: sqlite3.Connection) -> bool:
    session = db.execute("SELECT * FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,)).fetchone()
    if not session:
        return False
    baseline = json.loads(session["baseline_slots_json"])
    current = deck_slot_snapshot(deck_id, db)
    normalized = lambda slots: sorted(
        (
            int(slot["card_id"]),
            int(slot.get("quantity") or 0),
            int(bool(slot.get("allow_proxy", True))),
            slot.get("note") or "",
            normalized_deck_zone(slot.get("zone")),
        )
        for slot in slots
    )
    deck = db.execute("SELECT commander_card_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    return normalized(baseline) != normalized(current) or deck["commander_card_id"] != session["baseline_commander_card_id"]


def reconcile_deck_assignments(deck_id: int, db: sqlite3.Connection) -> None:
    requirements = db.execute(
        """
        SELECT card_id, SUM(quantity) AS quantity,
               SUM(CASE WHEN allow_proxy = 1 THEN quantity ELSE 0 END) AS proxy_quantity
        FROM deck_slots
        WHERE deck_id = ?
        GROUP BY card_id
        """,
        (deck_id,),
    ).fetchall()
    required = {int(row["card_id"]): (int(row["quantity"]), int(row["proxy_quantity"])) for row in requirements}
    assigned_cards = db.execute(
        "SELECT DISTINCT card_id FROM card_copies WHERE assigned_deck_id = ?",
        (deck_id,),
    ).fetchall()
    for row in assigned_cards:
        card_id = int(row["card_id"])
        quantity, proxy_quantity = required.get(card_id, (0, 0))
        copies = db.execute(
            "SELECT id, is_proxy FROM card_copies WHERE assigned_deck_id = ? AND card_id = ? ORDER BY is_proxy, id",
            (deck_id, card_id),
        ).fetchall()
        kept_real = 0
        kept_proxy = 0
        for copy in copies:
            keep = False
            if not copy["is_proxy"] and kept_real < quantity:
                kept_real += 1
                keep = True
            elif copy["is_proxy"] and kept_real + kept_proxy < quantity and kept_proxy < proxy_quantity:
                kept_proxy += 1
                keep = True
            if not keep:
                db.execute("UPDATE card_copies SET assigned_deck_id = NULL WHERE id = ?", (copy["id"],))
    for card_id, (quantity, proxy_quantity) in required.items():
        assigned = db.execute(
            "SELECT is_proxy, COUNT(*) AS quantity FROM card_copies WHERE assigned_deck_id = ? AND card_id = ? GROUP BY is_proxy",
            (deck_id, card_id),
        ).fetchall()
        real_count = sum(int(row["quantity"]) for row in assigned if not row["is_proxy"])
        proxy_count = sum(int(row["quantity"]) for row in assigned if row["is_proxy"])
        needed = max(0, quantity - real_count - proxy_count)
        free_real = db.execute(
            "SELECT id FROM card_copies WHERE card_id = ? AND is_proxy = 0 AND assigned_deck_id IS NULL ORDER BY id LIMIT ?",
            (card_id, needed),
        ).fetchall()
        for copy in free_real:
            db.execute("UPDATE card_copies SET assigned_deck_id = ?, location_id = NULL WHERE id = ?", (deck_id, copy["id"]))
        needed -= len(free_real)
        proxy_capacity = max(0, proxy_quantity - proxy_count)
        if needed > 0 and proxy_capacity > 0:
            free_proxy = db.execute(
                "SELECT id FROM card_copies WHERE card_id = ? AND is_proxy = 1 AND assigned_deck_id IS NULL ORDER BY id LIMIT ?",
                (card_id, min(needed, proxy_capacity)),
            ).fetchall()
            for copy in free_proxy:
                db.execute("UPDATE card_copies SET assigned_deck_id = ?, location_id = NULL WHERE id = ?", (deck_id, copy["id"]))


@app.post("/api/decks/{deck_id}/edit/begin")
def begin_deck_edit(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT id, active_variant_id, commander_card_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    existing = db.execute("SELECT started_at FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,)).fetchone()
    if not existing:
        db.execute(
            """
            INSERT INTO deck_edit_sessions
                (deck_id, base_variant_id, baseline_slots_json, baseline_commander_card_id)
            VALUES (?, ?, ?, ?)
            """,
            (deck_id, deck["active_variant_id"], json.dumps(deck_slot_snapshot(deck_id, db)), deck["commander_card_id"]),
        )
        db.commit()
    return {"editing": True, "started_at": existing["started_at"] if existing else None}


@app.post("/api/decks/{deck_id}/edit/save")
def save_deck_edit(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT id, active_variant_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    if deck["active_variant_id"]:
        replace_variant_slots(int(deck["active_variant_id"]), deck_slot_snapshot(deck_id, db), db)
        db.execute(
            """
            UPDATE deck_variants
            SET commander_card_id = (SELECT commander_card_id FROM decks WHERE id = ?),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (deck_id, deck["active_variant_id"]),
        )
    db.execute("DELETE FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,))
    db.commit()
    return {"saved": True, "active_variant_id": deck["active_variant_id"]}


@app.post("/api/decks/{deck_id}/edit/discard")
def discard_deck_edit(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    session = db.execute("SELECT * FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,)).fetchone()
    if not session:
        return {"discarded": False}
    replace_working_deck_slots(deck_id, json.loads(session["baseline_slots_json"]), db)
    db.execute(
        "UPDATE decks SET commander_card_id = ?, active_variant_id = ? WHERE id = ?",
        (session["baseline_commander_card_id"], session["base_variant_id"], deck_id),
    )
    reconcile_deck_assignments(deck_id, db)
    db.execute("DELETE FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,))
    db.commit()
    return {"discarded": True}


@app.get("/api/decks/{deck_id}/variants")
def deck_variants(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT id, active_variant_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    variants = rows_as_dicts(
        db.execute(
            """
            SELECT dv.*, COALESCE(SUM(dvs.quantity), 0) AS card_count
            FROM deck_variants dv
            LEFT JOIN deck_variant_slots dvs ON dvs.variant_id = dv.id
            WHERE dv.deck_id = ?
            GROUP BY dv.id
            ORDER BY dv.created_at, dv.id
            """,
            (deck_id,),
        ).fetchall()
    )
    return {
        "active_variant_id": deck["active_variant_id"],
        "editing": bool(db.execute("SELECT 1 FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,)).fetchone()),
        "dirty": deck_edit_is_dirty(deck_id, db),
        "variants": variants,
    }


@app.post("/api/decks/{deck_id}/variants")
def save_as_deck_variant(deck_id: int, payload: DeckVariantCreateIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT id, active_variant_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    session = db.execute("SELECT * FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,)).fetchone()
    if not session:
        raise HTTPException(status_code=409, detail="Keine laufende Deckbearbeitung.")
    if not deck["active_variant_id"]:
        create_variant_snapshot(
            deck_id,
            payload.base_name,
            json.loads(session["baseline_slots_json"]),
            db,
            session["baseline_commander_card_id"],
        )
    commander = db.execute("SELECT commander_card_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    variant_id = create_variant_snapshot(
        deck_id,
        payload.name,
        deck_slot_snapshot(deck_id, db),
        db,
        commander["commander_card_id"],
    )
    db.execute("UPDATE decks SET active_variant_id = ? WHERE id = ?", (variant_id, deck_id))
    db.execute("DELETE FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,))
    db.commit()
    return {"created": True, "id": variant_id, "active_variant_id": variant_id}


@app.patch("/api/decks/{deck_id}/variants/{variant_id}")
def rename_deck_variant(deck_id: int, variant_id: int, payload: DeckVariantPatchIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Bitte einen Variantennamen angeben.")
    try:
        cur = db.execute("UPDATE deck_variants SET name = ? WHERE id = ? AND deck_id = ?", (clean_name, variant_id, deck_id))
        db.commit()
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Eine Variante mit diesem Namen existiert bereits.") from error
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="Variante nicht gefunden.")
    return {"updated": True}


@app.post("/api/decks/{deck_id}/variants/{variant_id}/activate")
def activate_deck_variant(deck_id: int, variant_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    if deck_edit_is_dirty(deck_id, db):
        raise HTTPException(status_code=409, detail="Bitte aktuelle Aenderungen zuerst speichern oder verwerfen.")
    db.execute("DELETE FROM deck_edit_sessions WHERE deck_id = ?", (deck_id,))
    variant = db.execute("SELECT id, name, commander_card_id FROM deck_variants WHERE id = ? AND deck_id = ?", (variant_id, deck_id)).fetchone()
    if not variant:
        raise HTTPException(status_code=404, detail="Variante nicht gefunden.")
    slots = rows_as_dicts(db.execute("SELECT card_id, quantity, allow_proxy, note, zone FROM deck_variant_slots WHERE variant_id = ?", (variant_id,)).fetchall())
    replace_working_deck_slots(deck_id, slots, db)
    db.execute(
        "UPDATE decks SET active_variant_id = ?, commander_card_id = ? WHERE id = ?",
        (variant_id, variant["commander_card_id"], deck_id),
    )
    reconcile_deck_assignments(deck_id, db)
    db.commit()
    status = deck_status(deck_id, db)
    missing = sum(int(item["missing"]) for item in status["cards"])
    return {"activated": True, "id": variant_id, "name": variant["name"], "missing": missing}


@app.delete("/api/decks/{deck_id}")
def delete_deck(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    db.execute("UPDATE card_copies SET assigned_deck_id = NULL WHERE assigned_deck_id = ?", (deck_id,))
    cur = db.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    return {"deleted": True}


@app.get("/api/decks/{deck_id}")
def deck_detail(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    slots = db.execute(
        """
        SELECT ds.*, c.name, c.mana_cost, c.type_line, c.image_url, c.is_token,
               CASE WHEN d.commander_card_id = c.id THEN 1 ELSE 0 END AS is_cover
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        JOIN decks d ON d.id = ds.deck_id
        WHERE ds.deck_id = ?
        ORDER BY c.name
        """,
        (deck_id,),
    ).fetchall()
    return {"deck": dict(deck), "slots": [dict(row) for row in slots]}


@app.get("/api/decks/{deck_id}/qr")
def deck_qr_code(
    deck_id: int,
    request: Request,
    base_url: str | None = None,
    download: bool = False,
    db: sqlite3.Connection = Depends(db_dep),
) -> Response:
    deck, token = ensure_deck_share_token(deck_id, db)
    origin = configured_public_base_url()
    if not origin:
        raise HTTPException(status_code=409, detail="Oeffentliche Adresse noch nicht eingerichtet.")
    deck_url = f"{origin}/share/{token}"
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="QR-Code-Unterstuetzung ist nicht installiert.") from exc
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(deck_url)
    qr.make(fit=True)
    output = io.BytesIO()
    qr.make_image(image_factory=SvgPathImage).save(output)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", deck["name"]).strip("-") or f"deck-{deck_id}"
    disposition = "attachment" if download else "inline"
    return Response(
        content=output.getvalue(),
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}-qr.svg"'},
    )


@app.post("/api/decks/{deck_id}/slots")
def add_slot(deck_id: int, payload: DeckSlotIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    if payload.quantity < 1:
        raise HTTPException(status_code=400, detail="quantity muss mindestens 1 sein.")
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    card = db.execute("SELECT id FROM cards WHERE id = ?", (payload.card_id,)).fetchone()
    if not deck or not card:
        raise HTTPException(status_code=404, detail="Deck oder Karte nicht gefunden.")
    zone = normalized_deck_zone(payload.zone)
    cur = db.execute(
        """
        INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy, note, zone)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(deck_id, card_id, zone) DO UPDATE SET
            quantity=excluded.quantity,
            allow_proxy=excluded.allow_proxy,
            note=excluded.note
        """,
        (deck_id, payload.card_id, payload.quantity, int(payload.allow_proxy), payload.note, zone),
    )
    sync_active_variant_if_not_editing(deck_id, db)
    db.commit()
    return {"id": cur.lastrowid}


def deck_location_id(db: sqlite3.Connection) -> int | None:
    row = db.execute("SELECT id FROM locations WHERE type = 'Deck' ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    row = db.execute("SELECT id FROM locations WHERE name = 'Deck' ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def upsert_deck_slot(
    db: sqlite3.Connection,
    deck_id: int,
    card_id: int,
    quantity_delta: int,
    allow_proxy: bool,
    zone: str = "mainboard",
) -> None:
    zone = normalized_deck_zone(zone)
    db.execute(
        """
        INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy, zone)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(deck_id, card_id, zone) DO UPDATE SET
            quantity=deck_slots.quantity + excluded.quantity,
            allow_proxy=excluded.allow_proxy
        """,
        (deck_id, card_id, quantity_delta, int(allow_proxy), zone),
    )


@app.post("/api/decks/{deck_id}/add-card")
def smart_add_card(deck_id: int, payload: DeckAddCardIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    if payload.quantity < 1:
        raise HTTPException(status_code=400, detail="quantity muss mindestens 1 sein.")
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    card = db.execute("SELECT id, name FROM cards WHERE id = ?", (payload.card_id,)).fetchone()
    if not deck or not card:
        raise HTTPException(status_code=404, detail="Deck oder Karte nicht gefunden.")

    action = payload.action
    assigned_copy_ids: list[int] = []
    created_proxy_ids: list[int] = []

    if action == "auto":
        free = db.execute(
            """
            SELECT id FROM card_copies
            WHERE card_id = ? AND is_proxy = 0 AND assigned_deck_id IS NULL
            ORDER BY id
            LIMIT ?
            """,
            (payload.card_id, payload.quantity),
        ).fetchall()
        if len(free) < payload.quantity and payload.allow_proxy:
            proxy_needed = payload.quantity - len(free)
            free_proxy = db.execute(
                """
                SELECT id FROM card_copies
                WHERE card_id = ? AND is_proxy = 1 AND assigned_deck_id IS NULL
                ORDER BY id
                LIMIT ?
                """,
                (payload.card_id, proxy_needed),
            ).fetchall()
            free = [*free, *free_proxy]
        if len(free) < payload.quantity:
            return {
                "requires_decision": True,
                "reason": "not_enough_free_copies",
                "availability": card_availability(payload.card_id, deck_id, db),
            }
        for copy in free:
            db.execute(
                "UPDATE card_copies SET assigned_deck_id = ?, location_id = NULL WHERE id = ?",
                (deck_id, copy["id"]),
            )
            assigned_copy_ids.append(copy["id"])

    elif action == "use_copy":
        if not payload.copy_id:
            raise HTTPException(status_code=400, detail="copy_id fehlt.")
        copy = db.execute("SELECT * FROM card_copies WHERE id = ? AND card_id = ?", (payload.copy_id, payload.card_id)).fetchone()
        if not copy:
            raise HTTPException(status_code=404, detail="Copy nicht gefunden.")
        db.execute(
            "UPDATE card_copies SET assigned_deck_id = ?, location_id = NULL WHERE id = ?",
            (deck_id, payload.copy_id),
        )
        assigned_copy_ids.append(payload.copy_id)

    elif action == "proxy":
        for _ in range(payload.quantity):
            cur = db.execute(
                """
                INSERT INTO card_copies
                    (card_id, is_proxy, condition, language, foil, location_id, assigned_deck_id, note)
                VALUES (?, 1, 'Proxy', 'en', 0, ?, ?, 'Created from deckbuilder')
                """,
                (payload.card_id, None, deck_id),
            )
            created_proxy_ids.append(cur.lastrowid)

    elif action == "create_original":
        for _ in range(payload.quantity):
            cur = db.execute(
                """
                INSERT INTO card_copies
                    (card_id, is_proxy, condition, language, foil, location_id, assigned_deck_id, note)
                VALUES (?, 0, 'NM', 'en', 0, NULL, ?, 'Created from deckbuilder')
                """,
                (payload.card_id, deck_id),
            )
            assigned_copy_ids.append(cur.lastrowid)

    elif action == "plan":
        pass

    else:
        raise HTTPException(status_code=400, detail="Unbekannte action.")

    upsert_deck_slot(db, deck_id, payload.card_id, payload.quantity, payload.allow_proxy, payload.zone)
    sync_active_variant_if_not_editing(deck_id, db)
    db.commit()
    return {
        "requires_decision": False,
        "card_id": payload.card_id,
        "card_name": card["name"],
        "assigned_copy_ids": assigned_copy_ids,
        "created_proxy_ids": created_proxy_ids,
        "counts": card_collection_counts(db, payload.card_id),
    }


@app.post("/api/decks/{deck_id}/assign-free")
def assign_free_copies(deck_id: int, payload: DeckAssignFreeIn | None = None, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    payload = payload or DeckAssignFreeIn()
    scope = payload.scope if payload.scope in {"cards", "tokens", "all"} else "cards"
    slot_params: list[Any] = [deck_id]
    card_filter = ""
    if payload.card_id is not None:
        card_filter = "AND ds.card_id = ?"
        slot_params.append(payload.card_id)
    scope_filter = ""
    if payload.card_id is None and scope == "cards":
        scope_filter = "AND COALESCE(c.is_token, 0) = 0"
    elif payload.card_id is None and scope == "tokens":
        scope_filter = "AND COALESCE(c.is_token, 0) = 1"
    slots = db.execute(
        f"""
        SELECT ds.*, c.name, c.is_token
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        {card_filter}
        {scope_filter}
        ORDER BY c.name
        """,
        slot_params,
    ).fetchall()
    assigned: list[dict[str, Any]] = []
    for slot in slots:
        assigned_rows = db.execute(
            """
            SELECT is_proxy, COUNT(*) AS quantity
            FROM card_copies
            WHERE card_id = ? AND assigned_deck_id = ?
            GROUP BY is_proxy
            """,
            (slot["card_id"], deck_id),
        ).fetchall()
        real_assigned = sum(row["quantity"] for row in assigned_rows if not row["is_proxy"])
        proxy_assigned = sum(row["quantity"] for row in assigned_rows if row["is_proxy"])
        covered = real_assigned + (proxy_assigned if slot["allow_proxy"] else 0)
        needed = max(0, slot["quantity"] - covered)
        if needed <= 0:
            continue

        copy_ids: list[int] = []
        real_free = db.execute(
            """
            SELECT id FROM card_copies
            WHERE card_id = ? AND is_proxy = 0 AND assigned_deck_id IS NULL
            ORDER BY id
            LIMIT ?
            """,
            (slot["card_id"], needed),
        ).fetchall()
        copy_ids.extend(row["id"] for row in real_free)
        needed -= len(real_free)

        if needed > 0 and slot["allow_proxy"]:
            proxy_free = db.execute(
                """
                SELECT id FROM card_copies
                WHERE card_id = ? AND is_proxy = 1 AND assigned_deck_id IS NULL
                ORDER BY id
                LIMIT ?
                """,
                (slot["card_id"], needed),
            ).fetchall()
            copy_ids.extend(row["id"] for row in proxy_free)

        for copy_id in copy_ids:
            db.execute(
                "UPDATE card_copies SET assigned_deck_id = ?, location_id = NULL WHERE id = ?",
                (deck_id, copy_id),
            )
        if copy_ids:
            assigned.append({"card_id": slot["card_id"], "name": slot["name"], "quantity": len(copy_ids)})
    db.commit()
    return {"assigned": assigned, "assigned_count": sum(item["quantity"] for item in assigned)}


@app.delete("/api/decks/{deck_id}/slots/{slot_id}")
def delete_slot(deck_id: int, slot_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    slot = db.execute(
        "SELECT card_id FROM deck_slots WHERE id = ? AND deck_id = ?",
        (slot_id, deck_id),
    ).fetchone()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot nicht gefunden.")
    db.execute(
        "UPDATE decks SET commander_card_id = NULL WHERE id = ? AND commander_card_id = ?",
        (deck_id, slot["card_id"]),
    )
    cur = db.execute("DELETE FROM deck_slots WHERE id = ? AND deck_id = ?", (slot_id, deck_id))
    before_assigned = db.execute(
        "SELECT COUNT(*) AS count FROM card_copies WHERE assigned_deck_id = ? AND card_id = ?",
        (deck_id, slot["card_id"]),
    ).fetchone()["count"]
    reconcile_deck_assignments(deck_id, db)
    after_assigned = db.execute(
        "SELECT COUNT(*) AS count FROM card_copies WHERE assigned_deck_id = ? AND card_id = ?",
        (deck_id, slot["card_id"]),
    ).fetchone()["count"]
    sync_active_variant_if_not_editing(deck_id, db)
    db.commit()
    return {
        "deleted": True,
        "freed_card_id": slot["card_id"],
        "freed_copies": max(0, int(before_assigned) - int(after_assigned)),
        "counts": card_collection_counts(db, slot["card_id"]),
    }


@app.post("/api/decks/{deck_id}/slots/{slot_id}/decrement")
def decrement_slot(deck_id: int, slot_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    slot = db.execute(
        "SELECT card_id, quantity FROM deck_slots WHERE id = ? AND deck_id = ?",
        (slot_id, deck_id),
    ).fetchone()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot nicht gefunden.")

    card_id = int(slot["card_id"])
    old_quantity = int(slot["quantity"] or 0)
    remaining_quantity = max(0, old_quantity - 1)
    before_assigned = db.execute(
        "SELECT COUNT(*) AS count FROM card_copies WHERE assigned_deck_id = ? AND card_id = ?",
        (deck_id, card_id),
    ).fetchone()["count"]

    if remaining_quantity == 0:
        db.execute(
            "UPDATE decks SET commander_card_id = NULL WHERE id = ? AND commander_card_id = ?",
            (deck_id, card_id),
        )
        db.execute("DELETE FROM deck_slots WHERE id = ? AND deck_id = ?", (slot_id, deck_id))
    else:
        db.execute(
            "UPDATE deck_slots SET quantity = ? WHERE id = ? AND deck_id = ?",
            (remaining_quantity, slot_id, deck_id),
        )
    reconcile_deck_assignments(deck_id, db)
    after_assigned = db.execute(
        "SELECT COUNT(*) AS count FROM card_copies WHERE assigned_deck_id = ? AND card_id = ?",
        (deck_id, card_id),
    ).fetchone()["count"]
    freed_copies = max(0, int(before_assigned) - int(after_assigned))
    sync_active_variant_if_not_editing(deck_id, db)

    db.commit()
    return {
        "removed": remaining_quantity == 0,
        "remaining_quantity": remaining_quantity,
        "freed_card_id": card_id,
        "freed_copies": freed_copies,
        "counts": card_collection_counts(db, card_id),
    }


@app.post("/api/decks/{deck_id}/slots/{slot_id}/zone")
def move_slot_zone(deck_id: int, slot_id: int, payload: DeckSlotZoneIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    zone = normalized_deck_zone(payload.zone)
    slot = db.execute("SELECT * FROM deck_slots WHERE id = ? AND deck_id = ?", (slot_id, deck_id)).fetchone()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot nicht gefunden.")
    if slot["zone"] == zone:
        return {"moved": False, "zone": zone}
    existing = db.execute(
        "SELECT id, quantity FROM deck_slots WHERE deck_id = ? AND card_id = ? AND zone = ?",
        (deck_id, slot["card_id"], zone),
    ).fetchone()
    if existing:
        db.execute("UPDATE deck_slots SET quantity = quantity + ? WHERE id = ?", (slot["quantity"], existing["id"]))
        db.execute("DELETE FROM deck_slots WHERE id = ?", (slot_id,))
    else:
        db.execute("UPDATE deck_slots SET zone = ? WHERE id = ?", (zone, slot_id))
    sync_active_variant_if_not_editing(deck_id, db)
    db.commit()
    return {"moved": True, "zone": zone}


def required_tokens_for_deck(deck_id: int, db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT t.*, COALESCE(source.printed_name, source.name) AS source_name
        FROM deck_slots ds
        JOIN cards source ON source.id = ds.card_id AND COALESCE(source.is_token, 0) = 0
        JOIN card_token_links link ON link.source_scryfall_id = source.scryfall_id
        JOIN cards t ON t.scryfall_id = link.token_scryfall_id AND COALESCE(t.is_token, 0) = 1
        WHERE ds.deck_id = ?
        ORDER BY CASE t.lang WHEN 'de' THEN 0 WHEN 'en' THEN 1 ELSE 2 END,
                 t.name, t.released_at DESC
        """,
        (deck_id,),
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        card = card_row(row)
        token_key = str(card.get("oracle_id") or card.get("scryfall_id"))
        entry = grouped.setdefault(
            token_key,
            {
                "token_key": token_key,
                "card_id": int(card["id"]),
                "name": card.get("printed_name") or card.get("name") or "Token",
                "oracle_name": card.get("name") or "Token",
                "type_line": card.get("printed_type_line") or card.get("type_line") or "",
                "image_url": card.get("image_url"),
                "set_code": card.get("set_code"),
                "collector_number": card.get("collector_number"),
                "lang": card.get("lang"),
                "is_token": True,
                "source_names": set(),
            },
        )
        entry["source_names"].add(str(row["source_name"]))

    assigned_rows = db.execute(
        """
        SELECT COALESCE(c.oracle_id, c.scryfall_id) AS token_key,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS originals,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxies
        FROM card_copies cc
        JOIN cards c ON c.id = cc.card_id AND COALESCE(c.is_token, 0) = 1
        WHERE cc.assigned_deck_id = ?
        GROUP BY COALESCE(c.oracle_id, c.scryfall_id)
        """,
        (deck_id,),
    ).fetchall()
    assigned = {str(row["token_key"]): dict(row) for row in assigned_rows}
    listed_rows = db.execute(
        """
        SELECT COALESCE(c.oracle_id, c.scryfall_id) AS token_key, SUM(ds.quantity) AS quantity
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id AND COALESCE(c.is_token, 0) = 1
        WHERE ds.deck_id = ?
        GROUP BY COALESCE(c.oracle_id, c.scryfall_id)
        """,
        (deck_id,),
    ).fetchall()
    listed = {str(row["token_key"]): int(row["quantity"] or 0) for row in listed_rows}

    result = []
    for token_key, entry in grouped.items():
        counts = assigned.get(token_key, {})
        originals = int(counts.get("originals") or 0)
        proxies = int(counts.get("proxies") or 0)
        item = dict(entry)
        item["source_names"] = sorted(entry["source_names"])
        item["suggested_quantity"] = 1
        item["listed_quantity"] = listed.get(token_key, 0)
        item["originals"] = originals
        item["proxies"] = proxies
        item["missing"] = max(0, 1 - originals - proxies)
        result.append(item)
    return sorted(result, key=lambda item: str(item["name"]).lower())


ABILITY_COUNTER_LABELS = {
    "deathtouch": "Todesberührung-Marker",
    "double strike": "Doppelschlag-Marker",
    "first strike": "Erstschlag-Marker",
    "flying": "Flugfähigkeit-Marker",
    "haste": "Eile-Marker",
    "hexproof": "Fluchsicherheits-Marker",
    "indestructible": "Unzerstörbarkeits-Marker",
    "lifelink": "Lebensverknüpfungs-Marker",
    "menace": "Bedrohlichkeits-Marker",
    "reach": "Reichweiten-Marker",
    "trample": "Trampelschaden-Marker",
    "vigilance": "Wachsamkeits-Marker",
}

COMMON_COUNTER_LABELS = {
    "age": "Altersmarker",
    "bounty": "Kopfgeldmarker",
    "brick": "Ziegelmarker",
    "charge": "Ladungsmarker",
    "defense": "Verteidigungsmarker",
    "delay": "Verzögerungsmarker",
    "depletion": "Erschöpfungsmarker",
    "doom": "Verhängnismarker",
    "dream": "Traummarker",
    "energy": "Energiemarker",
    "experience": "Erfahrungsmarker",
    "fate": "Schicksalsmarker",
    "finality": "Endgültigkeitsmarker",
    "fuse": "Zündmarker",
    "growth": "Wachstumsmarker",
    "ice": "Eismarker",
    "infection": "Infektionsmarker",
    "invitation": "Einladungsmarker",
    "knowledge": "Wissensmarker",
    "level": "Stufenmarker",
    "lore": "Sagenmarker",
    "loyalty": "Loyalitätsmarker",
    "luck": "Glücksmarker",
    "oil": "Ölmarker",
    "page": "Seitenmarker",
    "petal": "Blütenblattmarker",
    "poison": "Giftmarker",
    "quest": "Questmarker",
    "shield": "Schildmarker",
    "spore": "Sporenmarker",
    "storage": "Speichermarker",
    "stun": "Betäubungsmarker",
    "time": "Zeitmarker",
    "training": "Trainingsmarker",
    "verse": "Versmarker",
    "vitality": "Vitalitätsmarker",
    "void": "Leerenmarker",
    "wish": "Wunschmarker",
}


def accessories_for_deck(deck_id: int, db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT COALESCE(c.printed_name, c.name) AS display_name, c.name, c.type_line, c.oracle_text
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ? AND COALESCE(c.is_token, 0) = 0
        """,
        (deck_id,),
    ).fetchall()
    accessories: dict[tuple[str, str], dict[str, Any]] = {}

    def add(category: str, key: str, name: str, source: str) -> None:
        item = accessories.setdefault(
            (category, key),
            {"category": category, "key": key, "name": name, "source_names": set()},
        )
        item["source_names"].add(source)

    for row in rows:
        source = str(row["display_name"] or row["name"])
        text = str(row["oracle_text"] or "").lower().replace("−", "-")
        type_line = str(row["type_line"] or "").lower()

        for match in re.finditer(r"(?<!\w)([+-]\d+/[+-]\d+) counters?\b", text):
            value = match.group(1)
            add("counter", value, f"{value}-Marker", source)
        for ability, label in ABILITY_COUNTER_LABELS.items():
            if re.search(rf"\b{re.escape(ability)} counters?\b", text):
                add("ability_counter", ability, label, source)
        for counter, label in COMMON_COUNTER_LABELS.items():
            if re.search(rf"\b{re.escape(counter)} counters?\b", text):
                add("counter", counter, label, source)

        if "planeswalker" in type_line:
            add("counter", "loyalty", COMMON_COUNTER_LABELS["loyalty"], source)
        if "saga" in type_line:
            add("counter", "lore", COMMON_COUNTER_LABELS["lore"], source)
        if "battle" in type_line:
            add("counter", "defense", COMMON_COUNTER_LABELS["defense"], source)
        if "{e}" in text:
            add("counter", "energy", COMMON_COUNTER_LABELS["energy"], source)
        if re.search(r"\b(infect|toxic \d+|poison counters?)\b", text):
            add("counter", "poison", COMMON_COUNTER_LABELS["poison"], source)

        game_aids = [
            (r"\broll (?:a|one|two|three|\d+) d20\b", "d20", "W20"),
            (r"\broll (?:a|one|two|three|\d+) d6\b", "d6", "W6"),
            (r"\bflip (?:a|one|two|three|\d+) coins?\b", "coin", "Münze"),
            (r"\bventure into the dungeon\b|\benter the dungeon\b", "dungeon", "Dungeon-Karten"),
            (r"\btake the initiative\b|\bthe initiative\b", "initiative", "Initiative-Hilfskarte"),
            (r"\btake the initiative\b|\bthe initiative\b", "undercity", "Unterstadt-Dungeon"),
            (r"\bbecome(?:s)? the monarch\b|\bthe monarch\b", "monarch", "Monarch-Hilfskarte"),
            (r"\bbecomes? day\b|\bbecomes? night\b|\bdaybound\b|\bnightbound\b", "day-night", "Tag/Nacht-Hilfskarte"),
            (r"\bthe ring tempts you\b", "ring", "Der Ring-Hilfskarte"),
            (r"\bopen an attraction\b|\bvisit an attraction\b", "attraction", "Attraction-Karten"),
            (r"\bsticker(?:s| sheet)?\b", "stickers", "Stickerbögen"),
            (r"\bcity's blessing\b", "citys-blessing", "Segen-der-Stadt-Hilfskarte"),
        ]
        for pattern, key, label in game_aids:
            if re.search(pattern, text):
                add("game_aid", key, label, source)

    category_order = {"ability_counter": 0, "counter": 1, "game_aid": 2}
    result = []
    for item in accessories.values():
        serialized = dict(item)
        serialized["source_names"] = sorted(item["source_names"])
        result.append(serialized)
    return sorted(result, key=lambda item: (category_order.get(item["category"], 9), item["name"].lower()))


@app.get("/api/decks/{deck_id}/status")
def deck_status(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    slots = db.execute(
        """
        SELECT ds.*, c.name, c.image_url, c.type_line, c.is_token
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        ORDER BY CASE ds.zone WHEN 'mainboard' THEN 0 ELSE 1 END, c.name
        """,
        (deck_id,),
    ).fetchall()
    status_rows = []
    token_rows = []
    shopping_list = []
    proxy_list = []
    conflicts = []
    allocation_by_card: dict[int, dict[str, Any]] = {}
    for slot in slots:
        card_id = slot["card_id"]
        if card_id not in allocation_by_card:
            copy_rows = db.execute(
                """
                SELECT cc.*, d.name AS deck_name
                FROM card_copies cc
                LEFT JOIN decks d ON d.id = cc.assigned_deck_id
                WHERE cc.card_id = ?
                """,
                (card_id,),
            ).fetchall()
            allocation_by_card[card_id] = {
                "real_remaining": sum(1 for copy in copy_rows if not copy["is_proxy"] and copy["assigned_deck_id"] == deck_id),
                "proxy_remaining": sum(1 for copy in copy_rows if copy["is_proxy"] and copy["assigned_deck_id"] == deck_id),
                "free_real": sum(1 for copy in copy_rows if not copy["is_proxy"] and copy["assigned_deck_id"] is None),
                "free_proxy": sum(1 for copy in copy_rows if copy["is_proxy"] and copy["assigned_deck_id"] is None),
                "in_other_decks": [dict(copy) for copy in copy_rows if copy["assigned_deck_id"] not in (None, deck_id)],
            }
        allocation = allocation_by_card[card_id]
        free_real = allocation["free_real"]
        free_proxy = allocation["free_proxy"]
        in_other_decks = allocation["in_other_decks"]
        needed = slot["quantity"]
        real_used = min(needed, allocation["real_remaining"])
        allocation["real_remaining"] -= real_used
        remaining = needed - real_used
        proxy_used = min(remaining, allocation["proxy_remaining"]) if slot["allow_proxy"] else 0
        allocation["proxy_remaining"] -= proxy_used
        missing = needed - real_used - proxy_used
        item = {
            "slot_id": slot["id"],
            "card_id": card_id,
            "name": slot["name"],
            "cardmarket_url": cardmarket_url(slot["name"]),
            "quantity": needed,
            "owned": real_used,
            "proxy": proxy_used,
            "missing": missing,
            "free_in_collection": free_real,
            "free_proxy_in_collection": free_proxy,
            "allow_proxy": bool(slot["allow_proxy"]),
            "copies_in_other_decks": len(in_other_decks),
            "other_decks": sorted({copy["deck_name"] for copy in in_other_decks if copy["deck_name"]}),
            "is_token": bool(slot["is_token"]),
            "zone": slot["zone"],
        }
        if slot["is_token"]:
            token_rows.append(item)
            continue
        status_rows.append(item)
        if missing > 0 and slot["allow_proxy"]:
            proxy_list.append(
                {
                    "card_id": card_id,
                    "name": slot["name"],
                    "quantity": missing,
                    "cardmarket_url": cardmarket_url(slot["name"]),
                    "zone": slot["zone"],
                }
            )
        elif missing > 0:
            shopping_list.append(
                {
                    "card_id": card_id,
                    "name": slot["name"],
                    "quantity": missing,
                    "cardmarket_url": cardmarket_url(slot["name"]),
                    "zone": slot["zone"],
                }
            )
        if in_other_decks and missing > 0:
            conflicts.append(item)
    return {
        "deck": dict(deck),
        "cards": status_rows,
        "tokens": token_rows,
        "required_tokens": required_tokens_for_deck(deck_id, db),
        "accessories": accessories_for_deck(deck_id, db),
        "shopping_list": shopping_list,
        "proxy_list": proxy_list,
        "conflicts": conflicts,
    }


@app.get("/api/decks/{deck_id}/shopping-list")
def deck_shopping_list(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    status = deck_status(deck_id, db)
    return {
        "deck": status["deck"],
        "shopping_list": status["shopping_list"],
        "proxy_list": status["proxy_list"],
        "conflicts": status["conflicts"],
    }


@app.get("/api/decks/{deck_id}/cardmarket-wants")
def deck_cardmarket_wants(
    deck_id: int,
    include_proxy_list: bool = False,
    db: sqlite3.Connection = Depends(db_dep),
) -> dict[str, Any]:
    status = deck_status(deck_id, db)
    items = list(status["shopping_list"])
    if include_proxy_list:
        items.extend(status["proxy_list"])

    merged: dict[int, dict[str, Any]] = {}
    for item in items:
        entry = merged.setdefault(
            item["card_id"],
            {
                "card_id": item["card_id"],
                "name": item["name"],
                "quantity": 0,
                "cardmarket_url": item["cardmarket_url"],
            },
        )
        entry["quantity"] += item["quantity"]

    rows = sorted(merged.values(), key=lambda item: item["name"])
    text = "\n".join(f"{item['quantity']} {item['name']}" for item in rows)
    deck_name = re.sub(r"[^A-Za-z0-9_-]+", "-", status["deck"]["name"]).strip("-") or "deck"
    return {
        "deck": status["deck"],
        "items": rows,
        "text": text,
        "filename": f"{deck_name}-cardmarket-wants.txt",
        "format": "Cardmarket import text: one line per card, e.g. '2 Sol Ring'.",
    }


@app.get("/api/planning")
def planning(db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    decks_rows = db.execute("SELECT id, name, format FROM decks ORDER BY name").fetchall()
    missing_by_card: dict[int, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    deck_summaries = []
    for deck in decks_rows:
        status = deck_status(deck["id"], db)
        missing_total = 0
        proxy_total = 0
        conflict_total = len(status["conflicts"])
        for item in status["cards"]:
            missing = item["missing"]
            proxy_total += item["proxy"]
            missing_total += missing
            if missing <= 0:
                continue
            entry = missing_by_card.setdefault(
                item["card_id"],
                {
                    "card_id": item["card_id"],
                    "name": item["name"],
                    "cardmarket_url": item["cardmarket_url"],
                    "quantity": 0,
                    "decks": [],
                    "allow_proxy": item["allow_proxy"],
                },
            )
            entry["quantity"] += missing
            entry["decks"].append({"deck_id": deck["id"], "deck_name": deck["name"], "quantity": missing})
        conflicts.extend(
            {
                "deck_id": deck["id"],
                "deck_name": deck["name"],
                **item,
            }
            for item in status["conflicts"]
        )
        deck_summaries.append(
            {
                "deck_id": deck["id"],
                "deck_name": deck["name"],
                "format": deck["format"],
                "missing_total": missing_total,
                "proxy_total": proxy_total,
                "conflict_total": conflict_total,
            }
        )
    return {
        "missing": sorted(missing_by_card.values(), key=lambda item: item["name"]),
        "conflicts": conflicts,
        "decks": deck_summaries,
    }


LINE_RE = re.compile(r"^\s*(?:(\d+)\s*x?\s+)?(.+?)\s*$", re.IGNORECASE)
SET_SUFFIX_RE = re.compile(r"\s+\([A-Za-z0-9]{2,6}\).*$")


def parse_deck_list(text: str) -> list[tuple[int, str, str]]:
    items: list[tuple[int, str, str]] = []
    headers = {"deck", "mainboard", "commander", "sideboard", "maybeboard", "tokens"}
    zone = "mainboard"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        header = line.lower().rstrip(":")
        if header in headers:
            zone = "sideboard" if header == "sideboard" else "mainboard"
            continue
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        quantity = int(match.group(1) or "1")
        name = SET_SUFFIX_RE.sub("", match.group(2)).strip()
        name = re.sub(r"\s+\d+[a-z]?$", "", name, flags=re.IGNORECASE).strip()
        if name:
            items.append((quantity, name, zone))
    return items


def find_card_by_name(db: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    exact = db.execute("SELECT * FROM cards WHERE lower(name) = lower(?) ORDER BY released_at DESC LIMIT 1", (name,)).fetchone()
    if exact:
        return exact
    return db.execute("SELECT * FROM cards WHERE lower(name) LIKE lower(?) ORDER BY name LIMIT 1", (f"{name}%",)).fetchone()


@app.post("/api/decks/{deck_id}/import-list")
def import_deck_list(deck_id: int, payload: DeckListImport, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    if payload.replace:
        db.execute("UPDATE card_copies SET assigned_deck_id = NULL WHERE assigned_deck_id = ?", (deck_id,))
        db.execute("DELETE FROM deck_slots WHERE deck_id = ?", (deck_id,))
    imported = []
    unresolved = []
    for quantity, name, zone in parse_deck_list(payload.text):
        card = find_card_by_name(db, name)
        if not card:
            unresolved.append({"name": name, "quantity": quantity})
            continue
        db.execute(
            """
            INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy, zone)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(deck_id, card_id, zone) DO UPDATE SET quantity=deck_slots.quantity + excluded.quantity
            """,
            (deck_id, card["id"], quantity, zone),
        )
        imported.append({"card_id": card["id"], "name": card["name"], "quantity": quantity, "zone": zone})
    sync_active_variant_if_not_editing(deck_id, db)
    db.commit()
    return {"imported": imported, "unresolved": unresolved}


@app.get("/api/decks/{deck_id}/export-list")
def export_deck_list(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, str]:
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    rows = db.execute(
        """
        SELECT ds.quantity, ds.zone, c.name, c.is_token
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        ORDER BY c.name
        """,
        (deck_id,),
    ).fetchall()
    cards = [row for row in rows if not row["is_token"] and row["zone"] == "mainboard"]
    sideboard = [row for row in rows if not row["is_token"] and row["zone"] == "sideboard"]
    tokens = [row for row in rows if row["is_token"]]
    sections = ["\n".join(f"{row['quantity']} {row['name']}" for row in cards)]
    if sideboard:
        sections.append("Sideboard\n" + "\n".join(f"{row['quantity']} {row['name']}" for row in sideboard))
    if tokens:
        sections.append("Tokens\n" + "\n".join(f"{row['quantity']} {row['name']}" for row in tokens))
    return {"text": "\n\n".join(section for section in sections if section)}
