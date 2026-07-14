from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
API_KEY_FILE = BASE_DIR / "data" / "openai-api-key.txt"
AI_PROVIDER_FILE = BASE_DIR / "data" / "ai-provider.txt"
OLLAMA_MODEL_FILE = BASE_DIR / "data" / "ollama-model.txt"
OPENAI_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


class AiMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AiContext(BaseModel):
    page: str = "collection"
    deck_id: int | None = None
    deck_name: str | None = None
    collection_search: str | None = None


class AiChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[AiMessage] = Field(default_factory=list, max_length=20)
    context: AiContext = Field(default_factory=AiContext)
    language: Literal["de", "en"] = "de"


class AiAssistantError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def _read_setting(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def configured_provider() -> str:
    provider = os.environ.get("MANAVAULT_AI_PROVIDER", "").strip().lower()
    if not provider:
        provider = _read_setting(AI_PROVIDER_FILE).lower()
    if provider in {"ollama", "openai", "disabled"}:
        return provider
    return "openai" if api_key() else "disabled"


def configured_model(provider: str | None = None) -> str:
    provider = provider or configured_provider()
    if provider == "ollama":
        return (
            os.environ.get("MANAVAULT_OLLAMA_MODEL", "").strip()
            or _read_setting(OLLAMA_MODEL_FILE)
            or DEFAULT_OLLAMA_MODEL
        )
    return os.environ.get("MANAVAULT_OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL


def api_key() -> str | None:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if value:
        return value
    try:
        value = API_KEY_FILE.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def status() -> dict[str, Any]:
    provider = configured_provider()
    configured = provider == "ollama" or (provider == "openai" and bool(api_key()))
    return {"configured": configured, "provider": provider, "model": configured_model(provider) if configured else None}


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _collection_summary(db: sqlite3.Connection) -> dict[str, Any]:
    totals = dict(db.execute(
        """
        SELECT COUNT(DISTINCT c.id) AS catalog_cards,
               COUNT(DISTINCT CASE WHEN cc.id IS NOT NULL THEN c.id END) AS owned_printings,
               COALESCE(SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END), 0) AS originals,
               COALESCE(SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END), 0) AS proxies
        FROM cards c LEFT JOIN card_copies cc ON cc.card_id = c.id
        """
    ).fetchone())
    totals["decks"] = db.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
    totals["top_cards"] = _rows(db.execute(
        """
        SELECT c.name, c.set_code, c.collector_number,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS originals,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxies
        FROM card_copies cc JOIN cards c ON c.id = cc.card_id
        GROUP BY c.id ORDER BY COUNT(cc.id) DESC, c.name LIMIT 15
        """
    ))
    return totals


def _search_cards(db: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    limit = max(1, min(int(args.get("limit") or 10), 20))
    owned_only = args.get("owned_only") is True
    pattern = f"%{query}%"
    owned_clause = "HAVING COUNT(cc.id) > 0" if owned_only else ""
    rows = _rows(db.execute(
        f"""
        SELECT c.id, c.name, c.printed_name, c.set_code, c.set_name, c.collector_number,
               c.lang, c.mana_cost, c.type_line, c.oracle_text, c.rarity, c.color_identity,
               SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS originals,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxies
        FROM cards c LEFT JOIN card_copies cc ON cc.card_id = c.id
        WHERE c.name LIKE ? OR COALESCE(c.printed_name, '') LIKE ?
           OR COALESCE(c.oracle_text, '') LIKE ? OR COALESCE(c.type_line, '') LIKE ?
        GROUP BY c.id {owned_clause}
        ORDER BY COUNT(cc.id) DESC, c.name, c.released_at DESC LIMIT ?
        """,
        (pattern, pattern, pattern, pattern, limit),
    ))
    for row in rows:
        row["color_identity"] = _json(row.get("color_identity"), [])
    return {"query": query, "count": len(rows), "cards": rows}


def _card_details(db: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    card_id, name = args.get("card_id"), str(args.get("name") or "").strip()
    if card_id is not None:
        where, params = "c.id = ?", (int(card_id),)
    elif name:
        where, params = "LOWER(c.name) = LOWER(?) OR LOWER(COALESCE(c.printed_name, '')) = LOWER(?)", (name, name)
    else:
        return {"error": "card_id or name is required"}
    row = db.execute(
        f"""
        SELECT c.*, SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END) AS originals,
               SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END) AS proxies
        FROM cards c LEFT JOIN card_copies cc ON cc.card_id = c.id
        WHERE {where} GROUP BY c.id ORDER BY c.released_at DESC LIMIT 1
        """, params
    ).fetchone()
    if not row:
        return {"error": "Card not found"}
    result = dict(row)
    for field in ("colors", "color_identity", "legalities", "prices_json"):
        result[field] = _json(result.get(field), {} if field in ("legalities", "prices_json") else [])
    result.pop("image_url", None)
    return result


def _list_decks(db: sqlite3.Connection) -> dict[str, Any]:
    return {"decks": _rows(db.execute(
        """
        SELECT d.id, d.name, d.format, d.notes, d.commander_card_id,
               COUNT(ds.id) AS distinct_slots, COALESCE(SUM(ds.quantity), 0) AS cards
        FROM decks d LEFT JOIN deck_slots ds ON ds.deck_id = d.id
        GROUP BY d.id ORDER BY d.name
        """
    ))}


def _deck_details(db: sqlite3.Connection, args: dict[str, Any], context: AiContext) -> dict[str, Any]:
    deck_id = args.get("deck_id") if args.get("deck_id") is not None else context.deck_id
    if deck_id is None:
        return {"error": "No deck is selected"}
    deck = db.execute("SELECT * FROM decks WHERE id = ?", (int(deck_id),)).fetchone()
    if not deck:
        return {"error": "Deck not found"}
    slots = _rows(db.execute(
        """
        SELECT ds.zone AS section, ds.quantity, c.id AS card_id, c.name, c.printed_name,
               c.set_code, c.collector_number, c.lang, c.mana_cost, c.cmc, c.type_line,
               c.oracle_text, c.power, c.toughness, c.colors, c.color_identity, c.rarity,
               COALESCE((SELECT SUM(CASE WHEN cc.is_proxy = 0 THEN 1 ELSE 0 END)
                         FROM card_copies cc WHERE cc.card_id = c.id), 0) AS owned_originals,
               COALESCE((SELECT SUM(CASE WHEN cc.is_proxy = 1 THEN 1 ELSE 0 END)
                         FROM card_copies cc WHERE cc.card_id = c.id), 0) AS owned_proxies
        FROM deck_slots ds JOIN cards c ON c.id = ds.card_id
        WHERE ds.deck_id = ? ORDER BY ds.zone, c.name
        """, (int(deck_id),)
    ))
    for card in slots:
        card["colors"] = _json(card.get("colors"), [])
        card["color_identity"] = _json(card.get("color_identity"), [])
        card["missing"] = max(0, card["quantity"] - card["owned_originals"] - card["owned_proxies"])
    return {"deck": dict(deck), "slots": slots, "slot_count": len(slots)}


def _set_progress(db: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    code = str(args.get("set_code") or "").strip().lower()
    rows = _rows(db.execute(
        """
        SELECT c.id, c.name, c.collector_number, c.rarity, COUNT(cc.id) AS copies
        FROM cards c LEFT JOIN card_copies cc ON cc.card_id = c.id
        WHERE LOWER(c.set_code) = ? AND c.lang = 'en' AND COALESCE(c.is_token, 0) = 0
        GROUP BY c.id ORDER BY CAST(c.collector_number AS INTEGER), c.collector_number
        """, (code,)
    ))
    missing = [{k: r[k] for k in ("id", "name", "collector_number", "rarity")} for r in rows if not r["copies"]]
    return {"set_code": code, "total": len(rows), "owned": len(rows) - len(missing), "missing_count": len(missing), "missing": missing[:100]}


TOOLS = [
    {"type": "function", "name": "get_collection_summary", "description": "Get aggregate counts and the most-owned cards in the user's ManaVault collection.", "strict": True, "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"type": "function", "name": "search_cards", "description": "Search the local Scryfall card catalog and optionally restrict results to owned printings.", "strict": True, "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "owned_only": {"type": ["boolean", "null"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query", "owned_only", "limit"], "additionalProperties": False}},
    {"type": "function", "name": "get_card_details", "description": "Get full local Scryfall details and collection counts for one card printing.", "strict": True, "parameters": {"type": "object", "properties": {"card_id": {"type": ["integer", "null"]}, "name": {"type": ["string", "null"]}}, "required": ["card_id", "name"], "additionalProperties": False}},
    {"type": "function", "name": "list_decks", "description": "List the user's ManaVault decks.", "strict": True, "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"type": "function", "name": "get_deck_details", "description": "Get the selected or requested deck with every card's local Scryfall rules text and owned counts.", "strict": True, "parameters": {"type": "object", "properties": {"deck_id": {"type": ["integer", "null"]}}, "required": ["deck_id"], "additionalProperties": False}},
    {"type": "function", "name": "get_set_progress", "description": "Get owned and missing cards for a set from the local Scryfall catalog.", "strict": True, "parameters": {"type": "object", "properties": {"set_code": {"type": "string"}}, "required": ["set_code"], "additionalProperties": False}},
]


def _dispatch(name: str, args: dict[str, Any], db: sqlite3.Connection, context: AiContext) -> dict[str, Any]:
    handlers = {
        "get_collection_summary": lambda: _collection_summary(db),
        "search_cards": lambda: _search_cards(db, args),
        "get_card_details": lambda: _card_details(db, args),
        "list_decks": lambda: _list_decks(db),
        "get_deck_details": lambda: _deck_details(db, args, context),
        "get_set_progress": lambda: _set_progress(db, args),
    }
    return handlers.get(name, lambda: {"error": f"Unknown tool: {name}"})()


def _openai(payload: dict[str, Any], key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", {}).get("message", detail)
        except ValueError:
            message = detail
        raise AiAssistantError(f"OpenAI: {message}", error.code) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise AiAssistantError("OpenAI ist momentan nicht erreichbar.", 502) from error


def _ollama(payload: dict[str, Any]) -> dict[str, Any]:
    url = os.environ.get("MANAVAULT_OLLAMA_URL", DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", detail)
        except ValueError:
            message = detail
        if error.code == 404:
            message = "Das lokale Modell wurde nicht gefunden. Bitte die lokale KI erneut einrichten."
        raise AiAssistantError(f"Lokale KI: {message}", 502) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise AiAssistantError(
            "Die lokale KI ist nicht erreichbar. Bitte prüfen, ob Ollama läuft.",
            502,
        ) from error


def _ollama_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in TOOLS
    ]


def _compact_local_result(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if name != "get_deck_details" or not isinstance(result.get("slots"), list):
        return result
    compact = dict(result)
    keep = {
        "section", "quantity", "name", "printed_name", "mana_cost", "cmc",
        "type_line", "colors", "color_identity", "owned_originals", "owned_proxies", "missing",
    }
    compact["slots"] = [
        {key: value for key, value in slot.items() if key in keep}
        for slot in result["slots"]
    ]
    return compact


def _answer(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def _instructions(body: AiChatRequest) -> str:
    language = "German" if body.language == "de" else "English"
    context_json = json.dumps(body.context.model_dump(), ensure_ascii=False)
    return (
        "You are the read-only ManaVault assistant for a Magic: The Gathering collection manager. "
        f"Always answer in {language}. Use the provided local tools before making claims about the user's "
        "collection, decks, set completion, or card rules. Local card records originate from the user's "
        "Scryfall bulk import and are the authority for this conversation. Never claim to modify data and never "
        "ask for secrets. Be concise, practical, and clearly label uncertainty. The current UI context is: " + context_json
    )


def _chat_openai(body: AiChatRequest, db: sqlite3.Connection, key: str) -> dict[str, Any]:
    model = configured_model("openai")
    inputs = [
        {"role": message.role, "content": message.content[:4000]}
        for message in body.history[-12:]
    ]
    inputs.append({"role": "user", "content": body.message})
    payload: dict[str, Any] = {
        "model": model, "instructions": _instructions(body), "input": inputs,
        "tools": TOOLS, "store": False,
    }
    used_tools: list[str] = []
    for _ in range(6):
        response = _openai(payload, key)
        calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        if not calls:
            answer = _answer(response)
            if not answer:
                raise AiAssistantError("Der Assistent hat keine Antwort geliefert.", 502)
            return {"answer": answer, "model": model, "provider": "openai", "used_tools": used_tools}
        next_input = list(payload["input"])
        next_input.extend(response.get("output", []))
        for call in calls:
            name = call.get("name", "")
            try:
                args = json.loads(call.get("arguments") or "{}")
                result = _dispatch(name, args, db, body.context)
            except Exception as error:  # Return tool errors to the model instead of aborting the chat.
                result = {"error": str(error)}
            used_tools.append(name)
            next_input.append({
                "type": "function_call_output", "call_id": call.get("call_id"),
                "output": json.dumps(result, ensure_ascii=False, default=str),
            })
        payload["input"] = next_input
    raise AiAssistantError("Die Anfrage benötigte zu viele Datenschritte. Bitte etwas genauer fragen.", 422)


def _chat_ollama(body: AiChatRequest, db: sqlite3.Connection) -> dict[str, Any]:
    model = configured_model("ollama")
    messages: list[dict[str, Any]] = [{"role": "system", "content": _instructions(body)}]
    messages.extend(
        {"role": message.role, "content": message.content[:4000]}
        for message in body.history[-8:]
    )
    messages.append({"role": "user", "content": body.message})
    used_tools: list[str] = []
    for _ in range(6):
        response = _ollama({
            "model": model,
            "messages": messages,
            "tools": _ollama_tools(),
            "stream": False,
            "think": False,
            "keep_alive": os.environ.get("MANAVAULT_OLLAMA_KEEP_ALIVE", "5m"),
            "options": {"num_ctx": 8192},
        })
        message = response.get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            answer = str(message.get("content") or "").strip()
            if not answer:
                raise AiAssistantError("Der lokale Assistent hat keine Antwort geliefert.", 502)
            return {"answer": answer, "model": model, "provider": "ollama", "used_tools": used_tools}
        messages.append({
            "role": "assistant",
            "content": str(message.get("content") or ""),
            "tool_calls": calls,
        })
        for call in calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw_args = function.get("arguments") or {}
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be an object")
                result = _compact_local_result(name, _dispatch(name, args, db, body.context))
            except Exception as error:
                result = {"error": str(error)}
            used_tools.append(name)
            messages.append({
                "role": "tool",
                "tool_name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
    raise AiAssistantError("Die Anfrage benötigte zu viele Datenschritte. Bitte etwas genauer fragen.", 422)


def chat(body: AiChatRequest, db: sqlite3.Connection) -> dict[str, Any]:
    provider = configured_provider()
    if provider == "ollama":
        return _chat_ollama(body, db)
    if provider == "openai":
        key = api_key()
        if not key:
            raise AiAssistantError("Der OpenAI-API-Schlüssel ist noch nicht eingerichtet.", 503)
        return _chat_openai(body, db, key)
    raise AiAssistantError("Der optionale Assistent ist noch nicht eingerichtet.", 503)
