from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import main as core


app = FastAPI(
    title="ManaVault public deck viewer",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def public_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/share/") or request.url.path.startswith("/api/public/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def public_db_dep():
    if not core.DB_PATH.exists():
        raise HTTPException(status_code=503, detail="ManaVault-Datenbank nicht verfuegbar.")
    db = sqlite3.connect(
        f"file:{core.DB_PATH.as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=10,
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    try:
        yield db
    finally:
        db.close()


def public_card(card: dict[str, Any], quantity: int, zone: str = "mainboard") -> dict[str, Any]:
    return {
        "name": card.get("printed_name") or card.get("name") or "Karte",
        "mana_cost": card.get("mana_cost") or "",
        "type_line": card.get("printed_type_line") or card.get("type_line") or "",
        "image_url": card.get("image_url"),
        "set_code": card.get("set_code"),
        "collector_number": card.get("collector_number"),
        "lang": card.get("lang"),
        "is_token": bool(card.get("is_token")),
        "quantity": int(quantity or 0),
        "zone": zone,
    }


@app.get("/api/version")
def version() -> dict[str, str]:
    value = core.VERSION_FILE.read_text(encoding="utf-8").strip() if core.VERSION_FILE.exists() else ""
    return {"version": value}


@app.get("/api/public/decks/{share_token}")
def public_deck(share_token: str, db: sqlite3.Connection = Depends(public_db_dep)) -> dict[str, Any]:
    if not (20 <= len(share_token) <= 128):
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    deck = db.execute(
        """
        SELECT d.id, d.name, d.format, d.notes,
               commander.image_url AS commander_image_url
        FROM decks d
        LEFT JOIN cards commander ON commander.id = d.commander_card_id
        WHERE d.public_share_token = ?
        """,
        (share_token,),
    ).fetchone()
    if not deck:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")

    slot_rows = db.execute(
        """
        SELECT ds.quantity, ds.zone, c.*
        FROM deck_slots ds
        JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ?
        ORDER BY COALESCE(c.is_token, 0), COALESCE(c.printed_name, c.name)
        """,
        (deck["id"],),
    ).fetchall()

    cards: list[dict[str, Any]] = []
    colors: set[str] = set()
    deck_value = 0.0
    for row in slot_rows:
        card = core.card_row(row)
        cards.append(public_card(card, row["quantity"], row["zone"]))
        if card.get("is_token"):
            continue
        identity = card.get("color_identity") or card.get("colors") or []
        colors.update(color for color in identity if color in {"W", "U", "B", "R", "G"})
        price, _source = core.card_price_eur_with_fallback(db, card)
        deck_value += price * int(row["quantity"] or 0)

    required_tokens = []
    for token in core.required_tokens_for_deck(int(deck["id"]), db):
        required_tokens.append(
            {
                key: token.get(key)
                for key in (
                    "name",
                    "type_line",
                    "image_url",
                    "set_code",
                    "collector_number",
                    "lang",
                    "source_names",
                    "suggested_quantity",
                    "originals",
                    "proxies",
                    "missing",
                )
            }
        )

    return {
        "deck": {
            "name": deck["name"],
            "format": deck["format"],
            "notes": deck["notes"],
        },
        "overview": {
            "commander_image_url": deck["commander_image_url"],
            "colors": sorted(colors),
            "deck_list_value_eur": round(deck_value, 2),
        },
        "cards": cards,
        "required_tokens": required_tokens,
        "accessories": core.accessories_for_deck(int(deck["id"]), db),
    }


@app.get("/share/{share_token}")
def share_page(share_token: str) -> FileResponse:
    if not (20 <= len(share_token) <= 128):
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    return FileResponse(core.FRONTEND_DIR / "index.html")


if core.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=core.FRONTEND_DIR), name="static")
