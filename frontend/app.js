const state = {
  collection: [],
  globalCards: [],
  globalOffset: 0,
  globalHasMore: true,
  globalPageSize: 120,
  collectionOffset: 0,
  collectionHasMore: true,
  collectionPageSize: 120,
  tagCatalog: [],
  setCatalog: [],
  planning: null,
  collectionStats: null,
  locations: [],
  decks: [],
  selectedDeckId: null,
  activePage: "collectionPage",
  pendingCardId: null,
  pendingDeleteLocationId: null,
  importStatusTimer: null,
  importWasRunning: false,
  importStatusHideTimer: null,
};

const $ = (id) => document.getElementById(id);
const SYMBOL_BASE = "https://svgs.scryfall.io/card-symbols";
const MANA_SYMBOLS = {
  W: `${SYMBOL_BASE}/W.svg`,
  U: `${SYMBOL_BASE}/U.svg`,
  B: `${SYMBOL_BASE}/B.svg`,
  R: `${SYMBOL_BASE}/R.svg`,
  G: `${SYMBOL_BASE}/G.svg`,
  C: `${SYMBOL_BASE}/C.svg`,
};
const rarityLabels = {
  common: "Common",
  uncommon: "Uncommon",
  rare: "Rare",
  mythic: "Mythic",
  special: "Special",
  bonus: "Bonus",
  unknown: "Unbekannt",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

async function apiText(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.text();
}

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.style.display = "block";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    box.style.display = "none";
  }, 3600);
}

async function withActionButton(event, task) {
  const button = event?.currentTarget;
  if (button) {
    button.disabled = true;
    button.classList.add("is-busy");
  }
  try {
    return await task();
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("is-busy");
    }
  }
}

function scheduleDeckRefresh() {
  debounce(loadDeck, 120);
}

function schedulePlanningRefresh() {
  debounce(loadPlanning, 250);
}

function downloadTextFile(text, filename, mimeType) {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function displayName(card) {
  return card.printed_name || card.name || card.card_name || "";
}

function displayType(card) {
  return card.printed_type_line || card.type_line || "";
}

function oracleNameHint(card) {
  if (!card.printed_name || card.printed_name === card.name) return "";
  return `<small>${escapeHtml(card.name)} - ${escapeHtml((card.lang || "").toUpperCase())}</small>`;
}

function debounce(fn, delay = 220) {
  clearTimeout(fn.timer);
  fn.timer = setTimeout(fn, delay);
}

function scheduleCollectionLoad() {
  loadCollection(true);
}

function selectedDeckId() {
  const value = Number($("deckSelect").value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

async function init() {
  wireEvents();
  await refreshBasics();
  await Promise.all([loadCollection(), loadDecks(), loadPlanning()]);
  await loadDeck();
  await refreshImportStatus();
}

function wireEvents() {
  setupStaticIconButtons();
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.page));
  });

  $("collectionSearch").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionSearchAllCards").addEventListener("change", () => loadCollection(true));
  document.querySelectorAll(".collectionManaFilter").forEach((button) => {
    const color = button.dataset.color;
    button.innerHTML = `<img src="${MANA_SYMBOLS[color]}" alt="${color}">`;
    button.addEventListener("click", () => {
      button.classList.toggle("active");
      loadCollection(true);
    });
  });
  $("collectionCmcMin").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionCmcMax").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionTypeFilter").addEventListener("change", () => loadCollection(true));
  $("collectionTagFilter").addEventListener("change", () => loadCollection(true));
  $("collectionLegalFilter").addEventListener("change", () => loadCollection(true));
  $("collectionRarityFilter").addEventListener("change", () => loadCollection(true));
  $("collectionSetFilter").addEventListener("change", () => loadCollection(true));
  $("collectionMinPrice").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionSort").addEventListener("change", () => loadCollection(true));
  $("exportCollection").addEventListener("click", exportCollection);
  $("collectionLoadMore").addEventListener("click", () => loadCollection(false));
  $("clearCollectionFilters").addEventListener("click", () => {
    $("collectionSearch").value = "";
    $("collectionCmcMin").value = "";
    $("collectionCmcMax").value = "";
    $("collectionTypeFilter").value = "";
    $("collectionTagFilter").value = "";
    $("collectionLegalFilter").value = "";
    $("collectionRarityFilter").value = "";
    $("collectionSetFilter").value = "";
    $("collectionMinPrice").value = "";
    $("collectionSort").value = "name";
    $("collectionSearchAllCards").checked = false;
    document.querySelectorAll(".collectionManaFilter").forEach((button) => button.classList.remove("active"));
    loadCollection(true);
  });

  $("deckSelect").addEventListener("change", async () => {
    state.selectedDeckId = selectedDeckId();
    await loadDeck();
  });

  $("deckForm").addEventListener("submit", createDeckFromForm);
  $("openDeckBuilder").addEventListener("click", openDeckBuilder);
  $("newDeckFromBuilder").addEventListener("click", createDeckQuick);
  $("locationForm").addEventListener("submit", createLocation);
  $("importDeck").addEventListener("click", importDeckList);
  $("exportDeck").addEventListener("click", exportDeck);
  $("refreshPlanning").addEventListener("click", loadPlanning);
  $("refreshStats").addEventListener("click", loadCollectionStats);
  $("downloadBackup").addEventListener("click", downloadBackup);
  $("importBackup").addEventListener("click", importBackup);

  $("importScryfall").addEventListener("click", importScryfall);
}

function setImportStatus(status) {
  const box = $("importStatus");
  const text = $("importStatusText");
  if (!box || !text) return;
  const visible = status.running || status.phase === "done" || status.phase === "error";
  clearTimeout(state.importStatusHideTimer);
  box.hidden = !visible;
  box.classList.toggle("running", Boolean(status.running));
  box.classList.toggle("done", status.phase === "done");
  box.classList.toggle("error", status.phase === "error");
  text.textContent = status.error ? `${status.message} ${status.error}` : status.message;
  if (status.phase === "done" && !status.running) {
    state.importStatusHideTimer = setTimeout(() => {
      box.hidden = true;
    }, 9000);
  }
}

async function refreshImportStatus() {
  const status = await api("/api/cards/import-scryfall/status");
  const wasRunning = state.importWasRunning;
  setImportStatus(status);
  $("importScryfall").disabled = Boolean(status.running);
  $("importScryfall").classList.toggle("is-busy", Boolean(status.running));
  if (status.running && !state.importStatusTimer) {
    state.importStatusTimer = setInterval(refreshImportStatus, 1500);
  }
  if (!status.running && state.importStatusTimer) {
    clearInterval(state.importStatusTimer);
    state.importStatusTimer = null;
  }
  if (wasRunning && !status.running && status.phase === "done") {
    toast(`${status.imported} Karten importiert.`);
    await loadCollection(true);
  }
  if (wasRunning && !status.running && status.phase === "error") {
    toast(status.error || "Scryfall Import fehlgeschlagen.");
  }
  state.importWasRunning = Boolean(status.running);
  return status;
}

async function importScryfall(event) {
  toast("Scryfall Import gestartet.");
  setImportStatus({ running: true, phase: "start", message: "Scryfall Import startet." });
  if (!state.importStatusTimer) {
    state.importStatusTimer = setInterval(refreshImportStatus, 1500);
  }
  try {
    await withActionButton(event, async () => {
      await api("/api/cards/import-scryfall", {
        method: "POST",
        body: JSON.stringify({}),
      });
      await refreshImportStatus();
    });
  } catch (error) {
    toast(error.message);
    await refreshImportStatus().catch(() => {});
  }
}

function setIconButton(id, icon, label) {
  const button = $(id);
  if (!button) return;
  button.classList.add("icon-button");
  button.innerHTML = iconSvg(icon);
  button.title = label;
  button.setAttribute("aria-label", label);
}

function setupStaticIconButtons() {
  setIconButton("importScryfall", "databaseImport", "Scryfall Import");
  setIconButton("exportCollection", "download", "Sammlung exportieren");
  setIconButton("openDeckBuilder", "deck", "Deckbuilder oeffnen");
  setIconButton("newDeckFromBuilder", "newDeck", "Deck erstellen");
  setIconButton("exportDeck", "download", "Deck exportieren");
  setIconButton("importDeck", "upload", "Liste uebernehmen");
  setIconButton("refreshPlanning", "refresh", "Aktualisieren");
  setIconButton("refreshStats", "refresh", "Aktualisieren");
  setIconButton("downloadBackup", "download", "Backup exportieren");
  setIconButton("importBackup", "upload", "Backup importieren");
  const scopeToggleIcon = document.querySelector(".scope-toggle-icon");
  if (scopeToggleIcon) scopeToggleIcon.innerHTML = iconSvg("allCards");
}

function showPage(pageId) {
  state.activePage = pageId;
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === pageId));
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.page === pageId));
  if (pageId === "statsPage") loadCollectionStats();
}

async function refreshBasics() {
  const [locations, decks, tagCatalog, setCatalog] = await Promise.all([api("/api/locations"), api("/api/decks"), api("/api/tags/catalog"), api("/api/sets/catalog")]);
  state.locations = locations;
  state.decks = decks;
  state.tagCatalog = tagCatalog;
  state.setCatalog = setCatalog;
  if (!state.selectedDeckId && decks.length) {
    state.selectedDeckId = decks[0].id;
  }
  renderDeckSelect();
  renderLocations();
  renderTagFilter();
  renderSetFilter();
}

function renderTagFilter() {
  const collectionCurrent = $("collectionTagFilter").value;
  $("collectionTagFilter").innerHTML = `<option value="">Alle Tags</option>${state.tagCatalog.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join("")}`;
  $("collectionTagFilter").value = collectionCurrent;
}

function renderSetFilter() {
  const collectionCurrent = $("collectionSetFilter").value;
  $("collectionSetFilter").innerHTML = `<option value="">Alle Sets</option>${state.setCatalog.map((set) => {
    const code = String(set.code || "").toUpperCase();
    const name = set.name || code;
    const count = Number(set.card_count || 0);
    return `<option value="${escapeHtml(set.code)}">${escapeHtml(code)} - ${escapeHtml(name)} (${count})</option>`;
  }).join("")}`;
  $("collectionSetFilter").value = collectionCurrent;
}

function renderDeckSelect() {
  $("deckSelect").innerHTML = state.decks.map((deck) => (
    `<option value="${deck.id}">${escapeHtml(deck.name)} (${escapeHtml(deck.format || "")})</option>`
  )).join("");
  if (state.selectedDeckId) {
    $("deckSelect").value = state.selectedDeckId;
  }
}

function collectionSearchParams() {
  const params = new URLSearchParams();
  const colors = [...document.querySelectorAll(".collectionManaFilter.active")].map((button) => button.dataset.color);
  params.set("q", $("collectionSearch").value.trim());
  params.set("colors", colors.join(","));
  if ($("collectionCmcMin").value !== "") params.set("cmc_min", $("collectionCmcMin").value);
  if ($("collectionCmcMax").value !== "") params.set("cmc_max", $("collectionCmcMax").value);
  if ($("collectionTypeFilter").value) params.set("card_type", $("collectionTypeFilter").value);
  if ($("collectionTagFilter").value) params.set("tag", $("collectionTagFilter").value);
  if ($("collectionLegalFilter").value) params.set("legal_format", $("collectionLegalFilter").value);
  if ($("collectionRarityFilter").value) params.set("rarity", $("collectionRarityFilter").value);
  if ($("collectionSetFilter").value) params.set("set_code", $("collectionSetFilter").value);
  if ($("collectionMinPrice").value !== "") params.set("min_price_eur", $("collectionMinPrice").value);
  params.set("sort", $("collectionSort").value);
  return params;
}

function allCardsSortValue(sort) {
  const supported = new Set(["name", "name_desc", "cmc", "cmc_desc", "price", "price_asc", "rarity", "rarity_asc", "set", "released"]);
  return supported.has(sort) ? sort : "name";
}

async function loadCollection(reset = true) {
  const allCardsMode = $("collectionSearchAllCards").checked;
  if (allCardsMode) {
    if (reset) {
      state.collection = [];
      state.collectionOffset = 0;
      state.collectionHasMore = true;
    }
    if (!state.collectionHasMore) return;
    const params = collectionSearchParams();
    params.set("sort", allCardsSortValue($("collectionSort").value));
    params.set("limit", String(state.collectionPageSize));
    params.set("offset", String(state.collectionOffset));
    const cards = await api(`/api/cards/search?${params.toString()}`);
    state.collection = reset ? cards : [...state.collection, ...cards];
    state.collectionOffset += cards.length;
    state.collectionHasMore = cards.length === state.collectionPageSize;
  } else {
    const params = collectionSearchParams();
    state.collection = await api(`/api/collection/summary?${params.toString()}`);
    state.collectionHasMore = false;
    state.collectionOffset = state.collection.length;
  }
  renderCollection();
}

function renderCollection() {
  const allCardsMode = $("collectionSearchAllCards").checked;
  $("collectionSearch").placeholder = allCardsMode ? "Alle Karten suchen..." : "Sammlung suchen...";
  $("collectionExportFormat").style.display = allCardsMode ? "none" : "";
  $("exportCollection").style.display = allCardsMode ? "none" : "inline-flex";
  $("collectionGrid").innerHTML = state.collection.map((card) => cardTile(card, {
    count: card.total_count,
    subCount: card.set_code ? `${card.set_code} #${card.collector_number || ""}` : "",
    source: allCardsMode ? "global" : "collection",
  })).join("") || emptyState(allCardsMode ? "Keine Karten gefunden. Falls leer: Scryfall importieren." : "Noch keine Karten in deiner Sammlung.");
  $("collectionMeta").textContent = allCardsMode
    ? `${state.collection.length} Karten aus Scryfall angezeigt`
    : `${state.collection.length} Karten in deiner Ansicht`;
  $("collectionLoadMore").style.display = allCardsMode && state.collectionHasMore ? "block" : "none";
}

async function loadCollectionStats() {
  state.collectionStats = await api("/api/collection/stats");
  renderCollectionStats();
}

function statCard(label, value, note = "") {
  return `
    <article class="stat-card">
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(label)}</span>
      ${note ? `<small>${escapeHtml(note)}</small>` : ""}
    </article>
  `;
}

function statBars(items, total) {
  const safeTotal = Math.max(1, total || 0);
  return items.map((item) => {
    const percent = Math.round((Number(item.value || 0) / safeTotal) * 100);
    return `
      <div class="stat-bar-row">
        <span>${item.icon || ""}${escapeHtml(item.label)}</span>
        <div class="stat-bar"><i style="width: ${percent}%"></i></div>
        <strong>${Number(item.value || 0)}</strong>
      </div>
    `;
  }).join("");
}

function renderCollectionStats() {
  const stats = state.collectionStats;
  if (!stats) return;
  const colors = [
    ["W", "Weiss"], ["U", "Blau"], ["B", "Schwarz"], ["R", "Rot"], ["G", "Gruen"], ["C", "Farblos"],
  ].map(([color, label]) => ({
    label,
    value: stats.color_counts[color] || 0,
    icon: color === "C" ? "" : `<img class="inline-mana" src="${MANA_SYMBOLS[color]}" alt="">`,
  }));
  const rarities = Object.entries(stats.rarity_counts || {}).map(([rarity, value]) => ({
    label: rarityLabels[rarity] || rarity,
    value,
  }));
  const groupLabels = { colorless: "Farblos", mono: "Einfarbig", multi: "Mehrfarbig" };
  const colorGroups = Object.entries(stats.color_groups || {}).map(([group, value]) => ({
    label: groupLabels[group] || group,
    value,
  }));
  $("collectionStats").innerHTML = `
    <div class="stat-grid">
      ${statCard("Copies gesamt", stats.total_copies)}
      ${statCard("Unterschiedliche Drucke", stats.unique_prints)}
      ${statCard("Originale", stats.original_copies)}
      ${statCard("Proxies", stats.proxy_copies)}
      ${statCard("Sammlungswert", formatEuro(stats.total_value_eur), `${stats.priced_originals} Originale mit Preis`)}
      ${statCard("Preis-Fallback", stats.fallback_priced_originals, "ueber englische Preise")}
    </div>
    <div class="stats-columns">
      <section class="stats-panel">
        <h3>Farben</h3>
        ${statBars(colors, stats.total_copies)}
      </section>
      <section class="stats-panel">
        <h3>Farbstruktur</h3>
        ${statBars(colorGroups, stats.total_copies)}
      </section>
      <section class="stats-panel">
        <h3>Seltenheit</h3>
        ${statBars(rarities, stats.total_copies)}
      </section>
    </div>
    <section class="stats-panel">
      <h3>Hoechster Sammlungswert</h3>
      <div class="stat-top-list">
        ${(stats.top_value_cards || []).map((card) => `
          <div class="stat-top-row">
            <span>${escapeHtml(card.name)} <small>${escapeHtml((card.set_code || "").toUpperCase())}</small></span>
            <strong>${formatEuro(card.value_eur)}</strong>
          </div>
        `).join("") || emptyState("Noch keine Karten mit Wert gefunden.")}
      </div>
    </section>
  `;
}

function defaultCollectionLocationId() {
  const location = state.locations.find((item) => item.type !== "Deck") || state.locations[0];
  return location?.id ?? null;
}

async function loadPlanning() {
  state.planning = await api("/api/planning");
  renderPlanning();
}

function renderPlanning() {
  const data = state.planning;
  if (!data) return;
  const missingTotal = data.missing.reduce((sum, item) => sum + item.quantity, 0);
  const conflictTotal = data.conflicts.length;
  $("planningSummary").innerHTML = `
    <div class="planning-card">
      <strong>${missingTotal}</strong>
      <span>fehlende/geplante Karten</span>
    </div>
    <div class="planning-card">
      <strong>${conflictTotal}</strong>
      <span>Deckkonflikte</span>
    </div>
    <div class="planning-card">
      <strong>${data.decks.length}</strong>
      <span>Decks beobachtet</span>
    </div>
  `;
  const missing = data.missing.map((item) => `
    <article class="row-card">
      <div>
        <strong>${item.quantity}x ${escapeHtml(item.name)}</strong>
        <span class="muted">${escapeHtml(item.decks.map((deck) => `${deck.quantity}x ${deck.deck_name}`).join(", "))}</span>
      </div>
      <div class="row-actions">
        <a class="button-link" href="${escapeHtml(item.cardmarket_url)}" target="_blank" rel="noopener noreferrer">Cardmarket</a>
        <button onclick="openCardDetail(${item.card_id})">Karte</button>
      </div>
    </article>
  `).join("");
  const conflicts = data.conflicts.map((item) => `
    <article class="row-card conflict-row">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <span class="muted">${escapeHtml(item.deck_name)} braucht ${item.missing} mehr; auch in ${escapeHtml(item.other_decks.join(", "))}</span>
      </div>
      <div class="row-actions">
        <button onclick="openCardDetail(${item.card_id})">Karte</button>
      </div>
    </article>
  `).join("");
  $("planningList").innerHTML = `
    <h3>Fehlt / geplant</h3>
    ${missing || emptyState("Aktuell fehlt nichts. Schoener Zustand.")}
    <h3>Konflikte</h3>
    ${conflicts || emptyState("Keine Konflikte gefunden.")}
  `;
}

function cardTile(card, options) {
  const count = Number(options.count || 0);
  const countBadge = count > 0 ? `<span class="count-badge" title="${count} Copies in ManaVault">${count}x</span>` : "";
  const valueInfo = valueBadge(card, options.source);
  const metaRow = countBadge || valueInfo
    ? `<div class="tile-meta-row">${countBadge || "<span></span>"}<span></span>${valueInfo || "<span></span>"}</div>`
    : "";
  const typeLine = displayType(card);
  const subCount = options.subCount || "";
  const previewAttrs = card.image_url
    ? `onmouseenter="showCardPreview(event, '${escapeHtml(card.image_url)}')" onmousemove="moveCardPreview(event)" onmouseleave="hideCardPreview()"`
    : "";
  return `
    <article class="card-tile" ${previewAttrs}>
      <button class="image-button" onclick="openCardDetail(${card.id})">
        ${card.image_url ? `<img src="${escapeHtml(card.image_url)}" alt="">` : `<span>${escapeHtml(displayName(card))}</span>`}
      </button>
      ${metaRow}
      <div class="tile-body">
        <strong>${escapeHtml(displayName(card))}</strong>
        ${oracleNameHint(card)}
        <span class="mana-cost">${manaCostHtml(card.mana_cost || "")}</span>
        ${typeLine ? `<small>${escapeHtml(typeLine)}</small>` : ""}
        ${subCount ? `<small>${escapeHtml(subCount)}</small>` : ""}
        ${tagChips(card.tags || [], 3)}
      </div>
      <div class="tile-actions">
        <button class="tile-action primary" title="Ins Deck" aria-label="Ins Deck" onclick="addToDeckFlow(${card.id}, event)">${iconSvg("deck")}</button>
        <button class="tile-action secondary" title="Original hinzufuegen" aria-label="Original hinzufuegen" onclick="quickAddCopy(${card.id}, false, event)">${iconSvg("original")}</button>
        <button class="tile-action secondary" title="Proxy hinzufuegen" aria-label="Proxy hinzufuegen" onclick="quickAddCopy(${card.id}, true, event)">${iconSvg("proxy")}</button>
      </div>
    </article>
  `;
}

function iconSvg(name) {
  const icons = {
    deck: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="4" width="11" height="15" rx="2"></rect><path d="M9 2h8a2 2 0 0 1 2 2v12"></path><path d="M9 8h5"></path><path d="M9 12h5"></path></svg>`,
    original: `<span class="action-symbol">O</span><span class="action-plus">+</span>`,
    proxy: `<span class="action-symbol proxy-symbol">P</span><span class="action-plus">+</span>`,
    proxyBadge: `<span class="metric-letter proxy-symbol">P</span>`,
    newDeck: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="4" width="10" height="16" rx="2"></rect><path d="M8 8h4"></path><path d="M8 12h4"></path><path d="M18 8v8"></path><path d="M14 12h8"></path></svg>`,
    open: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12s3-6 8-6 8 6 8 6-3 6-8 6-8-6-8-6Z"></path><circle cx="12" cy="12" r="2.5"></circle></svg>`,
    edit: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path></svg>`,
    delete: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M6 7l1 13h10l1-13"></path><path d="M9 7V4h6v3"></path></svg>`,
    download: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 20h14"></path></svg>`,
    upload: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21V9"></path><path d="m7 14 5-5 5 5"></path><path d="M5 4h14"></path></svg>`,
    databaseImport: `<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v8c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path><path d="M5 9c0 1.7 3.1 3 7 3s7-1.3 7-3"></path><path d="M12 22v-6"></path><path d="m8 18 4 4 4-4"></path></svg>`,
    cart: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="20" r="1.5"></circle><circle cx="18" cy="20" r="1.5"></circle><path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.8a2 2 0 0 0 2-1.6L21 8H7"></path></svg>`,
    refresh: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5"></path><path d="M19.2 11A7.5 7.5 0 1 0 17 17.3"></path></svg>`,
    allCards: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18"></path><path d="M12 3a14 14 0 0 1 0 18"></path><path d="M12 3a14 14 0 0 0 0 18"></path></svg>`,
    check: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"></path></svg>`,
    box: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8 12 4l8 4-8 4-8-4Z"></path><path d="M4 8v8l8 4 8-4V8"></path><path d="M12 12v8"></path></svg>`,
    missing: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v6"></path><path d="M12 17h.01"></path></svg>`,
  };
  return icons[name] || "";
}

function valueBadge(card, source) {
  const price = Number(card.price_eur || 0);
  const total = Number(card.collection_value_eur || 0);
  const priceSource = card.price_source && card.price_source !== "own" ? " ueber englischen Preis" : "";
  if (source === "collection" && total > 0) {
    return `<span class="value-badge" title="Sammlungswert Originale${priceSource}">${formatEuro(total)}</span>`;
  }
  if (source === "global" && price > 0) {
    return `<span class="value-badge" title="Scryfall EUR Preis${priceSource}">${formatEuro(price)}</span>`;
  }
  return "";
}

function formatEuro(value) {
  return `${Number(value).toFixed(2)} EUR`;
}

function tagChips(tags, max = tags.length) {
  const visible = tags.slice(0, max);
  const more = tags.length - visible.length;
  if (!visible.length) return "";
  return `
    <div class="tag-chips">
      ${visible.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
      ${more > 0 ? `<span>+${more}</span>` : ""}
    </div>
  `;
}

function updateGlobalCopyCounts(cardId, counts) {
  const applyCounts = (card) => Object.assign(card, {
    total_count: Number(counts.total_count || 0),
    owned_count: Number(counts.owned_count || 0),
    proxy_count: Number(counts.proxy_count || 0),
    free_count: Number(counts.free_count || 0),
    free_original_count: Number(counts.free_original_count || 0),
    free_proxy_count: Number(counts.free_proxy_count || 0),
    deck_count: Number(counts.deck_count || 0),
  });
  let updated = false;
  [...state.collection, ...state.globalCards].forEach((card) => {
    if (Number(card.id) === Number(cardId)) {
      applyCounts(card);
      updated = true;
    }
  });
  if (updated) renderCollection();
  return updated;
}

function manaCostHtml(cost) {
  const matches = [...String(cost).matchAll(/\{([^}]+)\}/g)];
  if (!matches.length) return escapeHtml(cost);
  return matches.map((match) => {
    const symbol = match[1];
    const file = symbol.replaceAll("/", "-");
    const url = `${SYMBOL_BASE}/${encodeURIComponent(file)}.svg`;
    return `<img class="mana-symbol" src="${url}" alt="${escapeHtml(symbol)}" title="${escapeHtml(symbol)}">`;
  }).join("");
}

function showCardPreview(event, imageUrl) {
  const preview = $("cardPreview");
  preview.innerHTML = `<img src="${imageUrl}" alt="">`;
  preview.style.display = "block";
  moveCardPreview(event);
}

function moveCardPreview(event) {
  const preview = $("cardPreview");
  const width = 360;
  const height = 502;
  let left = event.clientX + 18;
  let top = event.clientY + 18;
  if (left + width > window.innerWidth - 12) {
    left = event.clientX - width - 18;
  }
  if (top + height > window.innerHeight - 12) {
    top = window.innerHeight - height - 12;
  }
  preview.style.left = `${Math.max(12, left)}px`;
  preview.style.top = `${Math.max(12, top)}px`;
}

function hideCardPreview() {
  $("cardPreview").style.display = "none";
}

function emptyState(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

async function openCardDetail(cardId) {
  const detail = await api(`/api/collection/cards/${cardId}`);
  const card = detail.card;
  $("cardDialogContent").innerHTML = `
    <div class="detail-layout">
      <div>${card.image_url ? `<img class="detail-image" src="${escapeHtml(card.image_url)}" alt="">` : ""}</div>
      <div>
        <h2>${escapeHtml(displayName(card))}</h2>
        ${oracleNameHint(card)}
        <p class="muted">${escapeHtml(card.mana_cost || "")} ${escapeHtml(displayType(card))}</p>
        <p>${escapeHtml(card.printed_text || card.oracle_text || "")}</p>
        ${renderTagEditor(card.id, detail.tags)}
        <div class="button-row">
          <button type="button" onclick="addToDeckFlow(${card.id})">Ins Deck</button>
          <button type="button" class="secondary" onclick="quickAddCopy(${card.id}, false)">Original hinzufuegen</button>
          <button type="button" class="secondary" onclick="quickAddCopy(${card.id}, true)">Proxy hinzufuegen</button>
        </div>
        <h3>Fundorte</h3>
        ${detail.places.map((place) => `
          <div class="place-row">
            <strong>${place.quantity}x</strong>
            <span>${escapeHtml(place.state)}</span>
            <span>${escapeHtml(place.place_name)}</span>
            <span class="tag ${place.state === "Online" ? "bad" : place.is_proxy ? "warn" : "good"}">${place.state === "Online" ? "Geplant" : place.is_proxy ? "Proxy" : "Original"}</span>
          </div>
        `).join("") || "<p class=\"muted\">Keine Copy in deiner Sammlung.</p>"}
        <h3>Einzelne Copies</h3>
        ${detail.copies.map((copy) => copyEditor(copy)).join("") || ""}
      </div>
    </div>
  `;
  $("cardDialog").showModal();
}

function renderTagEditor(cardId, tags) {
  const active = new Set(tags.tags || []);
  const rejected = new Set(tags.rejected_auto_tags || []);
  return `
    <section class="tag-editor">
      <h3>Kategorien</h3>
      <div class="tag-editor-grid">
        ${state.tagCatalog.map((tag) => `
          <button
            type="button"
            class="tag-toggle ${active.has(tag) ? "active" : ""} ${rejected.has(tag) ? "rejected" : ""}"
            data-tag="${escapeHtml(tag)}"
            onclick="toggleCardTag(${cardId}, '${escapeHtml(tag)}')"
          >${escapeHtml(tag)}</button>
        `).join("")}
      </div>
    </section>
  `;
}

async function toggleCardTag(cardId, tag) {
  const current = await api(`/api/cards/${cardId}/tags`);
  const manual = new Set(current.manual_tags || []);
  const rejected = new Set(current.rejected_auto_tags || []);
  const auto = new Set(current.auto_tags || []);
  const active = new Set(current.tags || []);

  if (active.has(tag)) {
    manual.delete(tag);
    if (auto.has(tag)) rejected.add(tag);
  } else {
    rejected.delete(tag);
    manual.add(tag);
  }

  await api(`/api/cards/${cardId}/tags`, {
    method: "PATCH",
    body: JSON.stringify({ manual_tags: [...manual], rejected_auto_tags: [...rejected] }),
  });
  await openCardDetail(cardId);
}

function copyEditor(copy) {
  const isInDeck = Boolean(copy.assigned_deck_id);
  const collectionLocations = state.locations.filter((location) => location.type !== "Deck");
  const locationSelect = `
    <select onchange="patchCopy(${copy.id}, { location_id: Number(this.value) || null })">
      <option value="">Ohne Ort</option>
      ${collectionLocations.map((location) => `<option value="${location.id}" ${location.id === copy.location_id ? "selected" : ""}>${escapeHtml(location.name)}</option>`).join("")}
    </select>
  `;
  const deckSelect = `
    <select onchange="patchCopy(${copy.id}, { assigned_deck_id: Number(this.value) || null })">
      <option value="">Deck waehlen...</option>
      ${state.decks.map((deck) => `<option value="${deck.id}" ${deck.id === copy.assigned_deck_id ? "selected" : ""}>${escapeHtml(deck.name)}</option>`).join("")}
    </select>
  `;
  return `
    <div class="copy-editor">
      <span>#${copy.id}</span>
      <span class="tag ${copy.is_proxy ? "warn" : "good"}">${copy.is_proxy ? "Proxy" : "Original"}</span>
      <strong>${isInDeck ? "Deck" : "Sammlung"}</strong>
      ${isInDeck ? deckSelect : locationSelect}
      ${isInDeck ? `<button class="secondary" type="button" onclick="moveCopyToCollection(${copy.id}, ${copy.card_id})">Zur Sammlung</button>` : deckSelect}
      <button class="secondary" type="button" onclick="deleteCopy(${copy.id}, ${copy.card_id})">Loeschen</button>
    </div>
  `;
}

async function quickAddCopy(cardId, isProxy, event = null) {
  await withActionButton(event, async () => {
    const locationId = defaultCollectionLocationId();
    const result = await api("/api/collection/copies", {
      method: "POST",
      body: JSON.stringify({ card_id: cardId, is_proxy: isProxy, location_id: locationId }),
    });
    toast(isProxy ? "Proxy hinzugefuegt." : "Original hinzugefuegt.");
    if (result.counts) updateGlobalCopyCounts(cardId, result.counts);
    if ($("cardDialog").open) await openCardDetail(cardId);
  });
}

async function moveCopyToCollection(id, cardId) {
  await patchCopy(id, { location_id: defaultCollectionLocationId() });
  if (cardId && $("cardDialog").open) await openCardDetail(cardId);
}

async function patchCopy(id, patch) {
  await api(`/api/collection/copies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  await Promise.all([loadCollection(), loadDeck()]);
}

async function deleteCopy(id, cardId) {
  await api(`/api/collection/copies/${id}`, { method: "DELETE" });
  toast("Copy geloescht.");
  await loadCollection();
  if (cardId && $("cardDialog").open) await openCardDetail(cardId);
}

async function addToDeckFlow(cardId, event = null) {
  const deckId = selectedDeckId();
  if (!deckId) {
    toast("Bitte zuerst ein Deck erstellen.");
    return;
  }
  await withActionButton(event, async () => {
    const result = await api(`/api/decks/${deckId}/add-card`, {
      method: "POST",
      body: JSON.stringify({ card_id: cardId, quantity: 1, action: "auto" }),
    });
    if (result.requires_decision) {
      state.pendingCardId = cardId;
      renderDecision(result.availability);
      $("decisionDialog").showModal();
      return;
    }
    toast(`${result.card_name} wurde dem Deck hinzugefuegt.`);
    if (result.counts) updateGlobalCopyCounts(cardId, result.counts);
    scheduleDeckRefresh();
    schedulePlanningRefresh();
  });
}

function renderDecision(availability) {
  const card = availability.card;
  const otherCopies = availability.in_other_decks.map((copy) => `
    <button type="button" class="wide secondary" onclick="resolveDecision('use_copy', ${copy.id})">
      Aus ${escapeHtml(copy.assigned_deck_name || "anderem Deck")} nehmen (${escapeHtml(copy.location_name || "ohne Ort")})
    </button>
  `).join("");

  $("decisionContent").innerHTML = `
    <h2>${escapeHtml(card.name)}</h2>
    <p class="muted">Keine freie Original-Copy gefunden. Was soll ManaVault tun?</p>
    <div class="decision-actions">
      ${otherCopies}
      <button type="button" class="wide" onclick="resolveDecision('proxy')">Proxy fuer dieses Deck erstellen</button>
      <button type="button" class="wide secondary" onclick="resolveDecision('plan')">Auf Einkaufsliste / geplant lassen</button>
    </div>
  `;
}

async function resolveDecision(action, copyId = null) {
  const deckId = selectedDeckId();
  const cardId = state.pendingCardId;
  if (!deckId || !cardId) return;
  const result = await api(`/api/decks/${deckId}/add-card`, {
    method: "POST",
    body: JSON.stringify({ card_id: cardId, quantity: 1, action, copy_id: copyId, allow_proxy: action !== "plan" }),
  });
  $("decisionDialog").close();
  toast("Deck aktualisiert.");
  if (result.counts) updateGlobalCopyCounts(cardId, result.counts);
  scheduleDeckRefresh();
  schedulePlanningRefresh();
}

async function loadDecks() {
  state.decks = await api("/api/decks");
  renderDeckSelect();
  renderDeckList();
}

function renderDeckList() {
  $("deckList").innerHTML = state.decks.map((deck) => `
    <article class="row-card">
      <div>
        <strong>${escapeHtml(deck.name)}</strong>
        <span class="muted">${escapeHtml(deck.format || "")} - ${deck.slot_quantity || 0} Karten</span>
      </div>
      <div class="row-actions">
        <button class="icon-button" title="Oeffnen" aria-label="Oeffnen" onclick="selectDeck(${deck.id})">${iconSvg("open")}</button>
        <button class="icon-button secondary" title="Bearbeiten" aria-label="Bearbeiten" onclick="editDeck(${deck.id})">${iconSvg("edit")}</button>
        <button class="icon-button secondary danger" title="Loeschen" aria-label="Loeschen" onclick="deleteDeck(${deck.id})">${iconSvg("delete")}</button>
      </div>
    </article>
  `).join("") || emptyState("Noch keine Decks.");
}

async function createDeckFromForm(event) {
  event.preventDefault();
  const result = await api("/api/decks", {
    method: "POST",
    body: JSON.stringify({ name: $("deckName").value, format: $("deckFormat").value }),
  });
  $("deckName").value = "";
  state.selectedDeckId = result.id;
  await refreshBasics();
  await loadDecks();
  await loadDeck();
  await loadPlanning();
  openDeckBuilder();
}

async function createDeckQuick() {
  const name = prompt("Deckname:");
  if (!name) return;
  const result = await api("/api/decks", {
    method: "POST",
    body: JSON.stringify({ name, format: "Commander" }),
  });
  state.selectedDeckId = result.id;
  await refreshBasics();
  await loadDecks();
  await loadDeck();
  await loadPlanning();
  openDeckBuilder();
}

async function selectDeck(deckId) {
  state.selectedDeckId = deckId;
  renderDeckSelect();
  await loadDeck();
  openDeckBuilder();
}

function openDeckBuilder() {
  $("deckBuilderDialog").showModal();
}

async function editDeck(deckId) {
  const deck = state.decks.find((item) => item.id === deckId);
  if (!deck) return;
  const name = prompt("Deckname:", deck.name);
  if (!name) return;
  const format = prompt("Format:", deck.format || "Commander") || deck.format;
  await api(`/api/decks/${deckId}`, {
    method: "PATCH",
    body: JSON.stringify({ name, format }),
  });
  await refreshBasics();
  await loadDecks();
  await loadDeck();
  await loadPlanning();
}

async function deleteDeck(deckId) {
  if (!confirm("Deck wirklich loeschen? Zugewiesene Copies bleiben in der Sammlung.")) return;
  await api(`/api/decks/${deckId}`, { method: "DELETE" });
  state.selectedDeckId = null;
  await refreshBasics();
  await loadDecks();
  await loadDeck();
}

async function loadDeck() {
  const deckId = selectedDeckId();
  if (!deckId) {
    $("deckDetail").innerHTML = emptyState("Kein Deck ausgewaehlt.");
    $("deckStatus").innerHTML = "";
    return;
  }
  const [detail, status] = await Promise.all([
    api(`/api/decks/${deckId}`),
    api(`/api/decks/${deckId}/status`),
  ]);
  $("deckDetail").innerHTML = `
    <h3>${escapeHtml(detail.deck.name)}</h3>
    ${detail.slots.map((slot) => `
      <div class="deck-slot">
        <div>
          <strong>${slot.quantity} ${escapeHtml(slot.name)}</strong>
          <small>${escapeHtml(slot.type_line || "")}</small>
        </div>
        <button class="icon-button secondary danger" title="Aus Deckliste entfernen" aria-label="Aus Deckliste entfernen" onclick="deleteSlot(${slot.id})">${iconSvg("delete")}</button>
      </div>
    `).join("") || emptyState("Deck ist leer. Klicke bei Karten auf 'Ins Deck'.")}
  `;
  renderStatus(status);
}

function renderStatus(status) {
  const missing = status.cards.filter((item) => item.missing > 0);
  const conflicts = status.conflicts;
  const ownedTotal = status.cards.reduce((sum, item) => sum + item.owned, 0);
  const proxyTotal = status.cards.reduce((sum, item) => sum + item.proxy, 0);
  const missingTotal = missing.reduce((sum, item) => sum + item.missing, 0);
  const assignable = status.cards.reduce((sum, item) => {
    const freeProxy = item.allow_proxy ? Number(item.free_proxy_in_collection || 0) : 0;
    return sum + Math.min(Number(item.missing || 0), Number(item.free_in_collection || 0) + freeProxy);
  }, 0);
  const assignableRows = status.cards.filter((item) => {
    const freeProxy = item.allow_proxy ? Number(item.free_proxy_in_collection || 0) : 0;
    return Number(item.missing || 0) > 0 && Number(item.free_in_collection || 0) + freeProxy > 0;
  });
  $("deckStatus").innerHTML = `
    <h3>Status</h3>
    <div class="status-strip">
      ${statusMetric("check", ownedTotal, "Vorhanden", "good")}
      ${statusMetric("proxyBadge", proxyTotal, "Proxy", "warn")}
      ${statusMetric("missing", missingTotal, "Fehlt", "bad")}
    </div>
    ${assignable ? `<button class="wide" type="button" onclick="assignFreeCopiesToDeck()">${assignable} freie Karten zuweisen</button>` : ""}
    ${assignableRows.length ? `
      <div class="assign-list">
        ${assignableRows.map((item) => `
          <button class="assign-row" type="button" onclick="assignFreeCopiesToDeck(${item.card_id})">
            <span>${escapeHtml(item.name)}</span>
            <small>${Math.min(item.missing, item.free_in_collection + (item.allow_proxy ? item.free_proxy_in_collection : 0))} zuweisen</small>
          </button>
        `).join("")}
      </div>
    ` : ""}
    ${shoppingListBlock("Einkaufsliste", status.shopping_list, "buy")}
    ${shoppingListBlock("Proxy-Liste", status.proxy_list, "proxy")}
    ${missing.length && !status.shopping_list.length && !status.proxy_list.length ? `<h4>Fehlt / geplant</h4>${missing.map((item) => `<p>${item.missing}x ${escapeHtml(item.name)}</p>`).join("")}` : ""}
    ${conflicts.length ? `<h4>Konflikte</h4>${conflicts.map((item) => `<p>${escapeHtml(item.name)} ist auch in anderen Decks.</p>`).join("")}` : ""}
  `;
}

function statusMetric(icon, value, label, tone) {
  return `
    <span class="status-metric ${tone}" title="${escapeHtml(label)}" aria-label="${escapeHtml(`${value} ${label}`)}">
      ${iconSvg(icon)}
      <strong>${value}</strong>
    </span>
  `;
}

function shoppingListBlock(title, items, kind) {
  if (!items.length) return "";
  return `
    <h4>${title}</h4>
    <div class="shopping-list ${kind}">
      ${items.map((item) => `
        <a class="shopping-row" href="${escapeHtml(item.cardmarket_url)}" target="_blank" rel="noopener noreferrer">
          <span><strong>${item.quantity}x</strong> ${escapeHtml(item.name)}</span>
          <span>Cardmarket</span>
        </a>
      `).join("")}
    </div>
  `;
}

async function assignFreeCopiesToDeck(cardId = null) {
  const deckId = selectedDeckId();
  if (!deckId) return;
  const result = await api(`/api/decks/${deckId}/assign-free`, {
    method: "POST",
    body: JSON.stringify({ card_id: cardId }),
  });
  toast(result.assigned_count ? `${result.assigned_count} freie Karten zugewiesen.` : "Keine passenden freien Karten gefunden.");
  await Promise.all([loadCollection(), loadDeck(), loadPlanning()]);
}

async function deleteSlot(slotId) {
  const deckId = selectedDeckId();
  await api(`/api/decks/${deckId}/slots/${slotId}`, { method: "DELETE" });
  await loadDeck();
  await loadPlanning();
}

async function importDeckList() {
  const deckId = selectedDeckId();
  if (!deckId) return;
  const result = await api(`/api/decks/${deckId}/import-list`, {
    method: "POST",
    body: JSON.stringify({ text: $("deckImportText").value, replace: $("replaceDeck").checked }),
  });
  toast(`${result.imported.length} importiert, ${result.unresolved.length} ungeklart.`);
  await loadDeck();
  await loadPlanning();
}

async function exportDeck() {
  const deckId = selectedDeckId();
  if (!deckId) return;
  const result = await api(`/api/decks/${deckId}/export-list`);
  $("exportText").value = result.text;
  $("exportDialog").querySelector("h2").textContent = "Deck Export";
  $("exportDialog").showModal();
}

async function exportCollection() {
  const format = $("collectionExportFormat").value || "jsonl";
  const extension = format === "markdown" ? "md" : "jsonl";
  const mimeType = format === "markdown" ? "text/markdown;charset=utf-8" : "application/x-ndjson;charset=utf-8";
  const text = await apiText(`/api/collection/export?format=${encodeURIComponent(format)}`);
  const filename = `manavault-sammlung.${extension}`;
  downloadTextFile(text, filename, mimeType);
  $("exportDialog").querySelector("h2").textContent = `Export - ${filename}`;
  $("exportText").value = text || "Deine Sammlung ist noch leer.";
  $("exportDialog").showModal();
  toast(`Export gespeichert: ${filename}`);
}

function downloadBackup() {
  window.location.href = "/api/backups/download";
  toast("Backup wird vorbereitet.");
}

async function importBackup(event) {
  const file = $("backupImportFile").files[0];
  if (!file) {
    toast("Bitte zuerst eine Backup-Datei auswaehlen.");
    return;
  }
  if (!confirm("Backup wirklich importieren? Die aktuelle Datenbank wird vorher automatisch gesichert und dann ersetzt.")) return;
  await withActionButton(event, async () => {
    const response = await fetch("/api/backups/import", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    $("backupImportFile").value = "";
    toast("Backup importiert.");
    await refreshBasics();
    await Promise.all([loadCollection(true), loadDecks(), loadPlanning()]);
    await loadDeck();
  }).catch((error) => toast(error.message));
}

function renderLocations() {
  $("locationList").innerHTML = state.locations.map((location) => `
    <article class="row-card">
      <div>
        <strong>${escapeHtml(location.name)}</strong>
        <span class="muted">${escapeHtml(location.type)}</span>
      </div>
      <div class="row-actions">
        <button class="icon-button" title="Oeffnen" aria-label="Oeffnen" onclick="openLocationDetail(${location.id})">${iconSvg("open")}</button>
        <button class="icon-button secondary" title="Bearbeiten" aria-label="Bearbeiten" onclick="editLocation(${location.id})">${iconSvg("edit")}</button>
        <button class="icon-button secondary danger" title="Loeschen" aria-label="Loeschen" onclick="deleteLocation(${location.id})">${iconSvg("delete")}</button>
      </div>
    </article>
  `).join("") || emptyState("Noch keine Orte.");
}

async function openLocationDetail(locationId) {
  const detail = await api(`/api/locations/${locationId}`);
  const otherLocations = state.locations.filter((location) => location.id !== locationId && location.type !== "Deck");
  $("locationDialogContent").innerHTML = `
    <div class="location-detail-head">
      <div>
        <h2>${escapeHtml(detail.location.name)}</h2>
        <p class="muted">${escapeHtml(detail.location.type)} - ${detail.copies.length} einzelne Copies</p>
      </div>
    </div>
    <div class="location-summary">
      ${detail.summary.map((card) => `
        <button type="button" class="location-card-summary" onclick="openCardDetail(${card.card_id})">
          ${card.image_url ? `<img src="${escapeHtml(card.image_url)}" alt="">` : ""}
          <span><strong>${escapeHtml(displayName(card))}</strong><small>${card.total_count}x - ${card.owned_count || 0} Original / ${card.proxy_count || 0} Proxy</small></span>
        </button>
      `).join("") || emptyState("Dieser Ort ist leer.")}
    </div>
    <h3>Einzelne Copies</h3>
    <div class="location-copy-list">
      ${detail.copies.map((copy) => `
        <div class="location-copy-row">
          <div>
            <strong>${escapeHtml(displayName(copy))}</strong>
            <small>${escapeHtml(copy.mana_cost || "")} ${escapeHtml(displayType(copy))}</small>
          </div>
          <span class="tag ${copy.is_proxy ? "warn" : "good"}">${copy.is_proxy ? "Proxy" : "Original"}</span>
          <select onchange="moveCopyFromLocation(${copy.id}, Number(this.value), ${locationId})">
            <option value="">Verschieben nach...</option>
            ${otherLocations.map((location) => `<option value="${location.id}">${escapeHtml(location.name)}</option>`).join("")}
          </select>
          <button type="button" class="secondary danger" onclick="deleteCopyFromLocation(${copy.id}, ${locationId})">Entfernen</button>
        </div>
      `).join("") || ""}
    </div>
  `;
  $("locationDialog").showModal();
}

async function moveCopyFromLocation(copyId, targetLocationId, currentLocationId) {
  if (!targetLocationId) return;
  await patchCopy(copyId, { location_id: targetLocationId });
  toast("Copy verschoben.");
  await openLocationDetail(currentLocationId);
}

async function deleteCopyFromLocation(copyId, locationId) {
  if (!confirm("Diese Copy wirklich aus deiner Sammlung entfernen?")) return;
  await api(`/api/collection/copies/${copyId}`, { method: "DELETE" });
  toast("Copy entfernt.");
  await Promise.all([loadCollection(), loadDeck()]);
  await openLocationDetail(locationId);
}

async function createLocation(event) {
  event.preventDefault();
  await api("/api/locations", {
    method: "POST",
    body: JSON.stringify({ name: $("locationName").value, type: $("locationType").value }),
  });
  $("locationName").value = "";
  await refreshBasics();
}

async function editLocation(locationId) {
  const location = state.locations.find((item) => item.id === locationId);
  if (!location) return;
  const name = prompt("Location:", location.name);
  if (!name) return;
  const type = prompt("Typ:", location.type) || location.type;
  await api(`/api/locations/${locationId}`, {
    method: "PATCH",
    body: JSON.stringify({ name, type }),
  });
  await refreshBasics();
  await loadCollection();
}

async function deleteLocation(locationId) {
  if (!confirm("Location wirklich loeschen? Das geht nur, wenn keine Copies dort liegen.")) return;
  try {
    await api(`/api/locations/${locationId}`, { method: "DELETE" });
    await refreshBasics();
    await loadCollection();
  } catch (error) {
    await openDeleteLocationDialog(locationId, error.message);
  }
}

async function openDeleteLocationDialog(locationId, message) {
  const location = state.locations.find((item) => item.id === locationId);
  if (!location) {
    toast(message);
    return;
  }
  state.pendingDeleteLocationId = locationId;
  const targets = state.locations.filter((item) => item.id !== locationId && item.type !== "Deck");
  $("deleteLocationContent").innerHTML = `
    <h2>${escapeHtml(location.name)} loeschen</h2>
    <p class="muted">Dieser Ort enthaelt noch Karten. Was soll mit diesen Copies passieren?</p>
    <div class="delete-location-actions">
      <label>
        Karten verschieben nach
        <select id="deleteLocationMoveTarget">
          ${targets.map((target) => `<option value="${target.id}">${escapeHtml(target.name)}</option>`).join("")}
        </select>
      </label>
      <button type="button" ${targets.length ? "" : "disabled"} onclick="confirmDeleteLocationMove()">Verschieben und Ort loeschen</button>
      <button type="button" class="secondary" onclick="confirmDeleteLocationDetach()">Karten behalten ohne Ort</button>
    </div>
  `;
  $("deleteLocationDialog").showModal();
}

async function confirmDeleteLocationMove() {
  const locationId = state.pendingDeleteLocationId;
  const targetId = Number($("deleteLocationMoveTarget").value);
  if (!locationId || !targetId) return;
  await api(`/api/locations/${locationId}?move_to_location_id=${targetId}`, { method: "DELETE" });
  $("deleteLocationDialog").close();
  toast("Ort geloescht, Karten verschoben.");
  await refreshBasics();
  await loadCollection();
}

async function confirmDeleteLocationDetach() {
  const locationId = state.pendingDeleteLocationId;
  if (!locationId) return;
  await api(`/api/locations/${locationId}?detach_copies=true`, { method: "DELETE" });
  $("deleteLocationDialog").close();
  toast("Ort geloescht, Karten behalten.");
  await refreshBasics();
  await loadCollection();
}

window.openCardDetail = openCardDetail;
window.addToDeckFlow = addToDeckFlow;
window.quickAddCopy = quickAddCopy;
window.patchCopy = patchCopy;
window.deleteCopy = deleteCopy;
window.moveCopyToCollection = moveCopyToCollection;
window.resolveDecision = resolveDecision;
window.selectDeck = selectDeck;
window.editDeck = editDeck;
window.deleteDeck = deleteDeck;
window.deleteSlot = deleteSlot;
window.editLocation = editLocation;
window.deleteLocation = deleteLocation;
window.openLocationDetail = openLocationDetail;
window.moveCopyFromLocation = moveCopyFromLocation;
window.deleteCopyFromLocation = deleteCopyFromLocation;
window.confirmDeleteLocationMove = confirmDeleteLocationMove;
window.confirmDeleteLocationDetach = confirmDeleteLocationDetach;
window.showCardPreview = showCardPreview;
window.moveCardPreview = moveCardPreview;
window.hideCardPreview = hideCardPreview;
window.toggleCardTag = toggleCardTag;

init().catch((error) => toast(error.message));
