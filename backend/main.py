from __future__ import annotations

import json
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "manavault.sqlite3"
BACKUP_DIR = DATA_DIR / "backups"
FRONTEND_DIR = BASE_DIR / "frontend"
SCRYFALL_BULK_URL = "https://api.scryfall.com/bulk-data"
USER_AGENT = "ManaVault/0.1 (local collection manager; no api keys)"
CARDMARKET_SEARCH_URL = "https://www.cardmarket.com/en/Magic/Products/Search?searchString="
SCRYFALL_BULK_TYPE = "all_cards"
SCRYFALL_IMPORT_LOCK = Lock()
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


class DeckAddCardIn(BaseModel):
    card_id: int
    quantity: int = 1
    action: str = "auto"
    copy_id: int | None = None
    allow_proxy: bool = True


class DeckAssignFreeIn(BaseModel):
    card_id: int | None = None


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
                prices_json TEXT
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
                notes TEXT
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

            CREATE TABLE IF NOT EXISTS deck_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 1,
                allow_proxy INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                UNIQUE(deck_id, card_id)
            );

            CREATE TABLE IF NOT EXISTS card_tags (
                card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
                auto_tags TEXT NOT NULL DEFAULT '[]',
                manual_tags TEXT NOT NULL DEFAULT '[]',
                rejected_auto_tags TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
            CREATE INDEX IF NOT EXISTS idx_cards_printed_name ON cards(printed_name);
            CREATE INDEX IF NOT EXISTS idx_cards_lang ON cards(lang);
            CREATE INDEX IF NOT EXISTS idx_cards_rarity ON cards(rarity);
            CREATE INDEX IF NOT EXISTS idx_cards_oracle_id ON cards(oracle_id);
            CREATE INDEX IF NOT EXISTS idx_copies_card ON card_copies(card_id);
            CREATE INDEX IF NOT EXISTS idx_copies_deck ON card_copies(assigned_deck_id);
            CREATE INDEX IF NOT EXISTS idx_slots_deck ON deck_slots(deck_id);
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
        ]:
            if column_name not in existing_columns:
                db.execute(f"ALTER TABLE cards ADD COLUMN {column_name} {column_type}")
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


def json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
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
    oracle_id = card.get("oracle_id")
    if not oracle_id:
        return 0.0, "missing"
    same_set = db.execute(
        """
        SELECT prices_json
        FROM cards
        WHERE oracle_id = ? AND lang = 'en' AND lower(set_code) = lower(?)
        ORDER BY released_at DESC
        """,
        (oracle_id, card.get("set_code") or ""),
    ).fetchall()
    for row in same_set:
        price = card_price_eur(json_load(row["prices_json"], {}))
        if price > 0:
            return price, "english_same_set"
    english_prints = db.execute(
        """
        SELECT prices_json
        FROM cards
        WHERE oracle_id = ? AND lang = 'en'
        ORDER BY released_at DESC
        """,
        (oracle_id,),
    ).fetchall()
    for row in english_prints:
        price = card_price_eur(json_load(row["prices_json"], {}))
        if price > 0:
            return price, "english_oracle"
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


def upsert_cards(db: sqlite3.Connection, cards: list[dict[str, Any]]) -> int:
    rows = []
    tag_sources = []
    for card in cards:
        if card.get("object") != "card" or not card.get("id") or not card.get("name"):
            continue
        image_url, mana_cost, oracle_text = card_identity(card)
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
            )
        )
        tag_sources.append((card.get("id"), card.get("type_line"), oracle_text))
    db.executemany(
        """
        INSERT INTO cards (
            scryfall_id, oracle_id, name, printed_name, lang, released_at, mana_cost, cmc,
            type_line, printed_type_line, oracle_text, printed_text, power, toughness, loyalty, colors,
            color_identity, legalities, set_code, set_name, collector_number,
            rarity, image_url, prices_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            prices_json=excluded.prices_json
        """,
        rows,
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
) -> dict[str, Any]:
    set_scryfall_import_status(phase="prepare", message="Import wird vorbereitet.", error=None)
    init_db()
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
    set_scryfall_import_status(phase="done", message=f"{imported} Karten importiert.", imported=imported)
    return {"imported": imported, "source": str(source)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


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
    params.extend([safe_limit, safe_offset])
    rows = db.execute(
        f"""
        SELECT c.*,
               COUNT(cc.id) AS total_count,
               COALESCE(SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END), 0) AS owned_count,
               COALESCE(SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END), 0) AS proxy_count,
               COALESCE(SUM(CASE WHEN cc.assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_count,
               COALESCE(SUM(CASE WHEN cc.is_proxy = 0 AND cc.assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_original_count,
               COALESCE(SUM(CASE WHEN cc.is_proxy = 1 AND cc.assigned_deck_id IS NULL THEN 1 ELSE 0 END), 0) AS free_proxy_count,
               COALESCE(SUM(CASE WHEN cc.assigned_deck_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS deck_count
        FROM cards c
        LEFT JOIN card_copies cc ON cc.card_id = c.id
        {where}
        GROUP BY c.id
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    result = []
    for row in rows:
        card = card_row(row)
        price_eur, price_source = card_price_eur_with_fallback(db, card)
        card["price_eur"] = price_eur
        card["price_source"] = price_source
        if min_price_eur is not None and card.get("price_eur", 0) < min_price_eur:
            continue
        tags = readonly_card_tags(db, row["id"], row["type_line"], row["oracle_text"])
        card["tags"] = tags["tags"]
        result.append(card)
    return result


def run_scryfall_import(payload: ImportRequest) -> None:
    try:
        result = import_scryfall_data(payload.local_file, payload.limit, payload.bulk_type)
        set_scryfall_import_status(
            running=False,
            phase="done",
            message=f"{result['imported']} Karten importiert.",
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
    selected_langs = [lang.strip().lower() for lang in langs.split(",") if lang.strip().lower() in {"en", "de"}]
    if not selected_langs:
        selected_langs = ["en", "de"]
    placeholders = ",".join("?" for _ in selected_langs)
    conditions.append(f"c.lang IN ({placeholders})")
    params.extend(selected_langs)
    query = q.strip().lower()
    if query:
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
        conditions.append("c.legalities LIKE ?")
        params.append(f'%"{legal_key}":"legal"%')
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
    if query and sort == "name":
        order = f"CASE WHEN lower(c.name) LIKE ? OR lower(COALESCE(c.printed_name, '')) LIKE ? THEN 0 ELSE 1 END, {order}"
        params.append(f"{query}%")
        params.append(f"{query}%")
    return conditions, params, order


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
    db: sqlite3.Connection = Depends(db_dep),
) -> list[dict[str, Any]]:
    conditions, params, order = card_filter_sql(q, colors, cmc_min, cmc_max, card_type, tag, legal_format, rarity, set_code, langs, sort)
    where = f"AND {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(
        f"""
        SELECT c.id, c.name, c.printed_name, c.lang, c.mana_cost, c.type_line, c.printed_type_line,
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
    return sort_collection_items(items, sort)[:500]


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
                 ELSE COALESCE(l.name, 'Ohne Ort')
               END AS place_name,
               CASE
                 WHEN cc.assigned_deck_id IS NOT NULL THEN 'Deck'
                 ELSE COALESCE(l.type, 'Sammlung')
               END AS place_type,
               cc.is_proxy,
               COUNT(*) AS quantity
        FROM card_copies cc
        LEFT JOIN locations l ON l.id = cc.location_id
        LEFT JOIN decks d ON d.id = cc.assigned_deck_id
        WHERE cc.card_id = ?
        GROUP BY state, place_name, place_type, cc.is_proxy
        ORDER BY state, place_name
        """,
        (card_id,),
    ).fetchall()
    places_data = [dict(row) for row in places]
    places_data.extend(planned_rows_for_card(db, card_id))
    return {
        "card": card_row(card),
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
        SELECT d.*, c.name AS commander_name,
               COALESCE(SUM(ds.quantity), 0) AS slot_quantity
        FROM decks d
        LEFT JOIN cards c ON c.id = d.commander_card_id
        LEFT JOIN deck_slots ds ON ds.deck_id = d.id
        GROUP BY d.id
        ORDER BY d.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


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
    db.commit()
    return {"id": deck_id, "updated": True}


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
        SELECT ds.*, c.name, c.mana_cost, c.type_line, c.image_url
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        ORDER BY c.name
        """,
        (deck_id,),
    ).fetchall()
    return {"deck": dict(deck), "slots": [dict(row) for row in slots]}


@app.post("/api/decks/{deck_id}/slots")
def add_slot(deck_id: int, payload: DeckSlotIn, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    if payload.quantity < 1:
        raise HTTPException(status_code=400, detail="quantity muss mindestens 1 sein.")
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    card = db.execute("SELECT id FROM cards WHERE id = ?", (payload.card_id,)).fetchone()
    if not deck or not card:
        raise HTTPException(status_code=404, detail="Deck oder Karte nicht gefunden.")
    cur = db.execute(
        """
        INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(deck_id, card_id) DO UPDATE SET
            quantity=excluded.quantity,
            allow_proxy=excluded.allow_proxy,
            note=excluded.note
        """,
        (deck_id, payload.card_id, payload.quantity, int(payload.allow_proxy), payload.note),
    )
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
) -> None:
    db.execute(
        """
        INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(deck_id, card_id) DO UPDATE SET
            quantity=deck_slots.quantity + excluded.quantity,
            allow_proxy=excluded.allow_proxy
        """,
        (deck_id, card_id, quantity_delta, int(allow_proxy)),
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

    elif action == "plan":
        pass

    else:
        raise HTTPException(status_code=400, detail="Unbekannte action.")

    upsert_deck_slot(db, deck_id, payload.card_id, payload.quantity, payload.allow_proxy)
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
    slot_params: list[Any] = [deck_id]
    card_filter = ""
    if payload.card_id is not None:
        card_filter = "AND ds.card_id = ?"
        slot_params.append(payload.card_id)
    slots = db.execute(
        f"""
        SELECT ds.*, c.name
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        {card_filter}
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
    cur = db.execute("DELETE FROM deck_slots WHERE id = ? AND deck_id = ?", (slot_id, deck_id))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Slot nicht gefunden.")
    return {"deleted": True}


@app.get("/api/decks/{deck_id}/status")
def deck_status(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, Any]:
    deck = db.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    slots = db.execute(
        """
        SELECT ds.*, c.name, c.image_url, c.type_line
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        ORDER BY c.name
        """,
        (deck_id,),
    ).fetchall()
    status_rows = []
    shopping_list = []
    proxy_list = []
    conflicts = []
    for slot in slots:
        card_id = slot["card_id"]
        copy_rows = db.execute(
            """
            SELECT cc.*, d.name AS deck_name
            FROM card_copies cc
            LEFT JOIN decks d ON d.id = cc.assigned_deck_id
            WHERE cc.card_id = ?
            """,
            (card_id,),
        ).fetchall()
        real_assigned = sum(1 for copy in copy_rows if not copy["is_proxy"] and copy["assigned_deck_id"] == deck_id)
        proxy_assigned = sum(1 for copy in copy_rows if copy["is_proxy"] and copy["assigned_deck_id"] == deck_id)
        free_real = sum(1 for copy in copy_rows if not copy["is_proxy"] and copy["assigned_deck_id"] is None)
        free_proxy = sum(1 for copy in copy_rows if copy["is_proxy"] and copy["assigned_deck_id"] is None)
        in_other_decks = [dict(copy) for copy in copy_rows if copy["assigned_deck_id"] not in (None, deck_id)]
        needed = slot["quantity"]
        real_used = min(needed, real_assigned)
        remaining = needed - real_used
        proxy_used = min(remaining, proxy_assigned) if slot["allow_proxy"] else 0
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
        }
        status_rows.append(item)
        if missing > 0 and slot["allow_proxy"]:
            proxy_list.append(
                {
                    "card_id": card_id,
                    "name": slot["name"],
                    "quantity": missing,
                    "cardmarket_url": cardmarket_url(slot["name"]),
                }
            )
        elif missing > 0:
            shopping_list.append(
                {
                    "card_id": card_id,
                    "name": slot["name"],
                    "quantity": missing,
                    "cardmarket_url": cardmarket_url(slot["name"]),
                }
            )
        if in_other_decks and missing > 0:
            conflicts.append(item)
    return {
        "deck": dict(deck),
        "cards": status_rows,
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


def parse_deck_list(text: str) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    ignored_headers = {"deck", "commander", "sideboard", "maybeboard"}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.lower().rstrip(":") in ignored_headers:
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        quantity = int(match.group(1) or "1")
        name = SET_SUFFIX_RE.sub("", match.group(2)).strip()
        name = re.sub(r"\s+\d+[a-z]?$", "", name, flags=re.IGNORECASE).strip()
        if name:
            items.append((quantity, name))
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
        db.execute("DELETE FROM deck_slots WHERE deck_id = ?", (deck_id,))
    imported = []
    unresolved = []
    for quantity, name in parse_deck_list(payload.text):
        card = find_card_by_name(db, name)
        if not card:
            unresolved.append({"name": name, "quantity": quantity})
            continue
        db.execute(
            """
            INSERT INTO deck_slots (deck_id, card_id, quantity, allow_proxy)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(deck_id, card_id) DO UPDATE SET quantity=deck_slots.quantity + excluded.quantity
            """,
            (deck_id, card["id"], quantity),
        )
        imported.append({"card_id": card["id"], "name": card["name"], "quantity": quantity})
    db.commit()
    return {"imported": imported, "unresolved": unresolved}


@app.get("/api/decks/{deck_id}/export-list")
def export_deck_list(deck_id: int, db: sqlite3.Connection = Depends(db_dep)) -> dict[str, str]:
    deck = db.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck nicht gefunden.")
    rows = db.execute(
        """
        SELECT ds.quantity, c.name
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        ORDER BY c.name
        """,
        (deck_id,),
    ).fetchall()
    return {"text": "\n".join(f"{row['quantity']} {row['name']}" for row in rows)}
