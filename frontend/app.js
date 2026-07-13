const state = {
  collection: [],
  collectionOffset: 0,
  collectionHasMore: true,
  collectionPageSize: 120,
  deckBuilderCards: [],
  deckBuilderOffset: 0,
  deckBuilderHasMore: true,
  deckBuilderPageSize: 120,
  tagCatalog: [],
  setCatalog: [],
  planning: null,
  collectionStats: null,
  locations: [],
  decks: [],
  deckVariants: [],
  activeDeckVariantId: null,
  deckEditDirty: false,
  selectedDeckId: null,
  collectionActiveDeckId: null,
  activePage: "collectionPage",
  pendingCardId: null,
  pendingDeckId: null,
  importStatusTimer: null,
  importWasRunning: false,
  importStatusHideTimer: null,
  deckBuilderSplit: 52,
  scannerCard: null,
  scannerResults: [],
  scannerStream: null,
  scannerTimer: null,
  scannerChangeTimer: null,
  scannerWatchdogTimer: null,
  scannerBusy: false,
  scannerCandidate: "",
  scannerCandidateHits: 0,
  scannerCandidateHistory: [],
  scannerTorch: false,
  scannerZoom: 1,
  scannerZoomStep: 0.1,
  scannerZoomTimer: null,
  scannerPaused: false,
  scannerFingerprint: null,
  scannerLastAcceptedFingerprint: null,
  scannerLastAcceptedPrint: "",
  scannerStableFrames: 0,
  scannerLastScanAt: 0,
  scannerForceNext: false,
  scannerWaitingForChange: false,
  scannerLastReport: null,
  quickAddBursts: new Map(),
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

function countLabel(count, singular, plural) {
  return `${count} ${Number(count) === 1 ? singular : plural}`;
}

function displayName(card) {
  return card.printed_name || card.name || card.card_name || "";
}

function displayType(card) {
  return card.printed_type_line || card.type_line || "";
}

function scannerPrintLabel(card) {
  if (card.is_token) return tokenPrintIdentifier(card);
  const base = `${String(card.set_code || "").toUpperCase()} #${card.collector_number || ""}`.trim();
  const language = String(card.lang || "").toUpperCase();
  return language && language !== "EN" ? `${base} ${language}` : base;
}

function tokenPrintIdentifier(card) {
  const rawNumber = String(card.collector_number || "").toUpperCase();
  const match = rawNumber.match(/^(\d+)(.*)$/);
  const collectorNumber = match ? `${match[1].padStart(4, "0")}${match[2]}` : rawNumber;
  return ["T", collectorNumber, String(card.set_code || "").toUpperCase(), String(card.lang || "").toUpperCase()]
    .filter(Boolean)
    .join(" ");
}

function cardPrintSummary(card) {
  if (card.is_token) return tokenPrintIdentifier(card);
  return card.set_code ? `${String(card.set_code).toUpperCase()} #${card.collector_number || ""}` : "";
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

function scheduleDeckBuilderLoad() {
  loadDeckBuilderCollection(true);
}

function selectedDeckId() {
  const value = Number(state.selectedDeckId || $("deckSelect")?.value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function collectionTargetDeckId() {
  const value = Number(state.collectionActiveDeckId || $("collectionActiveDeck")?.value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function cardActionDeckId() {
  return state.activePage === "deckBuilderPage" ? selectedDeckId() : collectionTargetDeckId();
}

async function init() {
  wireEvents();
  loadAppVersion();
  const sharedDeck = deckReferenceFromPublicPath();
  if (sharedDeck) {
    document.body.classList.add("public-deck-view");
    await loadPublicDeck(sharedDeck);
    return;
  }
  await refreshBasics();
  await Promise.all([loadCollection(), loadDecks(), loadPlanning()]);
  await loadDeck();
  await refreshImportStatus();
}

async function loadAppVersion() {
  try {
    const result = await api("/api/version");
    $("appVersion").textContent = `v${result.version}`;
  } catch {
    $("appVersion").hidden = true;
  }
}

function wireEvents() {
  setupStaticIconButtons();
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.page));
  });

  $("collectionSearch").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionSearchAllCards").addEventListener("change", () => {
    updateCollectionScopeUi();
    loadCollection(true);
  });
  document.querySelectorAll(".collectionManaFilter").forEach((button) => {
    const color = button.dataset.color;
    button.innerHTML = `<img src="${MANA_SYMBOLS[color]}" alt="${color}">`;
    button.addEventListener("click", () => {
      button.classList.toggle("active");
      loadCollection(true);
    });
  });
  document.querySelectorAll(".deckListManaFilter").forEach((button) => {
    const color = button.dataset.color;
    button.innerHTML = `<img src="${MANA_SYMBOLS[color]}" alt="${color}">`;
    button.addEventListener("click", () => {
      button.classList.toggle("active");
      renderDeckList();
    });
  });
  document.querySelectorAll(".deckBuilderManaFilter").forEach((button) => {
    const color = button.dataset.color;
    button.innerHTML = `<img src="${MANA_SYMBOLS[color]}" alt="${color}">`;
    button.addEventListener("click", () => {
      button.classList.toggle("active");
      loadDeckBuilderCollection(true);
    });
  });
  $("collectionCmcMin").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionCmcMax").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionTypeFilter").addEventListener("change", () => loadCollection(true));
  $("collectionTagFilter").addEventListener("change", () => loadCollection(true));
  $("collectionLegalFilter").addEventListener("change", () => loadCollection(true));
  $("collectionRarityFilter").addEventListener("change", () => loadCollection(true));
  $("collectionSetFilter").addEventListener("change", () => loadCollection(true));
  $("collectionLangFilter").addEventListener("change", () => loadCollection(true));
  $("collectionMinPrice").addEventListener("input", () => debounce(scheduleCollectionLoad));
  $("collectionSort").addEventListener("change", () => loadCollection(true));
  $("exportCollection").addEventListener("click", exportCollection);
  $("collectionLoadMore").addEventListener("click", () => loadCollection(false));
  $("openCardScanner").addEventListener("click", openCardScanner);
  $("closeCardScanner").addEventListener("click", closeCardScanner);
  $("startLiveScanner").addEventListener("click", startLiveScanner);
  $("scanLiveCard").addEventListener("click", scanLiveCard);
  $("scannerCameraSelect").addEventListener("change", changeScannerCamera);
  $("toggleScannerTorch").addEventListener("click", toggleScannerTorch);
  $("scannerZoom").addEventListener("input", (event) => scheduleScannerZoom(Number(event.target.value)));
  $("scannerZoomOut").addEventListener("click", () => nudgeScannerZoom(-1));
  $("scannerZoomIn").addEventListener("click", () => nudgeScannerZoom(1));
  $("scannerDialog").addEventListener("close", stopLiveScanner);
  $("scannerCapture").addEventListener("change", scanCapturedCard);
  $("reportScannerIssue").addEventListener("click", reportScannerIssue);
  $("scannerSearch").addEventListener("input", () => debounce(searchScannerCards, 300));
  $("deckBuilderSearch").addEventListener("input", () => debounce(scheduleDeckBuilderLoad));
  $("deckBuilderSearchAllCards").addEventListener("change", () => {
    updateDeckBuilderScopeUi();
    loadDeckBuilderCollection(true);
  });
  $("deckBuilderCmcMin").addEventListener("input", () => debounce(scheduleDeckBuilderLoad));
  $("deckBuilderCmcMax").addEventListener("input", () => debounce(scheduleDeckBuilderLoad));
  $("deckBuilderTypeFilter").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderTagFilter").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderLegalFilter").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderRarityFilter").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderSetFilter").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderLangFilter").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderMinPrice").addEventListener("input", () => debounce(scheduleDeckBuilderLoad));
  $("deckBuilderSort").addEventListener("change", () => loadDeckBuilderCollection(true));
  $("deckBuilderLoadMore").addEventListener("click", () => loadDeckBuilderCollection(false));
  $("clearDeckBuilderFilters").addEventListener("click", () => {
    $("deckBuilderSearch").value = "";
    $("deckBuilderCmcMin").value = "";
    $("deckBuilderCmcMax").value = "";
    $("deckBuilderTypeFilter").value = "";
    $("deckBuilderTagFilter").value = "";
    $("deckBuilderLegalFilter").value = "";
    $("deckBuilderRarityFilter").value = "";
    $("deckBuilderSetFilter").value = "";
    $("deckBuilderLangFilter").value = "en,de";
    $("deckBuilderMinPrice").value = "";
    $("deckBuilderSort").value = "name";
    $("deckBuilderSearchAllCards").checked = false;
    updateDeckBuilderScopeUi();
    document.querySelectorAll(".deckBuilderManaFilter").forEach((button) => button.classList.remove("active"));
    loadDeckBuilderCollection(true);
  });
  $("clearCollectionFilters").addEventListener("click", () => {
    $("collectionSearch").value = "";
    $("collectionCmcMin").value = "";
    $("collectionCmcMax").value = "";
    $("collectionTypeFilter").value = "";
    $("collectionTagFilter").value = "";
    $("collectionLegalFilter").value = "";
    $("collectionRarityFilter").value = "";
    $("collectionSetFilter").value = "";
    $("collectionLangFilter").value = "en,de";
    $("collectionMinPrice").value = "";
    $("collectionSort").value = "name";
    $("collectionSearchAllCards").checked = false;
    updateCollectionScopeUi();
    document.querySelectorAll(".collectionManaFilter").forEach((button) => button.classList.remove("active"));
    loadCollection(true);
  });
  $("deckSearch").addEventListener("input", () => debounce(renderDeckList));
  $("deckFormatFilter").addEventListener("change", renderDeckList);
  $("deckTypeFilter").addEventListener("change", renderDeckList);
  $("deckSort").addEventListener("change", renderDeckList);
  $("clearDeckFilters").addEventListener("click", () => {
    $("deckSearch").value = "";
    $("deckFormatFilter").value = "";
    $("deckTypeFilter").value = "";
    $("deckSort").value = "name";
    document.querySelectorAll(".deckListManaFilter").forEach((button) => button.classList.remove("active"));
    renderDeckList();
  });

  $("deckSelect").addEventListener("change", async () => {
    state.selectedDeckId = selectedDeckIdFromElement("deckSelect");
    renderDeckSelect();
    if (state.activePage === "deckBuilderPage" && state.selectedDeckId) {
      await api(`/api/decks/${state.selectedDeckId}/edit/begin`, { method: "POST" });
    }
    await loadDeck();
  });
  $("collectionActiveDeck").addEventListener("change", async () => {
    state.collectionActiveDeckId = selectedDeckIdFromElement("collectionActiveDeck");
    renderDeckSelect();
    renderCollection();
  });

  $("deckForm").addEventListener("submit", createDeckFromForm);
  $("openDeckBuilder").addEventListener("click", openDeckBuilder);
  $("deckQrButton").addEventListener("click", () => openDeckQr(selectedDeckId()));
  $("backToDecks").addEventListener("click", () => showPage("decksPage"));
  $("deckVariantSelect").addEventListener("change", activateSelectedDeckVariant);
  $("saveDeckChanges").addEventListener("click", saveDeckChanges);
  $("discardDeckChanges").addEventListener("click", discardDeckChanges);
  $("saveDeckAsVariant").addEventListener("click", saveDeckAsVariant);
  $("closeDeckQr").addEventListener("click", closeDeckQr);
  $("printDeckQr").addEventListener("click", printDeckQr);
  $("deckQrDialog").addEventListener("close", () => document.body.classList.remove("qr-printing"));
  $("rotateDeckShare").addEventListener("click", rotateDeckShare);
  $("revokeDeckShare").addEventListener("click", revokeDeckShare);
  $("historySearch").addEventListener("input", () => debounce(loadHistory, 250));
  $("historyAction").addEventListener("change", loadHistory);
  $("downloadUserBackup").addEventListener("click", downloadUserBackup);
  $("importUserBackup").addEventListener("click", importUserBackup);
  $("downloadBackup").addEventListener("click", downloadBackup);
  $("importBackup").addEventListener("click", importBackup);

  $("importScryfall").addEventListener("click", importScryfall);
  setupDeckWorkbenchResize();
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
  setIconButton("deckQrButton", "qr", "QR-Code erstellen");
  $("deckQrButton")?.insertAdjacentHTML("beforeend", "<span>QR-Code</span>");
  setIconButton("backToDecks", "back", "Zurueck zu Decks");
  setIconButton("downloadUserBackup", "download", "Datenbackup exportieren");
  setIconButton("importUserBackup", "upload", "Datenbackup importieren");
  setIconButton("downloadBackup", "download", "Vollbackup exportieren");
  setIconButton("importBackup", "upload", "Vollbackup importieren");
  document.querySelectorAll(".scope-toggle-icon").forEach((icon) => {
    icon.innerHTML = iconSvg("allCards");
  });
  updateCollectionScopeUi();
  updateDeckBuilderScopeUi();
}

function openCardScanner() {
  state.scannerCard = null;
  $("scannerSearch").value = "";
  $("scannerResults").innerHTML = "";
  $("scannerChoice").hidden = true;
  state.scannerLastReport = null;
  $("reportScannerIssue").hidden = true;
  $("scannerStatus").textContent = "";
  $("scannerPreview").hidden = true;
  $("scannerDialog").showModal();
  startLiveScanner();
}

function closeCardScanner() {
  stopLiveScanner();
  $("scannerDialog").close();
  if ($("scannerPreview").src) URL.revokeObjectURL($("scannerPreview").src);
  $("scannerCapture").value = "";
}

async function startLiveScanner() {
  stopLiveScanner();
  state.scannerCandidate = "";
  state.scannerCandidateHits = 0;
  state.scannerCandidateHistory = [];
  state.scannerCard = null;
  $("scannerChoice").hidden = true;
  $("scannerResults").innerHTML = "";
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    $("scannerStatus").textContent = "Live-Kamera benoetigt die Tailscale-HTTPS-Adresse. Foto oder Namenssuche sind weiterhin moeglich.";
    $("startLiveScanner").hidden = false;
    return;
  }
  try {
    const savedCameraId = localStorage.getItem("manavault-scanner-camera") || "";
    const videoConstraints = savedCameraId
      ? { deviceId: { exact: savedCameraId }, width: { ideal: 1920 }, height: { ideal: 1080 } }
      : { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } };
    try {
      state.scannerStream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: false });
    } catch (cameraError) {
      if (!savedCameraId) throw cameraError;
      localStorage.removeItem("manavault-scanner-camera");
      state.scannerStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
    }
    const video = $("scannerVideo");
    video.srcObject = state.scannerStream;
    await video.play();
    updateScannerGuide();
    const videoTrack = state.scannerStream.getVideoTracks()[0];
    await configureScannerCameras(videoTrack);
    const torchSupported = Boolean(videoTrack?.getCapabilities?.().torch);
    $("toggleScannerTorch").hidden = !torchSupported;
    $("toggleScannerTorch").textContent = "Licht einschalten";
    state.scannerTorch = false;
    configureScannerZoom(videoTrack);
    $("scannerCamera").hidden = false;
    $("startLiveScanner").hidden = true;
    $("scanLiveCard").hidden = false;
    $("scannerPreview").hidden = true;
    resumeLiveScanner();
  } catch (error) {
    $("scannerStatus").textContent = error.name === "NotAllowedError"
      ? "Kamerazugriff wurde nicht erlaubt. Bitte Browser-Berechtigung pruefen."
      : `Live-Kamera konnte nicht gestartet werden: ${error.message}`;
    $("startLiveScanner").hidden = false;
  }
}

async function configureScannerCameras(activeTrack) {
  const wrap = $("scannerCameraSelectWrap");
  const select = $("scannerCameraSelect");
  try {
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === "videoinput");
    const activeId = activeTrack?.getSettings?.().deviceId || "";
    select.innerHTML = devices.map((device, index) => (
      `<option value="${escapeHtml(device.deviceId)}">${escapeHtml(device.label || `Kamera ${index + 1}`)}</option>`
    )).join("");
    if (activeId && devices.some((device) => device.deviceId === activeId)) select.value = activeId;
    wrap.hidden = devices.length < 2;
  } catch (_error) {
    wrap.hidden = true;
  }
}

function changeScannerCamera(event) {
  const deviceId = event.target.value;
  if (!deviceId) return;
  localStorage.setItem("manavault-scanner-camera", deviceId);
  $("scannerStatus").textContent = "Kamera wird gewechselt ...";
  startLiveScanner();
}

async function toggleScannerTorch() {
  const track = state.scannerStream?.getVideoTracks?.()[0];
  if (!track?.getCapabilities?.().torch) return;
  const next = !state.scannerTorch;
  try {
    await track.applyConstraints({ advanced: [{ torch: next }] });
    state.scannerTorch = next;
    $("toggleScannerTorch").textContent = next ? "Licht ausschalten" : "Licht einschalten";
    $("toggleScannerTorch").classList.toggle("active", next);
  } catch (error) {
    toast(`Licht konnte nicht geschaltet werden: ${error.message}`);
  }
}

function configureScannerZoom(track) {
  const capabilities = track?.getCapabilities?.();
  const zoom = capabilities?.zoom;
  const supported = zoom && Number.isFinite(Number(zoom.min)) && Number.isFinite(Number(zoom.max)) && Number(zoom.max) > Number(zoom.min);
  const controls = $("scannerZoomControls");
  controls.hidden = !supported;
  if (!supported) return;
  const slider = $("scannerZoom");
  const settings = track.getSettings?.() || {};
  const minimum = Number(zoom.min);
  const maximum = Number(zoom.max);
  const step = Number(zoom.step) > 0 ? Number(zoom.step) : 0.1;
  const current = Math.min(maximum, Math.max(minimum, Number(settings.zoom) || minimum));
  slider.min = String(minimum);
  slider.max = String(maximum);
  slider.step = String(step);
  slider.value = String(current);
  state.scannerZoom = current;
  state.scannerZoomStep = step;
  updateScannerZoomLabel(current);
}

function updateScannerZoomLabel(value) {
  $("scannerZoomValue").textContent = `${Number(value).toLocaleString("de-CH", { maximumFractionDigits: 1 })}×`;
}

function scheduleScannerZoom(value) {
  state.scannerZoom = value;
  updateScannerZoomLabel(value);
  clearTimeout(state.scannerZoomTimer);
  state.scannerZoomTimer = setTimeout(() => applyScannerZoom(value), 80);
}

function nudgeScannerZoom(direction) {
  const slider = $("scannerZoom");
  const minimum = Number(slider.min);
  const maximum = Number(slider.max);
  const next = Math.min(maximum, Math.max(minimum, Number(slider.value) + direction * state.scannerZoomStep));
  slider.value = String(next);
  scheduleScannerZoom(next);
}

async function applyScannerZoom(value) {
  const track = state.scannerStream?.getVideoTracks?.()[0];
  if (!track || track.readyState === "ended") return;
  try {
    await track.applyConstraints({ advanced: [{ zoom: value }] });
    const applied = Number(track.getSettings?.().zoom);
    if (Number.isFinite(applied)) {
      state.scannerZoom = applied;
      $("scannerZoom").value = String(applied);
      updateScannerZoomLabel(applied);
    }
  } catch (error) {
    toast(`Zoom konnte nicht eingestellt werden: ${error.message}`);
  }
}

function stopLiveScanner() {
  pauseLiveScanner();
  clearTimeout(state.scannerZoomTimer);
  state.scannerZoomTimer = null;
  state.scannerTorch = false;
  state.scannerZoom = 1;
  state.scannerFingerprint = null;
  state.scannerLastAcceptedFingerprint = null;
  state.scannerLastAcceptedPrint = "";
  state.scannerStableFrames = 0;
  state.scannerLastScanAt = 0;
  state.scannerForceNext = false;
  state.scannerWaitingForChange = false;
  state.scannerStream?.getTracks().forEach((track) => track.stop());
  state.scannerStream = null;
  if ($("scannerVideo")) $("scannerVideo").srcObject = null;
  if ($("scannerCamera")) $("scannerCamera").hidden = true;
  if ($("scannerCameraSelectWrap")) $("scannerCameraSelectWrap").hidden = true;
  if ($("scannerOcrDebug")) $("scannerOcrDebug").hidden = true;
  if ($("startLiveScanner")) $("startLiveScanner").hidden = false;
  if ($("scanLiveCard")) {
    $("scanLiveCard").hidden = true;
    $("scanLiveCard").disabled = false;
    $("scanLiveCard").textContent = "Karte jetzt scannen";
  }
  if ($("toggleScannerTorch")) {
    $("toggleScannerTorch").hidden = true;
    $("toggleScannerTorch").classList.remove("active");
    $("toggleScannerTorch").textContent = "Licht einschalten";
  }
  if ($("scannerZoomControls")) $("scannerZoomControls").hidden = true;
}

function pauseLiveScanner() {
  clearTimeout(state.scannerTimer);
  clearInterval(state.scannerTimer);
  clearInterval(state.scannerChangeTimer);
  clearInterval(state.scannerWatchdogTimer);
  state.scannerTimer = null;
  state.scannerChangeTimer = null;
  state.scannerWatchdogTimer = null;
  state.scannerPaused = true;
}

function resumeLiveScanner() {
  if (!state.scannerStream) return startLiveScanner();
  clearTimeout(state.scannerTimer);
  clearInterval(state.scannerTimer);
  clearInterval(state.scannerChangeTimer);
  clearInterval(state.scannerWatchdogTimer);
  state.scannerCandidate = "";
  state.scannerCandidateHits = 0;
  state.scannerCandidateHistory = [];
  state.scannerBusy = false;
  state.scannerPaused = false;
  state.scannerFingerprint = null;
  state.scannerStableFrames = 0;
  state.scannerWaitingForChange = Boolean(state.scannerLastAcceptedFingerprint);
  $("scannerCamera").hidden = false;
  $("startLiveScanner").hidden = true;
  $("scanLiveCard").hidden = false;
  $("scanLiveCard").disabled = false;
  $("scanLiveCard").textContent = "Karte jetzt scannen";
  $("scannerStatus").textContent = "Scanner aktiv.";
  updateScannerGuide();
  state.scannerChangeTimer = setInterval(monitorScannerCard, 150);
  state.scannerWatchdogTimer = setInterval(scannerWatchdogTick, 5000);
  if (!state.scannerWaitingForChange) scheduleAutomaticScanner(100);
}

function scheduleAutomaticScanner(delay = 60) {
  clearTimeout(state.scannerTimer);
  if (state.scannerPaused || !state.scannerStream) return;
  state.scannerTimer = setTimeout(automaticScannerTick, delay);
}

function automaticScannerTick() {
  if (state.scannerPaused || state.scannerWaitingForChange || !state.scannerStream) return;
  if (state.scannerBusy) {
    scheduleAutomaticScanner(60);
    return;
  }
  const video = $("scannerVideo");
  if (video.readyState < 2) {
    scheduleAutomaticScanner(100);
    return;
  }
  state.scannerLastScanAt = Date.now();
  const force = state.scannerForceNext;
  state.scannerForceNext = false;
  captureLiveScannerFrame(true, scannerFrameFingerprint(), force);
}

function scannerFrameFingerprint() {
  const video = $("scannerVideo");
  if (!video.videoWidth || !video.videoHeight || video.readyState < 2) return null;
  const card = scannerCardGeometry(video.videoWidth, video.videoHeight);
  const canvas = document.createElement("canvas");
  canvas.width = 24;
  canvas.height = 32;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(video, card.x, card.y, card.width, card.height, 0, 0, canvas.width, canvas.height);
  const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const gray = [];
  for (let index = 0; index < rgba.length; index += 4) {
    gray.push(rgba[index] * 0.299 + rgba[index + 1] * 0.587 + rgba[index + 2] * 0.114);
  }
  const mean = gray.reduce((sum, value) => sum + value, 0) / gray.length;
  const variance = gray.reduce((sum, value) => sum + (value - mean) ** 2, 0) / gray.length;
  const deviation = Math.max(20, Math.sqrt(variance));
  return gray.map((value) => Math.max(0, Math.min(255, 128 + (value - mean) * 32 / deviation)));
}

function scannerFingerprintDifference(first, second) {
  if (!first || !second || first.length !== second.length) return Infinity;
  return first.reduce((sum, value, index) => sum + Math.abs(value - second[index]), 0) / first.length;
}

function monitorScannerCard() {
  if (!state.scannerWaitingForChange || state.scannerBusy || state.scannerPaused || !state.scannerStream) return;
  const fingerprint = scannerFrameFingerprint();
  if (!fingerprint) return;
  const movement = scannerFingerprintDifference(fingerprint, state.scannerFingerprint);
  if (movement < 3.5) {
    state.scannerStableFrames += 1;
  } else {
    state.scannerFingerprint = fingerprint;
    state.scannerStableFrames = 0;
  }
  const changed = scannerFingerprintDifference(fingerprint, state.scannerLastAcceptedFingerprint) > 9;
  if (state.scannerStableFrames >= 2 && changed) {
    state.scannerWaitingForChange = false;
    state.scannerLastScanAt = Date.now();
    scheduleAutomaticScanner(0);
  }
}

function scannerWatchdogTick() {
  if (!state.scannerWaitingForChange || state.scannerBusy || state.scannerPaused || !state.scannerStream) return;
  state.scannerWaitingForChange = false;
  scheduleAutomaticScanner(0);
}

function scannerCardGeometry(frameWidth, frameHeight) {
  let width = frameWidth * 0.7;
  let height = width / 0.716;
  if (height > frameHeight * 0.9) {
    height = frameHeight * 0.9;
    width = height * 0.716;
  }
  return { x: (frameWidth - width) / 2, y: (frameHeight - height) / 2, width, height };
}

function updateScannerGuide() {
  const video = $("scannerVideo");
  const guide = document.querySelector(".scanner-card-guide");
  if (!video.videoWidth || !video.videoHeight || !guide) return;
  const card = scannerCardGeometry(video.videoWidth, video.videoHeight);
  guide.style.left = `${card.x / video.videoWidth * 100}%`;
  guide.style.top = `${card.y / video.videoHeight * 100}%`;
  guide.style.width = `${card.width / video.videoWidth * 100}%`;
  guide.style.height = `${card.height / video.videoHeight * 100}%`;
}

function scannerRegionCrop(source, region, isFullCard = false) {
  const canvas = document.createElement("canvas");
  const frameWidth = isFullCard ? source.width : source.videoWidth;
  const frameHeight = isFullCard ? source.height : source.videoHeight;
  const card = isFullCard ? { x: 0, y: 0, width: frameWidth, height: frameHeight } : scannerCardGeometry(frameWidth, frameHeight);
  const x = card.x + card.width * region.x;
  const y = card.y + card.height * region.y;
  const width = card.width * region.width;
  const height = card.height * region.height;
  canvas.width = Math.min(1600, Math.max(900, Math.round(width * 2)));
  canvas.height = Math.max(60, Math.round(canvas.width * height / width));
  canvas.getContext("2d").drawImage(source, x, y, width, height, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.92);
}

function scannerCrops(source, isFullCard = false) {
  return {
    nameData: scannerRegionCrop(source, { x: 0.045, y: 0.035, width: 0.87, height: 0.08 }, isFullCard),
    collectorData: scannerRegionCrop(source, { x: 0.02, y: 0.935, width: 0.23, height: 0.055 }, isFullCard),
    collectorWideData: scannerRegionCrop(source, { x: 0.02, y: 0.92, width: 0.55, height: 0.075 }, isFullCard),
  };
}

function scannerFullFrame(source, isFullCard = false) {
  const sourceWidth = isFullCard ? source.width : source.videoWidth;
  const sourceHeight = isFullCard ? source.height : source.videoHeight;
  const scale = Math.min(1, 1400 / Math.max(sourceWidth, sourceHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(sourceWidth * scale));
  canvas.height = Math.max(1, Math.round(sourceHeight * scale));
  canvas.getContext("2d").drawImage(source, 0, 0, sourceWidth, sourceHeight, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.86);
}

async function scanLiveCard() {
  const button = $("scanLiveCard");
  if (!state.scannerStream) return;
  if (state.scannerPaused) return;
  if (state.scannerBusy) {
    state.scannerForceNext = true;
    button.textContent = "Direkter Scan vorgemerkt";
    return;
  }
  state.scannerWaitingForChange = false;
  clearTimeout(state.scannerTimer);
  button.disabled = true;
  button.textContent = "Karte wird erkannt ...";
  $("scannerStatus").textContent = "Kartenkontur, Name und Druckkennung werden gelesen ...";
  try {
    state.scannerLastScanAt = Date.now();
    await captureLiveScannerFrame(true, scannerFrameFingerprint(), true);
  } finally {
    if (!state.scannerCard && state.scannerStream) {
      button.disabled = false;
      button.textContent = "Erneut scannen";
    }
  }
}

async function captureLiveScannerFrame(immediate = false, fingerprint = null, force = false) {
  const video = $("scannerVideo");
  if (state.scannerBusy || state.scannerPaused || !state.scannerStream || video.readyState < 2) return;
  state.scannerBusy = true;
  let fullImageData = null;
  if (force) {
    $("scanLiveCard").disabled = true;
    $("scanLiveCard").textContent = "Karte wird erkannt ...";
  }
  try {
    const crops = scannerCrops(video);
    fullImageData = scannerFullFrame(video);
    const result = await recognizeScannerImage(crops, true, fullImageData);
    rememberScannerReport(fullImageData, result);
    if (result.debug_collector_image) {
      $("scannerOcrPreview").src = result.debug_collector_image;
      $("scannerOcrWidePreview").src = result.debug_name_image || result.debug_collector_image;
      $("scannerOcrDebug").hidden = false;
    }
    handleScannerRecognition(result, immediate, fingerprint, force);
  } catch (error) {
    if (fullImageData) rememberScannerReport(fullImageData, { error: error.message, cards: [] });
    $("scannerStatus").textContent = error.message;
    if (/nicht installiert|Sprachdaten fehlen/i.test(error.message)) stopLiveScanner();
  } finally {
    state.scannerBusy = false;
    if (force && !state.scannerPaused && state.scannerStream) {
      $("scanLiveCard").disabled = false;
      $("scanLiveCard").textContent = "Karte jetzt scannen";
    }
    if (!state.scannerPaused && !state.scannerWaitingForChange && state.scannerStream) {
      scheduleAutomaticScanner(state.scannerForceNext ? 0 : 60);
    }
  }
}

function rememberScannerReport(imageData, result) {
  state.scannerLastReport = {
    image_data: imageData,
    result: {
      recognized_text: result.recognized_text || "",
      collector_text: result.collector_text || "",
      name_text: result.name_text || "",
      match_type: result.match_type || "none",
      ocr_engine: result.ocr_engine || "",
      ocr_score: Number(result.ocr_score || 0),
      card_detected: Boolean(result.card_detected),
      card_detection_score: Number(result.card_detection_score || 0),
      error: result.error || "",
      cards: (result.cards || []).slice(0, 8).map((card) => ({
        id: card.id,
        name: card.name,
        printed_name: card.printed_name,
        set_code: card.set_code,
        collector_number: card.collector_number,
        lang: card.lang,
      })),
    },
  };
  $("reportScannerIssue").hidden = false;
  $("reportScannerIssue").textContent = "Fehlscan speichern";
}

async function reportScannerIssue(event) {
  const report = state.scannerLastReport;
  if (!report) return;
  const expected = window.prompt("Welche Karte oder Druckkennung waere richtig? (optional)", "");
  if (expected === null) return;
  await withActionButton(event, async () => {
    const saved = await api("/api/cards/scan-reports", {
      method: "POST",
      body: JSON.stringify({ ...report, expected }),
    });
    $("reportScannerIssue").textContent = "Fehlscan gespeichert";
    toast(`Scanner-Report ${saved.report_id} gespeichert.`);
  }).catch((error) => toast(error.message));
}

async function recognizeScannerImage(crops, live = false, fullImageData = null) {
  return api("/api/cards/scan-frame", {
    method: "POST",
    body: JSON.stringify({
      image_data: crops.nameData,
      collector_data: crops.collectorData,
      collector_wide_data: crops.collectorWideData,
      full_image_data: fullImageData,
      live,
    }),
  });
}

function handleScannerRecognition(result, immediate = false, fingerprint = null, force = false) {
  const cards = result.cards || [];
  if (result.match_type !== "collector" || !cards[0]) {
    return;
  }
  const possiblePrints = new Set(cards.map((card) => `${card.set_code}:${card.collector_number}:${card.lang}`));
  const recognizedPrint = possiblePrints.size === 1 ? [...possiblePrints][0] : "";
  if (immediate) {
    const selectedPrint = state.scannerCard
      ? `${state.scannerCard.set_code}:${state.scannerCard.collector_number}:${state.scannerCard.lang}`
      : "";
    if (!recognizedPrint) {
      if (selectedPrint && possiblePrints.has(selectedPrint)) return;
      state.scannerCard = null;
      $("scannerChoice").hidden = true;
      $("scannerStatus").textContent = "Mehrere passende Drucke gefunden - bitte auswaehlen.";
      renderScannerResults(cards);
      return;
    }
    if (recognizedPrint === selectedPrint) {
      state.scannerLastAcceptedFingerprint = fingerprint || scannerFrameFingerprint();
      state.scannerWaitingForChange = true;
      return;
    }
    state.scannerLastAcceptedFingerprint = fingerprint || scannerFrameFingerprint();
    state.scannerLastAcceptedPrint = recognizedPrint;
    state.scannerWaitingForChange = true;
    $("scannerSearch").value = displayName(cards[0]);
    $("scannerStatus").textContent = `${displayName(cards[0])} - ${scannerPrintLabel(cards[0])} erkannt.`;
    renderScannerResults(cards);
    selectScannedCard(0);
    return;
  }
  const candidate = String(cards[0].id);
  state.scannerCandidateHistory.push(candidate);
  state.scannerCandidateHistory = state.scannerCandidateHistory.slice(-6);
  const hits = state.scannerCandidateHistory.filter((item) => item === candidate).length;
  const instantMatch = String(result.ocr_engine || "").startsWith("rapidocr") && Number(result.ocr_score || 0) >= 0.70 && possiblePrints.size === 1;
  const requiredHits = instantMatch ? 1 : 2;
  $("scannerStatus").textContent = `Druckkennung erkannt (${hits}/${requiredHits}) ...`;
  if (hits >= requiredHits) {
    pauseLiveScanner();
    $("scannerSearch").value = displayName(cards[0]);
    $("scannerStatus").textContent = possiblePrints.size > 1
      ? "Kennung ist zwischen mehreren echten Set-Codes mehrdeutig. Bitte Druck auswaehlen."
      : `${displayName(cards[0])} - ${scannerPrintLabel(cards[0])} eindeutig erkannt.`;
    renderScannerResults(cards);
  }
}

async function scanCapturedCard() {
  const file = $("scannerCapture").files?.[0];
  if (!file) return;
  if ($("scannerPreview").src) URL.revokeObjectURL($("scannerPreview").src);
  $("scannerPreview").src = URL.createObjectURL(file);
  $("scannerPreview").hidden = false;
  stopLiveScanner();
  $("scannerStatus").textContent = "Kartenname wird gelesen ...";
  try {
    const bitmap = await createImageBitmap(file);
    const crops = scannerCrops(bitmap, true);
    $("scannerOcrPreview").src = crops.collectorData;
    $("scannerOcrWidePreview").src = crops.collectorWideData;
    $("scannerOcrDebug").hidden = false;
    const result = await recognizeScannerImage(crops, false, scannerFullFrame(bitmap, true));
    bitmap.close();
    const cards = result.cards || [];
    $("scannerSearch").value = cards[0] ? displayName(cards[0]) : "";
    $("scannerStatus").textContent = cards.length
      ? `${result.match_type === "collector" ? "Druck eindeutig erkannt" : "Name erkannt"}: ${displayName(cards[0])}`
      : `Keine sichere Zuordnung. OCR: ${result.collector_text || result.recognized_text || "kein Text"}`;
    renderScannerResults(cards);
  } catch (error) {
    $("scannerStatus").textContent = `${error.message} Bitte Kartenname eingeben.`;
    $("scannerSearch").focus();
  }
}

function renderScannerResults(cards) {
  state.scannerResults = cards;
  $("scannerResults").innerHTML = cards.length ? cards.map((card, index) => `
    <button class="scanner-result" type="button" onclick="selectScannedCard(${index})">
      ${card.image_url ? `<img src="${escapeHtml(card.image_url)}" alt="">` : ""}
      <span><strong>${escapeHtml(displayName(card))}</strong><small>${escapeHtml(scannerPrintLabel(card))}</small></span>
    </button>
  `).join("") : emptyState("Keine passende Karte gefunden.");
}

async function searchScannerCards() {
  const query = $("scannerSearch").value.trim();
  if (query.length < 2) {
    $("scannerResults").innerHTML = "";
    return;
  }
  try {
    const cards = await api(`/api/cards/search?q=${encodeURIComponent(query)}&langs=en,de&sort=name&limit=8`);
    renderScannerResults(cards);
  } catch (error) {
    $("scannerStatus").textContent = error.message;
  }
}

function selectScannedCard(index) {
  const card = state.scannerResults[index];
  if (!card) return;
  state.scannerCard = card;
  state.scannerLastAcceptedPrint = `${card.set_code}:${card.collector_number}:${card.lang}`;
  $("scanLiveCard").hidden = false;
  $("scanLiveCard").disabled = state.scannerBusy;
  $("scanLiveCard").textContent = state.scannerBusy ? "Karte wird erkannt ..." : "Karte jetzt scannen";
  $("scannerResults").innerHTML = "";
  $("scannerChoice").hidden = false;
  $("scannerChoice").innerHTML = `
    <div class="scanner-selected">
      ${card.image_url ? `<img src="${escapeHtml(card.image_url)}" alt="">` : ""}
      <div><strong>${escapeHtml(displayName(card))}</strong><small>${escapeHtml(scannerPrintLabel(card))}</small></div>
    </div>
    <div class="quantity-stepper">
      <button class="secondary" type="button" onclick="changeScannerQuantity(-1)" aria-label="Menge verringern">&minus;</button>
      <output id="scannerQuantity">1</output>
      <button class="secondary" type="button" onclick="changeScannerQuantity(1)" aria-label="Menge erhoehen">+</button>
    </div>
    <button type="button" onclick="confirmScannedCard(event)">Zur Sammlung hinzufuegen</button>
    <button class="secondary" type="button" onclick="scannerChooseAgain()">Anderen Druck waehlen</button>`;
}

function safeScannerScroll(elementId) {
  const element = $(elementId);
  if (!element) return;
  try {
    element.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (_error) {
    element.scrollIntoView();
  }
}

function changeScannerQuantity(delta) {
  const output = $("scannerQuantity");
  output.textContent = String(Math.max(1, Math.min(100, Number(output.textContent) + delta)));
}

function scannerChooseAgain() {
  state.scannerCard = null;
  $("scannerChoice").hidden = true;
  $("scannerResults").innerHTML = "";
  state.scannerStream ? resumeLiveScanner() : startLiveScanner();
}

async function confirmScannedCard(event) {
  if (!state.scannerCard) return;
  await withActionButton(event, async () => {
    const selectedCard = state.scannerCard;
    const quantity = Number($("scannerQuantity").textContent) || 1;
    pauseLiveScanner();
    await api("/api/collection/copies/batch", {
      method: "POST",
      body: JSON.stringify({
        card_id: selectedCard.id,
        quantity,
        language: selectedCard.lang || "en",
        location_id: defaultCollectionLocationId(),
      }),
    });
    toast(`${quantity}x ${displayName(selectedCard)} hinzugefuegt.`);
    state.scannerCard = null;
    $("scannerChoice").hidden = true;
    $("scannerResults").innerHTML = "";
    $("scannerSearch").value = "";
    resumeLiveScanner();
    Promise.all([loadCollection(true), loadCollectionStats()]).catch((error) => toast(error.message));
  }).catch((error) => {
    toast(error.message);
    if (state.scannerStream) {
      resumeLiveScanner();
      $("scanLiveCard").hidden = false;
      $("scanLiveCard").disabled = false;
      $("scanLiveCard").textContent = "Karte jetzt scannen";
    }
  });
}

function updateCollectionScopeUi() {
  const toggle = $("collectionSearchAllCards");
  const label = $("collectionScopeLabel");
  const wrap = document.querySelector(".search-scope-wrap");
  const isGlobal = Boolean(toggle?.checked);
  if (label) label.textContent = isGlobal ? "Scryfall" : "Sammlung";
  if (wrap) wrap.classList.toggle("global-mode", isGlobal);
}

function updateDeckBuilderScopeUi() {
  const toggle = $("deckBuilderSearchAllCards");
  const label = $("deckBuilderScopeLabel");
  const wrap = document.querySelector(".builder-search-wrap");
  const isGlobal = Boolean(toggle?.checked);
  if (label) label.textContent = isGlobal ? "Scryfall" : "Sammlung";
  if (wrap) wrap.classList.toggle("global-mode", isGlobal);
}

function showPage(pageId) {
  state.activePage = pageId;
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === pageId));
  const activeTabPage = pageId === "deckBuilderPage" ? "decksPage" : pageId;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.page === activeTabPage));
  if (pageId === "statsPage") {
    $("collectionStats").innerHTML = `<div class="empty">Lade...</div>`;
    loadCollectionStats().catch((error) => {
      $("collectionStats").innerHTML = emptyState(error.message);
    });
  }
  if (pageId === "planningPage") loadPlanning();
  if (pageId === "historyPage") loadHistory();
}

function deckReferenceFromPublicPath() {
  const privateMatch = window.location.pathname.match(/^\/deck\/(\d+)\/?$/);
  if (privateMatch) return { type: "internal", value: Number(privateMatch[1]) };
  const shareMatch = window.location.pathname.match(/^\/share\/([A-Za-z0-9_-]{20,128})\/?$/);
  return shareMatch ? { type: "share", value: shareMatch[1] } : null;
}

async function loadPublicDeck(reference) {
  showPage("publicDeckPage");
  const content = $("publicDeckContent");
  try {
    let detail;
    let status;
    let overview;
    const isExternalShare = reference.type === "share";
    if (isExternalShare) {
      const shared = await api(`/api/public/decks/${encodeURIComponent(reference.value)}`);
      detail = { deck: shared.deck, slots: shared.cards || [] };
      status = { cards: [], required_tokens: shared.required_tokens || [], accessories: shared.accessories || [] };
      overview = shared.overview || shared.deck;
    } else {
      const deckId = reference.value;
      const [internalDetail, internalStatus, decks] = await Promise.all([
        api(`/api/decks/${deckId}`),
        api(`/api/decks/${deckId}/status`),
        api("/api/decks"),
      ]);
      detail = internalDetail;
      status = internalStatus;
      overview = decks.find((deck) => Number(deck.id) === Number(deckId)) || detail.deck;
    }
    const cards = detail.slots.filter((slot) => !slot.is_token && slot.zone !== "sideboard");
    const sideboard = detail.slots.filter((slot) => !slot.is_token && slot.zone === "sideboard");
    const tokens = detail.slots.filter((slot) => slot.is_token);
    const cardCount = cards.reduce((sum, slot) => sum + Number(slot.quantity || 0), 0);
    const sideboardCount = sideboard.reduce((sum, slot) => sum + Number(slot.quantity || 0), 0);
    const tokenCount = tokens.reduce((sum, slot) => sum + Number(slot.quantity || 0), 0);
    const originalCount = status.cards.reduce((sum, item) => sum + Number(item.owned || 0), 0);
    const proxyCount = status.cards.reduce((sum, item) => sum + Number(item.proxy || 0), 0);
    const missingCount = status.cards.reduce((sum, item) => sum + Number(item.missing || 0), 0);
    document.title = `${detail.deck.name} - ManaVault`;
    content.innerHTML = `
      <header class="public-deck-hero${overview.commander_image_url ? "" : " no-cover"}">
        ${overview.commander_image_url ? `<img src="${escapeHtml(overview.commander_image_url)}" alt="">` : ""}
        <div>
          <span class="public-deck-kicker">ManaVault Deck</span>
          <h2>${escapeHtml(detail.deck.name)}</h2>
          <p>${escapeHtml(detail.deck.format || "Ohne Format")}</p>
          <div class="public-deck-colors">
            ${(overview.colors || []).map((color) => `<img src="${MANA_SYMBOLS[color]}" alt="${color}">`).join("")}
          </div>
        </div>
      </header>
      <div class="public-deck-metrics">
        <span><strong>${cardCount}</strong><small>Karten</small></span>
        <span><strong>${sideboardCount}</strong><small>Sideboard</small></span>
        <span><strong>${tokenCount}</strong><small>Tokens</small></span>
        ${isExternalShare ? "" : `
          <span><strong>${originalCount}</strong><small>Originale</small></span>
          <span><strong>${proxyCount}</strong><small>Proxys</small></span>
          <span class="${missingCount ? "is-warning" : ""}"><strong>${missingCount}</strong><small>Fehlend</small></span>
        `}
        <span><strong>${formatEuro(overview.deck_list_value_eur || 0)}</strong><small>Deckwert</small></span>
      </div>
      ${detail.deck.notes ? `<section class="public-deck-notes"><h3>Notizen</h3><p>${escapeHtml(detail.deck.notes)}</p></section>` : ""}
      <section class="public-deck-section">
        <div class="public-deck-section-head"><h3>Deckkarten</h3></div>
        <div class="public-deck-grid">${cards.map(publicDeckCard).join("") || emptyState("Keine Deckkarten eingetragen.")}</div>
      </section>
      ${sideboard.length ? `
        <section class="public-deck-section">
          <div class="public-deck-section-head"><h3>Sideboard</h3><span>${sideboardCount}</span></div>
          <div class="public-deck-grid">${sideboard.map(publicDeckCard).join("")}</div>
        </section>` : ""}
      ${publicRequiredTokensBlock(status.required_tokens || [])}
      ${accessoriesBlock(status.accessories || [], true)}
      ${tokens.length ? `
        <section class="public-deck-section public-token-section">
          <div class="public-deck-section-head"><h3>Tokens</h3><span>${tokenCount}</span></div>
          <div class="public-deck-grid">${tokens.map(publicDeckCard).join("")}</div>
        </section>` : ""}
    `;
  } catch (error) {
    content.innerHTML = emptyState(error.message || "Deck konnte nicht geladen werden.");
  }
}

function publicRequiredTokensBlock(tokens) {
  if (!tokens.length) return "";
  const missingCount = tokens.filter((token) => token.missing > 0).length;
  return `
    <section class="public-deck-section public-required-tokens">
      <div class="public-deck-section-head">
        <div><h3>Benötigte Tokens</h3></div>
        <span class="${missingCount ? "is-missing" : ""}">${missingCount ? `${missingCount} offen` : "Vollständig"}</span>
      </div>
      <div class="public-required-token-grid">
        ${tokens.map((token) => `
          <article>
            ${token.image_url ? `<img src="${escapeHtml(token.image_url)}" alt="">` : ""}
            <div>
              <strong>${escapeHtml(token.name)}</strong>
              <small>${escapeHtml(tokenPrintIdentifier(token))}</small>
              <small>Erzeugt durch: ${token.source_names.map(escapeHtml).join(", ")}</small>
            </div>
            <span class="${token.missing ? "bad" : token.proxies ? "warn" : "good"}">${token.missing ? "Noch benötigt" : token.proxies ? "Proxy" : "Vorhanden"}</span>
          </article>`).join("")}
      </div>
    </section>`;
}

function publicDeckCard(slot) {
  return `
    <article class="public-deck-card${slot.is_token ? " public-token-card" : ""}">
      <div class="public-deck-card-image">
        ${slot.image_url ? `<img src="${escapeHtml(slot.image_url)}" alt="">` : `<span>${escapeHtml(slot.name)}</span>`}
        <strong>${slot.quantity}x</strong>
      </div>
      <div>
        <strong>${escapeHtml(slot.name)}</strong>
        <span class="mana-cost">${manaCostHtml(slot.mana_cost || "")}</span>
        <small>${escapeHtml(slot.type_line || "")}</small>
      </div>
    </article>`;
}

async function openDeckQr(deckId) {
  if (!deckId) {
    toast("Bitte zuerst ein Deck auswaehlen.");
    return;
  }
  let deck = state.decks.find((item) => Number(item.id) === Number(deckId));
  if (!deck) {
    const detail = await api(`/api/decks/${deckId}`);
    deck = detail.deck;
  }
  let share;
  try {
    share = await api(`/api/decks/${deckId}/share`, { method: "POST" });
  } catch (error) {
    toast(error.message || "Oeffentliche Adresse noch nicht eingerichtet.");
    return;
  }
  const publicUrl = share.url;
  const qrEndpoint = `/api/decks/${deckId}/qr`;
  $("deckQrTitle").textContent = `QR-Code fuer ${deck.name}`;
  $("deckQrLabelName").textContent = deck.name;
  $("deckQrUrl").textContent = publicUrl;
  $("deckQrImage").src = qrEndpoint;
  $("downloadDeckQr").href = `${qrEndpoint}?download=true`;
  $("deckQrDialog").dataset.deckId = String(deckId);
  $("deckQrDialog").showModal();
}

async function rotateDeckShare() {
  const deckId = Number($("deckQrDialog").dataset.deckId || 0);
  if (!deckId || !window.confirm("Der bisherige QR-Code funktioniert danach nicht mehr. Neuen Link erzeugen?")) return;
  try {
    const share = await api(`/api/decks/${deckId}/share/rotate`, { method: "POST" });
    if (!share.url) throw new Error("Oeffentliche Adresse noch nicht eingerichtet.");
    const qrEndpoint = `/api/decks/${deckId}/qr?t=${Date.now()}`;
    $("deckQrUrl").textContent = share.url;
    $("deckQrImage").src = qrEndpoint;
    $("downloadDeckQr").href = `${qrEndpoint}&download=true`;
    toast("Neuer Freigabelink erstellt.");
  } catch (error) {
    toast(error.message);
  }
}

async function revokeDeckShare() {
  const deckId = Number($("deckQrDialog").dataset.deckId || 0);
  if (!deckId || !window.confirm("Diesen Freigabelink deaktivieren?")) return;
  try {
    await api(`/api/decks/${deckId}/share`, { method: "DELETE" });
    closeDeckQr();
    toast("Freigabe deaktiviert.");
  } catch (error) {
    toast(error.message);
  }
}

function closeDeckQr() {
  document.body.classList.remove("qr-printing");
  $("deckQrDialog").close();
}

function printDeckQr() {
  document.body.classList.add("qr-printing");
  window.addEventListener("afterprint", () => document.body.classList.remove("qr-printing"), { once: true });
  window.print();
}

const historyLabels = {
  added: "Hinzugefuegt",
  deck_added: "Ins Deck gelegt",
  deck_removed: "Aus Deck genommen",
  deck_moved: "Deck gewechselt",
  moved: "Verschoben",
  deleted: "Geloescht",
};

async function loadHistory() {
  const params = new URLSearchParams({ limit: "500" });
  const query = $("historySearch")?.value.trim();
  const action = $("historyAction")?.value;
  if (query) params.set("q", query);
  if (action) params.set("action", action);
  const items = await api(`/api/history?${params.toString()}`);
  const groups = groupHistoryItems(items);
  $("historyMeta").textContent = groups.length === items.length
    ? countLabel(items.length, "Ereignis", "Ereignisse")
    : countLabel(groups.length, "Eintrag", "Eintraege");
  $("historyList").innerHTML = groups.map((item) => {
    const route = item.from_name && item.to_name
      ? `${escapeHtml(item.from_name)} → ${escapeHtml(item.to_name)}`
      : escapeHtml(item.to_name || item.from_name || "");
    const time = new Intl.DateTimeFormat("de-CH", { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.created_at));
    return `
      <article class="history-row history-${escapeHtml(item.action)}">
        <time datetime="${escapeHtml(item.created_at)}">${escapeHtml(time)}</time>
        <div>
          <strong>${escapeHtml(item.card_name)}</strong>
          <span>${item.quantity > 1 ? `${item.quantity}× ` : ""}${escapeHtml(historyLabels[item.action] || item.action)}${item.is_proxy ? " · Proxy" : ""}</span>
        </div>
        <span class="history-route">${route}</span>
      </article>`;
  }).join("") || emptyState("Noch keine Aenderungen aufgezeichnet.");
}

function groupHistoryItems(items) {
  const groups = [];
  for (const item of items) {
    const previous = groups[groups.length - 1];
    const sameEvent = previous
      && previous.card_id === item.card_id
      && previous.action === item.action
      && previous.from_name === item.from_name
      && previous.to_name === item.to_name
      && previous.is_proxy === item.is_proxy
      && Math.abs(new Date(previous.lastCreatedAt).getTime() - new Date(item.created_at).getTime()) <= 10000;
    if (sameEvent) {
      previous.quantity += 1;
      previous.lastCreatedAt = item.created_at;
    } else {
      groups.push({ ...item, quantity: 1, lastCreatedAt: item.created_at });
    }
  }
  return groups;
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
  renderDeckFormatFilter();
  renderTagFilter();
  renderSetFilter();
}

function renderTagFilter() {
  const collectionCurrent = $("collectionTagFilter").value;
  const builderCurrent = $("deckBuilderTagFilter").value;
  $("collectionTagFilter").innerHTML = `<option value="">Alle Tags</option>${state.tagCatalog.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join("")}`;
  $("deckBuilderTagFilter").innerHTML = $("collectionTagFilter").innerHTML;
  $("collectionTagFilter").value = collectionCurrent;
  $("deckBuilderTagFilter").value = builderCurrent;
}

function renderSetFilter() {
  const collectionCurrent = $("collectionSetFilter").value;
  const builderCurrent = $("deckBuilderSetFilter").value;
  const options = `<option value="">Alle Sets</option>${state.setCatalog.map((set) => {
    const code = String(set.code || "").toUpperCase();
    const name = set.name || code;
    const count = Number(set.card_count || 0);
    return `<option value="${escapeHtml(set.code)}">${escapeHtml(code)} - ${escapeHtml(name)} (${count})</option>`;
  }).join("")}`;
  $("collectionSetFilter").innerHTML = options;
  $("deckBuilderSetFilter").innerHTML = options;
  $("collectionSetFilter").value = collectionCurrent;
  $("deckBuilderSetFilter").value = builderCurrent;
}

function renderDeckSelect() {
  const options = state.decks.map((deck) => (
    `<option value="${deck.id}">${escapeHtml(deck.name)} (${escapeHtml(deck.format || "")})</option>`
  )).join("");
  $("deckSelect").innerHTML = options || `<option value="">Kein Deck</option>`;
  $("collectionActiveDeck").innerHTML = `<option value="">Kein Deck</option>${options}`;
  if (state.selectedDeckId) {
    $("deckSelect").value = state.selectedDeckId;
  }
  if (state.collectionActiveDeckId) {
    $("collectionActiveDeck").value = state.collectionActiveDeckId;
  } else {
    $("collectionActiveDeck").value = "";
  }
}

function renderDeckFormatFilter() {
  const select = $("deckFormatFilter");
  if (!select) return;
  const current = select.value;
  const formats = [...new Set(state.decks.map((deck) => deck.format).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  select.innerHTML = `<option value="">Alle Formate</option>${formats.map((format) => `<option value="${escapeHtml(format)}">${escapeHtml(format)}</option>`).join("")}`;
  select.value = formats.includes(current) ? current : "";
}

function selectedDeckIdFromElement(id) {
  const value = Number($(id)?.value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function collectionSearchParams() {
  return cardSearchParams({
    search: "collectionSearch",
    manaSelector: ".collectionManaFilter.active",
    cmcMin: "collectionCmcMin",
    cmcMax: "collectionCmcMax",
    type: "collectionTypeFilter",
    tag: "collectionTagFilter",
    legal: "collectionLegalFilter",
    rarity: "collectionRarityFilter",
    set: "collectionSetFilter",
    lang: "collectionLangFilter",
    minPrice: "collectionMinPrice",
    sort: "collectionSort",
  });
}

function deckBuilderSearchParams() {
  return cardSearchParams({
    search: "deckBuilderSearch",
    manaSelector: ".deckBuilderManaFilter.active",
    cmcMin: "deckBuilderCmcMin",
    cmcMax: "deckBuilderCmcMax",
    type: "deckBuilderTypeFilter",
    tag: "deckBuilderTagFilter",
    legal: "deckBuilderLegalFilter",
    rarity: "deckBuilderRarityFilter",
    set: "deckBuilderSetFilter",
    lang: "deckBuilderLangFilter",
    minPrice: "deckBuilderMinPrice",
    sort: "deckBuilderSort",
  });
}

function cardSearchParams(ids) {
  const params = new URLSearchParams();
  const colors = [...document.querySelectorAll(ids.manaSelector)].map((button) => button.dataset.color);
  params.set("q", $(ids.search).value.trim());
  params.set("colors", colors.join(","));
  if ($(ids.cmcMin).value !== "") params.set("cmc_min", $(ids.cmcMin).value);
  if ($(ids.cmcMax).value !== "") params.set("cmc_max", $(ids.cmcMax).value);
  if ($(ids.type).value) params.set("card_type", $(ids.type).value);
  if ($(ids.tag).value) params.set("tag", $(ids.tag).value);
  if ($(ids.legal).value) params.set("legal_format", $(ids.legal).value);
  if ($(ids.rarity).value) params.set("rarity", $(ids.rarity).value);
  if ($(ids.set).value) params.set("set_code", $(ids.set).value);
  if (ids.lang && $(ids.lang).value) params.set("langs", $(ids.lang).value);
  if ($(ids.minPrice).value !== "") params.set("min_price_eur", $(ids.minPrice).value);
  params.set("sort", $(ids.sort).value);
  return params;
}

function allCardsSortValue(sort) {
  const supported = new Set(["name", "name_desc", "cmc", "cmc_desc", "price", "price_asc", "rarity", "rarity_asc", "set", "released"]);
  return supported.has(sort) ? sort : "name";
}

async function loadCollection(reset = true) {
  const allCardsMode = $("collectionSearchAllCards").checked;
  if (reset) {
    state.collection = [];
    state.collectionOffset = 0;
    state.collectionHasMore = true;
  }
  if (!state.collectionHasMore) return;
  const params = collectionSearchParams();
  params.set("limit", String(state.collectionPageSize));
  params.set("offset", String(state.collectionOffset));
  if (allCardsMode) {
    params.set("sort", allCardsSortValue($("collectionSort").value));
    const cards = await api(`/api/cards/search?${params.toString()}`);
    state.collection = reset ? cards : [...state.collection, ...cards];
    state.collectionOffset += cards.length;
    state.collectionHasMore = cards.length === state.collectionPageSize;
  } else {
    const cards = await api(`/api/collection/summary?${params.toString()}`);
    state.collection = reset ? cards : [...state.collection, ...cards];
    state.collectionOffset += cards.length;
    state.collectionHasMore = cards.length === state.collectionPageSize;
  }
  renderCollection();
}

function renderCollection() {
  const allCardsMode = $("collectionSearchAllCards").checked;
  updateCollectionScopeUi();
  $("collectionSearch").placeholder = "Name / Kennung";
  $("collectionGrid").innerHTML = state.collection.map((card) => cardTile(card, {
    count: card.total_count,
    subCount: cardPrintSummary(card),
    source: allCardsMode ? "global" : "collection",
  })).join("") || emptyState(allCardsMode ? "Keine Karten. Scryfall pruefen." : "Sammlung leer.");
  $("collectionMeta").textContent = countLabel(state.collection.length, "Karte", "Karten");
  $("collectionLoadMore").style.display = state.collectionHasMore ? "block" : "none";
}

async function loadDeckBuilderCollection(reset = true) {
  const allCardsMode = $("deckBuilderSearchAllCards").checked;
  if (allCardsMode) {
    if (reset) {
      state.deckBuilderCards = [];
      state.deckBuilderOffset = 0;
      state.deckBuilderHasMore = true;
    }
    if (!state.deckBuilderHasMore) return;
    const params = deckBuilderSearchParams();
    params.set("sort", allCardsSortValue($("deckBuilderSort").value));
    params.set("limit", String(state.deckBuilderPageSize));
    params.set("offset", String(state.deckBuilderOffset));
    const cards = await api(`/api/cards/search?${params.toString()}`);
    state.deckBuilderCards = reset ? cards : [...state.deckBuilderCards, ...cards];
    state.deckBuilderOffset += cards.length;
    state.deckBuilderHasMore = cards.length === state.deckBuilderPageSize;
  } else {
    const params = deckBuilderSearchParams();
    state.deckBuilderCards = await api(`/api/collection/summary?${params.toString()}`);
    state.deckBuilderOffset = state.deckBuilderCards.length;
    state.deckBuilderHasMore = false;
  }
  renderDeckBuilderCollection();
}

function renderDeckBuilderCollection() {
  const box = $("deckBuilderCollection");
  if (!box) return;
  const allCardsMode = $("deckBuilderSearchAllCards").checked;
  updateDeckBuilderScopeUi();
  $("deckBuilderSearch").placeholder = "Name / Kennung";
  const cards = state.deckBuilderCards;
  $("deckBuilderCollectionMeta").textContent = cards.length ? countLabel(cards.length, "Karte", "Karten") : "";
  box.innerHTML = cards.map((card) => cardTile(card, {
    count: card.total_count,
    subCount: cardPrintSummary(card),
    source: allCardsMode ? "global" : "collection",
    deckBuilder: true,
  })).join("") || emptyState(allCardsMode ? "Keine Karten. Scryfall pruefen." : "Keine Karten.");
  $("deckBuilderLoadMore").style.display = allCardsMode && state.deckBuilderHasMore ? "block" : "none";
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
    <section class="stats-panel">
      <h3>Sets</h3>
      <div class="set-progress-list">
        ${(stats.set_stats || []).map((set) => `
          <article class="set-progress-row">
            <div>
              <strong>${escapeHtml(set.name)}</strong>
              <small>${escapeHtml((set.code || "").toUpperCase())} - ${set.owned_prints || 0}/${set.total_prints || 0} Drucke</small>
            </div>
            <div class="set-progress-main">
              <div class="stat-bar"><i style="width: ${Math.max(0, Math.min(100, Number(set.completion_percent || 0)))}%"></i></div>
              <span>${Number(set.completion_percent || 0).toFixed(1)}%</span>
            </div>
            <div class="set-progress-meta">
              <span>${set.owned_copies || 0} Originale</span>
              ${set.proxy_copies ? `<span>${set.proxy_copies} Proxies</span>` : ""}
              <span class="missing-value">${set.missing_prints || 0} fehlen</span>
            </div>
            ${(set.missing_examples || []).length ? `
              <details class="set-missing">
                <summary>Fehlende Beispiele</summary>
                <div>
                  ${set.missing_examples.map((card) => `<span>${escapeHtml(card.name)} <small>#${escapeHtml(card.collector_number || "")}</small></span>`).join("")}
                </div>
              </details>
            ` : ""}
          </article>
        `).join("") || emptyState("Noch keine Set-Daten.")}
      </div>
    </section>
    <section class="stats-panel">
      <h3>Deck-Werte</h3>
      <div class="deck-value-list">
        ${(stats.deck_value_stats || []).map((deck) => `
          <article class="deck-value-row">
            <div>
              <strong>${escapeHtml(deck.name)}</strong>
              <small>${escapeHtml(deck.format || "")} - ${deck.slot_quantity || 0} Kartenpositionen</small>
            </div>
            <span><strong>${formatEuro(deck.deck_list_value_eur)}</strong><small>Deckliste</small></span>
            <span><strong>${formatEuro(deck.assigned_original_value_eur)}</strong><small>Originale</small></span>
            <span class="missing-value"><strong>${formatEuro(deck.missing_value_eur)}</strong><small>Fehlt</small></span>
          </article>
        `).join("") || emptyState("Noch keine Decks.")}
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
      <span>Fehlend / geplant</span>
    </div>
    <div class="planning-card">
      <strong>${conflictTotal}</strong>
      <span>Deckkonflikte</span>
    </div>
    <div class="planning-card">
      <strong>${data.decks.length}</strong>
      <span>Decks</span>
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
    ${missing || emptyState("Nichts offen.")}
    <h3>Konflikte</h3>
    ${conflicts || emptyState("Keine Konflikte.")}
  `;
}

function cardTile(card, options) {
  const count = Number(options.count || 0);
  const countBadge = count > 0 ? `<span class="count-badge" title="${count} Copies in ManaVault">${count}x</span>` : "";
  const tokenBadge = card.is_token ? `<span class="token-badge">Token</span>` : "<span></span>";
  const valueInfo = valueBadge(card, options.source);
  const metaRow = `<div class="tile-meta-row" aria-hidden="${countBadge || valueInfo || card.is_token ? "false" : "true"}">${countBadge || "<span></span>"}${tokenBadge}${valueInfo || "<span></span>"}</div>`;
  const typeLine = displayType(card);
  const subCount = options.subCount || "";
  const previewAttrs = card.image_url
    ? `onmouseenter="showCardPreview(event, '${escapeHtml(card.image_url)}')" onmousemove="moveCardPreview(event)" onmouseleave="hideCardPreview()"`
    : "";
  const deckBuilderAction = options.deckBuilder
    ? `<button class="tile-action secondary" title="Original hinzufuegen und ins Deck" aria-label="Original hinzufuegen und ins Deck" onclick="addOriginalToDeck(${card.id}, event)">${iconSvg("originalDeck")}</button>`
    : "";
  const addToDeckAction = options.deckBuilder || collectionTargetDeckId()
    ? `<button class="tile-action primary" title="Ins Deck" aria-label="Ins Deck" onclick="addToDeckFlow(${card.id}, event)">${iconSvg("deck")}</button>`
    : "";
  const burst = state.quickAddBursts.get(Number(card.id));
  const burstCounter = burst
    ? `<span class="quick-add-counter${burst.isProxy ? " proxy" : ""}" aria-live="polite">+${burst.count}${burst.isProxy ? " P" : ""}</span>`
    : "";
  return `
    <article class="card-tile${options.deckBuilder ? " deckbuilder-tile" : ""}${card.is_token ? " token-card" : ""}" data-card-id="${card.id}" ${previewAttrs}>
      ${burstCounter}
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
        ${addToDeckAction}
        ${deckBuilderAction}
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
    originalDeck: `<span class="action-symbol">O</span><svg class="action-mini-deck" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="4" width="11" height="15" rx="2"></rect><path d="M9 8h5"></path><path d="M9 12h5"></path></svg>`,
    proxy: `<span class="action-symbol proxy-symbol">P</span><span class="action-plus">+</span>`,
    proxyBadge: `<span class="metric-letter proxy-symbol">P</span>`,
    open: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12s3-6 8-6 8 6 8 6-3 6-8 6-8-6-8-6Z"></path><circle cx="12" cy="12" r="2.5"></circle></svg>`,
    qr: `<svg class="qr-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h8v8H3V3Zm2 2v4h4V5H5Zm8-2h8v8h-8V3Zm2 2v4h4V5h-4ZM3 13h8v8H3v-8Zm2 2v4h4v-4H5Zm8-2h3v3h-3v-3Zm5 0h3v5h-2v3h-3v-5h2v-3Zm-5 5h3v3h-3v-3Zm6 1h2v2h-2v-2Z"></path></svg>`,
    edit: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path></svg>`,
    delete: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M6 7l1 13h10l1-13"></path><path d="M9 7V4h6v3"></path></svg>`,
    cover: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.2l-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z"></path></svg>`,
    coverFilled: `<svg class="filled-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.2l-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z"></path></svg>`,
    download: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 20h14"></path></svg>`,
    upload: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21V9"></path><path d="m7 14 5-5 5 5"></path><path d="M5 4h14"></path></svg>`,
    databaseImport: `<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v8c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path><path d="M5 9c0 1.7 3.1 3 7 3s7-1.3 7-3"></path><path d="M12 22v-6"></path><path d="m8 18 4 4 4-4"></path></svg>`,
    back: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5"></path><path d="m12 5-7 7 7 7"></path></svg>`,
    cart: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="20" r="1.5"></circle><circle cx="18" cy="20" r="1.5"></circle><path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.8a2 2 0 0 0 2-1.6L21 8H7"></path></svg>`,
    refresh: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5"></path><path d="M19.2 11A7.5 7.5 0 1 0 17 17.3"></path></svg>`,
    allCards: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18"></path><path d="M12 3a14 14 0 0 1 0 18"></path><path d="M12 3a14 14 0 0 0 0 18"></path></svg>`,
    check: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"></path></svg>`,
    minus: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"></path></svg>`,
    moveToSideboard: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="9" height="13" rx="2"></rect><path d="M15 8h6v11h-6"></path><path d="m11 12 4 0"></path><path d="m13 10 2 2-2 2"></path></svg>`,
    moveToDeck: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="12" y="5" width="9" height="13" rx="2"></rect><path d="M9 8H3v11h6"></path><path d="m13 12-4 0"></path><path d="m11 10-2 2 2 2"></path></svg>`,
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

function priceDetailBlock(card) {
  const price = Number(card.price_eur || 0);
  const total = Number(card.collection_value_eur || 0);
  const source = card.price_source && card.price_source !== "own" ? "ueber englischen Preis" : "eigener Preis";
  if (price <= 0 && total <= 0) return "";
  return `
    <div class="price-detail">
      <span>
        <strong>${formatEuro(price)}</strong>
        <small>Einzelpreis ${source}</small>
      </span>
      ${total > 0 ? `<span><strong>${formatEuro(total)}</strong><small>Sammlungswert Originale</small></span>` : ""}
    </div>
  `;
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
  [...state.collection, ...state.deckBuilderCards].forEach((card) => {
    if (Number(card.id) === Number(cardId)) {
      applyCounts(card);
      updated = true;
    }
  });
  if (updated) {
    renderCollection();
    renderDeckBuilderCollection();
  }
  return updated;
}

function manaCostHtml(cost) {
  const matches = [...String(cost).matchAll(/\{([^}]+)\}/g)];
  if (!matches.length) return escapeHtml(cost);
  return matches.map((match) => {
    const symbol = match[1];
    const file = symbol.replaceAll("/", "");
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
        ${priceDetailBlock(card)}
        <p>${escapeHtml(card.printed_text || card.oracle_text || "")}</p>
        ${renderTagEditor(card.id, detail.tags)}
        <div class="button-row">
          <button type="button" onclick="addToDeckFlow(${card.id})">Ins Deck</button>
          <button type="button" class="secondary" onclick="quickAddCopy(${card.id}, false)">Original hinzufuegen</button>
          <button type="button" class="secondary" onclick="quickAddCopy(${card.id}, true)">Proxy hinzufuegen</button>
        </div>
        <h3>Status</h3>
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
      ${isInDeck ? deckSelect : `<span class="muted">In deiner Sammlung</span>`}
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
    recordQuickAddBurst(cardId, isProxy);
    toast(isProxy ? "Proxy hinzugefuegt." : "Original hinzugefuegt.");
    if (result.counts) updateGlobalCopyCounts(cardId, result.counts);
    if ($("cardDialog").open) await openCardDetail(cardId);
  });
}

function recordQuickAddBurst(cardId, isProxy) {
  const key = Number(cardId);
  const previous = state.quickAddBursts.get(key);
  if (previous?.timer) clearTimeout(previous.timer);
  if (previous?.fadeTimer) clearTimeout(previous.fadeTimer);
  const count = previous && previous.isProxy === isProxy ? previous.count + 1 : 1;
  const burst = { count, isProxy, fadeTimer: null, timer: null };
  state.quickAddBursts.set(key, burst);
  burst.fadeTimer = setTimeout(() => {
    document.querySelectorAll(`.card-tile[data-card-id="${key}"] .quick-add-counter`).forEach((element) => element.classList.add("fade-out"));
  }, 1200);
  burst.timer = setTimeout(() => {
    if (state.quickAddBursts.get(key) !== burst) return;
    state.quickAddBursts.delete(key);
    document.querySelectorAll(`.card-tile[data-card-id="${key}"] .quick-add-counter`).forEach((element) => element.remove());
  }, 1900);
}

async function addOriginalToDeck(cardId, event = null) {
  const deckId = selectedDeckId();
  if (!deckId) {
    toast("Bitte im Deckbuilder ein Deck auswaehlen.");
    return;
  }
  await withActionButton(event, async () => {
    const result = await api(`/api/decks/${deckId}/add-card`, {
      method: "POST",
      body: JSON.stringify({ card_id: cardId, quantity: 1, action: "create_original" }),
    });
    recordQuickAddBurst(cardId, false);
    toast(`${result.card_name} als Original hinzugefuegt und ins Deck gelegt.`);
    if (result.counts) updateGlobalCopyCounts(cardId, result.counts);
    await Promise.all([loadDeck(), loadDecks(), loadPlanning()]);
  }).catch((error) => toast(error.message));
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
  const deckId = cardActionDeckId();
  if (!deckId) {
    toast(state.activePage === "deckBuilderPage" ? "Bitte im Deckbuilder ein Deck auswaehlen." : "Bitte oben in der Sammlung ein aktives Deck auswaehlen.");
    return;
  }
  await withActionButton(event, async () => {
    const result = await api(`/api/decks/${deckId}/add-card`, {
      method: "POST",
      body: JSON.stringify({ card_id: cardId, quantity: 1, action: "auto" }),
    });
    if (result.requires_decision) {
      state.pendingCardId = cardId;
      state.pendingDeckId = deckId;
      renderDecision(result.availability);
      $("decisionDialog").showModal();
      return;
    }
    recordQuickAddBurst(cardId, false);
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
  const deckId = state.pendingDeckId || cardActionDeckId();
  const cardId = state.pendingCardId;
  if (!deckId || !cardId) return;
  const result = await api(`/api/decks/${deckId}/add-card`, {
    method: "POST",
    body: JSON.stringify({ card_id: cardId, quantity: 1, action, copy_id: copyId, allow_proxy: action !== "plan" }),
  });
  $("decisionDialog").close();
  state.pendingCardId = null;
  state.pendingDeckId = null;
  recordQuickAddBurst(cardId, action === "proxy");
  toast("Deck aktualisiert.");
  if (result.counts) updateGlobalCopyCounts(cardId, result.counts);
  scheduleDeckRefresh();
  schedulePlanningRefresh();
}

async function loadDecks() {
  state.decks = await api("/api/decks");
  renderDeckSelect();
  renderDeckFormatFilter();
  renderDeckList();
}

function renderDeckList() {
  const decks = filteredDecks();
  $("deckMeta").textContent = decks.length === state.decks.length
    ? countLabel(state.decks.length, "Deck", "Decks")
    : `${decks.length}/${state.decks.length} Decks`;
  $("deckList").innerHTML = decks.map((deck) => `
    <article class="deck-overview-card">
      <button class="deck-cover-button" onclick="selectDeck(${deck.id})" title="Deck oeffnen" aria-label="Deck oeffnen">
        ${deck.commander_image_url ? `<img src="${escapeHtml(deck.commander_image_url)}" alt="">` : `<span>${escapeHtml(deck.name)}</span>`}
      </button>
      <div class="deck-overview-body">
        <strong>${escapeHtml(deck.name)}</strong>
        <span class="muted">${escapeHtml(deck.format || "")}</span>
        <div class="deck-overview-metrics">
          <span>${deck.slot_quantity || 0} Karten</span>
          ${Number(deck.token_quantity || 0) > 0 ? `<span>${deck.token_quantity} Tokens</span>` : ""}
          <span>${formatEuro(deck.deck_list_value_eur || 0)}</span>
        </div>
        <div class="deck-chip-row">
          ${(deck.colors || []).map((color) => `<span><img src="${MANA_SYMBOLS[color]}" alt="${color}"></span>`).join("")}
          ${(deck.types || []).slice(0, 4).map((type) => `<small>${escapeHtml(type)}</small>`).join("")}
        </div>
      </div>
      <div class="deck-overview-actions">
        <button class="icon-button" title="Oeffnen" aria-label="Oeffnen" onclick="selectDeck(${deck.id})">${iconSvg("open")}</button>
        <button class="icon-button secondary" title="QR-Code erstellen" aria-label="QR-Code erstellen" onclick="openDeckQr(${deck.id})">${iconSvg("qr")}</button>
        <button class="icon-button secondary" title="Deck exportieren" aria-label="Deck exportieren" onclick="exportDeck(${deck.id})">${iconSvg("download")}</button>
        <button class="icon-button secondary" title="Bearbeiten" aria-label="Bearbeiten" onclick="editDeck(${deck.id})">${iconSvg("edit")}</button>
        <button class="icon-button secondary danger" title="Loeschen" aria-label="Loeschen" onclick="deleteDeck(${deck.id})">${iconSvg("delete")}</button>
      </div>
    </article>
  `).join("") || emptyState("Noch keine Decks.");
}

function filteredDecks() {
  const query = $("deckSearch").value.trim().toLowerCase();
  const format = $("deckFormatFilter").value;
  const type = $("deckTypeFilter").value;
  const colors = [...document.querySelectorAll(".deckListManaFilter.active")].map((button) => button.dataset.color);
  const sort = $("deckSort").value;
  const filtered = state.decks.filter((deck) => {
    const haystack = `${deck.name || ""} ${deck.format || ""}`.toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (format && deck.format !== format) return false;
    if (type && !(deck.types || []).includes(type)) return false;
    if (colors.length && !colors.every((color) => (deck.colors || []).includes(color))) return false;
    return true;
  });
  const byName = (a, b) => String(a.name || "").localeCompare(String(b.name || ""));
  if (sort === "cards") {
    return filtered.sort((a, b) => Number(b.slot_quantity || 0) - Number(a.slot_quantity || 0) || byName(a, b));
  }
  if (sort === "value") {
    return filtered.sort((a, b) => Number(b.deck_list_value_eur || 0) - Number(a.deck_list_value_eur || 0) || byName(a, b));
  }
  if (sort === "format") {
    return filtered.sort((a, b) => String(a.format || "").localeCompare(String(b.format || "")) || byName(a, b));
  }
  return filtered.sort(byName);
}

function setupDeckWorkbenchResize() {
  const divider = $("deckWorkbenchDivider");
  const workbench = $("deckBuilderWorkbench");
  if (!divider || !workbench) return;
  const applySplit = () => {
    workbench.style.setProperty("--deck-left", `${state.deckBuilderSplit}%`);
  };
  applySplit();
  divider.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    divider.setPointerCapture(event.pointerId);
    const rect = workbench.getBoundingClientRect();
    const move = (moveEvent) => {
      const raw = ((moveEvent.clientX - rect.left) / rect.width) * 100;
      state.deckBuilderSplit = Math.max(32, Math.min(68, raw));
      applySplit();
    };
    const up = () => {
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", up);
      divider.removeEventListener("pointercancel", up);
    };
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", up);
    divider.addEventListener("pointercancel", up);
  });
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
  await openDeckBuilder();
}

async function selectDeck(deckId) {
  state.selectedDeckId = deckId;
  renderDeckSelect();
  await loadDeck();
  await openDeckBuilder();
}

async function openDeckBuilder() {
  showPage("deckBuilderPage");
  const deckId = selectedDeckId();
  if (deckId) {
    await api(`/api/decks/${deckId}/edit/begin`, { method: "POST" });
    await loadDeck();
  }
  await loadDeckBuilderCollection(true);
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
  if (state.selectedDeckId === deckId) state.selectedDeckId = null;
  if (state.collectionActiveDeckId === deckId) state.collectionActiveDeckId = null;
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
  const [detail, status, variants] = await Promise.all([
    api(`/api/decks/${deckId}`),
    api(`/api/decks/${deckId}/status`),
    api(`/api/decks/${deckId}/variants`),
  ]);
  state.deckVariants = variants.variants || [];
  state.activeDeckVariantId = variants.active_variant_id;
  state.deckEditDirty = Boolean(variants.dirty);
  renderDeckVariantBar();
  const deckCards = detail.slots.filter((slot) => !slot.is_token && slot.zone !== "sideboard");
  const sideboard = detail.slots.filter((slot) => !slot.is_token && slot.zone === "sideboard");
  const tokens = detail.slots.filter((slot) => slot.is_token);
  const cardCount = deckCards.reduce((sum, slot) => sum + Number(slot.quantity || 0), 0);
  const sideboardCount = sideboard.reduce((sum, slot) => sum + Number(slot.quantity || 0), 0);
  const tokenCount = tokens.reduce((sum, slot) => sum + Number(slot.quantity || 0), 0);
  $("deckDetail").innerHTML = `
    <div class="pane-head deck-list-head">
      <div>
        <span class="section-kicker">Aktive Variante</span>
        <h3>Deckliste</h3>
      </div>
      <div class="deck-count-summary" aria-label="Deckumfang">
        <span><strong>${cardCount}</strong> Hauptdeck</span>
        <span><strong>${sideboardCount}</strong> Sideboard</span>
        ${tokenCount ? `<span><strong>${tokenCount}</strong> Tokens</span>` : ""}
      </div>
    </div>
    <section class="deck-slot-section">
      <div class="deck-slot-section-head"><h4>Hauptdeck</h4><span>${cardCount}</span></div>
      <div class="deck-card-grid">
        ${deckCards.map((slot) => deckSlotTile(slot)).join("") || emptyState("Noch keine Deckkarten. Klicke links bei Karten auf 'Ins Deck'.")}
      </div>
    </section>
    <section class="deck-slot-section sideboard-slot-section">
      <div class="deck-slot-section-head"><h4>Sideboard</h4><span>${sideboardCount}</span></div>
      <div class="deck-card-grid">
        ${sideboard.map((slot) => deckSlotTile(slot)).join("") || emptyState("Noch keine Sideboard-Karten.")}
      </div>
    </section>
    <section class="deck-slot-section token-slot-section">
      <div class="deck-slot-section-head"><h4>Tokens</h4><span>${tokenCount}</span></div>
      <div class="deck-card-grid token-card-grid">
        ${tokens.map((slot) => deckSlotTile(slot)).join("") || emptyState("Noch keine Tokens hinzugefuegt.")}
      </div>
    </section>
    ${requiredTokensBlock(status.required_tokens || [])}
    ${accessoriesBlock(status.accessories || [])}
  `;
  renderStatus(status);
}

function deckSlotTile(slot) {
  const previewAttrs = slot.image_url
    ? `onmouseenter="showCardPreview(event, '${escapeHtml(slot.image_url)}')" onmousemove="moveCardPreview(event)" onmouseleave="hideCardPreview()"`
    : "";
  const coverClass = slot.is_cover ? " is-cover" : "";
  return `
    <article class="deck-slot-card${coverClass}${slot.is_token ? " token-slot-card" : ""}" ${previewAttrs}>
      <button class="image-button" onclick="openCardDetail(${slot.card_id})">
        ${slot.image_url ? `<img src="${escapeHtml(slot.image_url)}" alt="">` : `<span>${escapeHtml(slot.name)}</span>`}
      </button>
      <div class="tile-meta-row">
        <span class="count-badge">${slot.quantity}x</span>
        <button class="icon-button secondary slot-decrement" title="Eine Karte entfernen" aria-label="Eine Karte entfernen" onclick="decrementSlot(${slot.id}, event)">${iconSvg("minus")}</button>
        ${slot.is_token ? `<span></span>` : `<button class="icon-button secondary slot-zone" title="${slot.zone === "sideboard" ? "Ins Hauptdeck" : "Ins Sideboard"}" aria-label="${slot.zone === "sideboard" ? "Ins Hauptdeck" : "Ins Sideboard"}" onclick="moveSlotZone(${slot.id}, '${slot.zone === "sideboard" ? "mainboard" : "sideboard"}')">${iconSvg(slot.zone === "sideboard" ? "moveToDeck" : "moveToSideboard")}</button>`}
        <button class="icon-button secondary cover-button${slot.is_cover ? " active" : ""}" title="Als Deckblatt setzen" aria-label="Als Deckblatt setzen" onclick="setDeckCover(${slot.card_id})">${iconSvg(slot.is_cover ? "coverFilled" : "cover")}</button>
        <button class="icon-button secondary danger" title="Aus Deckliste entfernen" aria-label="Aus Deckliste entfernen" onclick="deleteSlot(${slot.id})">${iconSvg("delete")}</button>
      </div>
      <div class="tile-body">
        <strong>${escapeHtml(slot.name)}</strong>
        <span class="mana-cost">${manaCostHtml(slot.mana_cost || "")}</span>
        <small>${escapeHtml(slot.type_line || "")}</small>
      </div>
    </article>
  `;
}

function renderDeckVariantBar() {
  const select = $("deckVariantSelect");
  const hasVariants = state.deckVariants.length > 0;
  select.innerHTML = hasVariants
    ? state.deckVariants.map((variant) => `<option value="${variant.id}">${escapeHtml(variant.name)} (${variant.card_count} Karten)</option>`).join("")
    : `<option value="">Aktueller Deckstand</option>`;
  select.disabled = !hasVariants;
  if (state.activeDeckVariantId) select.value = String(state.activeDeckVariantId);
  const editState = $("deckEditState");
  editState.textContent = state.deckEditDirty ? "Ungespeicherte Änderungen" : "Keine offenen Änderungen";
  editState.classList.toggle("is-dirty", state.deckEditDirty);
  $("saveDeckChanges").disabled = !state.deckEditDirty;
  $("discardDeckChanges").disabled = !state.deckEditDirty;
}

async function continueDeckEditing() {
  const deckId = selectedDeckId();
  if (deckId && state.activePage === "deckBuilderPage") {
    await api(`/api/decks/${deckId}/edit/begin`, { method: "POST" });
  }
}

async function saveDeckChanges(event) {
  const deckId = selectedDeckId();
  if (!deckId) return;
  await withActionButton(event, async () => {
    await api(`/api/decks/${deckId}/edit/save`, { method: "POST" });
    await continueDeckEditing();
    toast("Deckänderungen gespeichert.");
    await Promise.all([loadDeck(), loadDecks(), loadPlanning(), loadCollection(true)]);
  }).catch((error) => toast(error.message));
}

async function discardDeckChanges(event) {
  const deckId = selectedDeckId();
  if (!deckId || !state.deckEditDirty) return;
  if (!confirm("Alle Änderungen seit dem Öffnen verwerfen?")) return;
  await withActionButton(event, async () => {
    await api(`/api/decks/${deckId}/edit/discard`, { method: "POST" });
    await continueDeckEditing();
    toast("Änderungen verworfen.");
    await Promise.all([loadDeck(), loadDecks(), loadPlanning(), loadCollection(true)]);
  }).catch((error) => toast(error.message));
}

async function saveDeckAsVariant(event) {
  const deckId = selectedDeckId();
  if (!deckId) return;
  const suggested = `Variante ${state.deckVariants.length + 1}`;
  const name = prompt("Name der neuen Variante:", suggested)?.trim();
  if (!name) return;
  await withActionButton(event, async () => {
    await api(`/api/decks/${deckId}/variants`, {
      method: "POST",
      body: JSON.stringify({ name, base_name: "Original" }),
    });
    await continueDeckEditing();
    toast(`Variante „${name}“ gespeichert und aktiviert.`);
    await Promise.all([loadDeck(), loadDecks(), loadPlanning(), loadCollection(true)]);
  }).catch((error) => toast(error.message));
}

async function activateSelectedDeckVariant(event) {
  const deckId = selectedDeckId();
  const variantId = Number(event.target.value);
  if (!deckId || !variantId || variantId === Number(state.activeDeckVariantId)) return;
  if (state.deckEditDirty) {
    const discard = confirm("Es gibt ungespeicherte Änderungen. Verwerfen und die gewählte Variante aktivieren?");
    if (!discard) {
      event.target.value = String(state.activeDeckVariantId || "");
      return;
    }
    await api(`/api/decks/${deckId}/edit/discard`, { method: "POST" });
  }
  try {
    const result = await api(`/api/decks/${deckId}/variants/${variantId}/activate`, { method: "POST" });
    await continueDeckEditing();
    toast(result.missing ? `${result.name} aktiviert · ${result.missing} Karten fehlen.` : `${result.name} aktiviert.`);
    await Promise.all([loadDeck(), loadDecks(), loadPlanning(), loadCollection(true)]);
  } catch (error) {
    toast(error.message);
    event.target.value = String(state.activeDeckVariantId || "");
  }
}

async function moveSlotZone(slotId, zone) {
  const deckId = selectedDeckId();
  if (!deckId) return;
  await api(`/api/decks/${deckId}/slots/${slotId}/zone`, {
    method: "POST",
    body: JSON.stringify({ zone }),
  });
  toast(zone === "sideboard" ? "Karte ins Sideboard verschoben." : "Karte ins Hauptdeck verschoben.");
  await loadDeck();
}

async function setDeckCover(cardId) {
  const deckId = selectedDeckId();
  if (!deckId) return;
  await api(`/api/decks/${deckId}`, {
    method: "PATCH",
    body: JSON.stringify({ commander_card_id: cardId }),
  });
  toast("Deckblatt gesetzt.");
  await loadDecks();
  await loadDeck();
}

function renderStatus(status) {
  const missing = status.cards.filter((item) => item.missing > 0);
  const tokens = status.tokens || [];
  const tokenOriginalTotal = tokens.reduce((sum, item) => sum + item.owned, 0);
  const tokenProxyTotal = tokens.reduce((sum, item) => sum + item.proxy, 0);
  const tokenMissingTotal = tokens.reduce((sum, item) => sum + item.missing, 0);
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
  const tokenAssignable = tokens.reduce((sum, item) => {
    const freeProxy = item.allow_proxy ? Number(item.free_proxy_in_collection || 0) : 0;
    return sum + Math.min(Number(item.missing || 0), Number(item.free_in_collection || 0) + freeProxy);
  }, 0);
  const tokenAssignableRows = tokens.filter((item) => {
    const freeProxy = item.allow_proxy ? Number(item.free_proxy_in_collection || 0) : 0;
    return Number(item.missing || 0) > 0 && Number(item.free_in_collection || 0) + freeProxy > 0;
  });
  $("deckStatus").innerHTML = `
    <div class="deck-status-heading">
      <div>
        <span class="section-kicker">Deckstatus</span>
        <h3>Verfügbarkeit</h3>
      </div>
      <span class="status-summary ${missingTotal ? "has-missing" : "is-complete"}">${missingTotal ? `${missingTotal} fehlen` : "Vollständig"}</span>
    </div>
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
            <span>${escapeHtml(item.name)}${item.zone === "sideboard" ? ` <small>Sideboard</small>` : ""}</span>
            <small>${Math.min(item.missing, item.free_in_collection + (item.allow_proxy ? item.free_proxy_in_collection : 0))} zuweisen</small>
          </button>
        `).join("")}
      </div>
    ` : ""}
    ${shoppingListBlock("Einkaufsliste", status.shopping_list, "buy")}
    ${shoppingListBlock("Proxy-Liste", status.proxy_list, "proxy")}
    ${missing.length && !status.shopping_list.length && !status.proxy_list.length ? `<h4>Fehlt / geplant</h4>${missing.map((item) => `<p>${item.missing}x ${escapeHtml(item.name)}${item.zone === "sideboard" ? " (Sideboard)" : ""}</p>`).join("")}` : ""}
    ${conflicts.length ? `<h4>Konflikte</h4>${conflicts.map((item) => `<p>${escapeHtml(item.name)} ist auch in anderen Decks.</p>`).join("")}` : ""}
    ${tokens.length ? `
      <section class="token-status-block">
        <h3>Tokens</h3>
        <div class="status-strip token-status-strip">
          ${statusMetric("check", tokenOriginalTotal, "Token Originale", "good")}
          ${statusMetric("proxyBadge", tokenProxyTotal, "Token Proxies", "warn")}
          ${statusMetric("missing", tokenMissingTotal, "Fehlende Tokens", "bad")}
        </div>
        ${tokenAssignable ? `<button class="wide" type="button" onclick="assignFreeCopiesToDeck(null, 'tokens')">${tokenAssignable} freie Tokens zuweisen</button>` : ""}
        ${tokenAssignableRows.length ? `
          <div class="assign-list">
            ${tokenAssignableRows.map((item) => `
              <button class="assign-row" type="button" onclick="assignFreeCopiesToDeck(${item.card_id}, 'tokens')">
                <span>${escapeHtml(item.name)}</span>
                <small>${Math.min(item.missing, item.free_in_collection + (item.allow_proxy ? item.free_proxy_in_collection : 0))} zuweisen</small>
              </button>
            `).join("")}
          </div>
        ` : ""}
      </section>
    ` : ""}
  `;
}

function requiredTokensBlock(tokens) {
  if (!tokens.length) return "";
  const missingCount = tokens.filter((token) => token.missing > 0).length;
  return `
    <section class="required-token-block">
      <div class="required-token-head">
        <div>
          <h3>Benötigte Tokens</h3>
          <small>Mindestens 1 je Token-Art</small>
        </div>
        <span class="${missingCount ? "bad" : "good"}">${missingCount ? `${missingCount} offen` : "Vollständig"}</span>
      </div>
      <div class="required-token-list">
        ${tokens.map((token) => {
          const status = token.originals > 0
            ? `${token.originals} Original${token.originals === 1 ? "" : "e"}`
            : token.proxies > 0
              ? `${token.proxies} Proxy`
              : "Noch benötigt";
          const tone = token.originals > 0 ? "good" : token.proxies > 0 ? "warn" : "bad";
          return `
            <article class="required-token-row">
              ${token.image_url ? `<img src="${escapeHtml(token.image_url)}" alt="">` : `<span class="required-token-placeholder">T</span>`}
              <div class="required-token-info">
                <strong>${escapeHtml(token.name)}</strong>
                <small>${escapeHtml(tokenPrintIdentifier(token))}</small>
                <small>Erzeugt durch: ${token.source_names.map(escapeHtml).join(", ")}</small>
              </div>
              <span class="required-token-state ${tone}">${status}</span>
              ${Number(token.listed_quantity || 0) === 0 ? `<button class="secondary" type="button" onclick="addToDeckFlow(${token.card_id}, event)">Zum Deck</button>` : `<small class="required-token-listed">${token.listed_quantity}x eingeplant</small>`}
            </article>`;
        }).join("")}
      </div>
    </section>`;
}

function accessoriesBlock(items, publicView = false) {
  if (!items.length) return "";
  const categories = [
    ["ability_counter", "Fähigkeitsmarker", "A"],
    ["counter", "Weitere Marker", "+"],
    ["game_aid", "Weitere Spielhilfen", "Z"],
  ];
  return `
    <section class="accessory-block${publicView ? " public-accessory-block public-deck-section" : ""}">
      <div class="accessory-head">
        <div><h3>Zubehör</h3></div>
        <span>${items.length} Hinweise</span>
      </div>
      ${categories.map(([key, label, symbol]) => {
        const matches = items.filter((item) => item.category === key);
        if (!matches.length) return "";
        return `
          <div class="accessory-group">
            <h4>${label}</h4>
            <div class="accessory-list">
              ${matches.map((item) => `
                <article class="accessory-row">
                  <span class="accessory-symbol accessory-${key}">${symbol}</span>
                  <div><strong>${escapeHtml(item.name)}</strong><small>Benötigt durch: ${item.source_names.map(escapeHtml).join(", ")}</small></div>
                </article>`).join("")}
            </div>
          </div>`;
      }).join("")}
    </section>`;
}

function statusMetric(icon, value, label, tone) {
  return `
    <span class="status-metric ${tone}" title="${escapeHtml(label)}" aria-label="${escapeHtml(`${value} ${label}`)}">
      ${iconSvg(icon)}
      <span class="status-metric-copy"><strong>${value}</strong><small>${escapeHtml(label)}</small></span>
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
          <span><strong>${item.quantity}x</strong> ${escapeHtml(item.name)}${item.zone === "sideboard" ? " (Sideboard)" : ""}</span>
          <span>Cardmarket</span>
        </a>
      `).join("")}
    </div>
  `;
}

async function assignFreeCopiesToDeck(cardId = null, scope = "cards") {
  const deckId = selectedDeckId();
  if (!deckId) return;
  const result = await api(`/api/decks/${deckId}/assign-free`, {
    method: "POST",
    body: JSON.stringify({ card_id: cardId, scope }),
  });
  toast(result.assigned_count ? `${result.assigned_count} freie Karten zugewiesen.` : "Keine passenden freien Karten gefunden.");
  await Promise.all([loadCollection(), loadDeck(), loadPlanning()]);
}

async function deleteSlot(slotId) {
  const deckId = selectedDeckId();
  const result = await api(`/api/decks/${deckId}/slots/${slotId}`, { method: "DELETE" });
  if (result.freed_card_id && result.counts) {
    updateGlobalCopyCounts(result.freed_card_id, result.counts);
  }
  await loadDeck();
  await loadPlanning();
}

async function decrementSlot(slotId, event = null) {
  const deckId = selectedDeckId();
  if (!deckId) return;
  await withActionButton(event, async () => {
    const result = await api(`/api/decks/${deckId}/slots/${slotId}/decrement`, { method: "POST" });
    if (result.freed_card_id && result.counts) {
      updateGlobalCopyCounts(result.freed_card_id, result.counts);
    }
    toast(result.removed ? "Karte aus dem Deck entfernt." : `Noch ${result.remaining_quantity}x im Deck.`);
    await Promise.all([loadDeck(), loadPlanning()]);
  }).catch((error) => toast(error.message));
}

async function exportDeck(deckId = null) {
  deckId = deckId || selectedDeckId();
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
  toast("Vollbackup wird vorbereitet.");
}

function downloadUserBackup() {
  window.location.href = "/api/backups/user-data";
  toast("Datenbackup wird vorbereitet.");
}

async function importUserBackup(event) {
  const file = $("userBackupImportFile").files[0];
  if (!file) {
    toast("Bitte zuerst ein Datenbackup auswaehlen.");
    return;
  }
  if (!confirm("Datenbackup wirklich importieren? Sammlung und Decks werden ersetzt. Scryfall kannst du danach neu laden.")) return;
  await withActionButton(event, async () => {
    const response = await fetch("/api/backups/user-data/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: file,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    const result = await response.json();
    $("userBackupImportFile").value = "";
    const copies = result.counts?.card_copies ?? 0;
    const decks = result.counts?.decks ?? 0;
    toast(`Datenbackup importiert: ${copies} Kopien, ${decks} Decks.`);
    await refreshBasics();
    await Promise.all([loadCollection(true), loadDecks(), loadPlanning(), loadCollectionStats()]);
    await loadDeck();
  }).catch((error) => toast(error.message));
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

window.openCardDetail = openCardDetail;
window.addToDeckFlow = addToDeckFlow;
window.quickAddCopy = quickAddCopy;
window.addOriginalToDeck = addOriginalToDeck;
window.patchCopy = patchCopy;
window.deleteCopy = deleteCopy;
window.moveCopyToCollection = moveCopyToCollection;
window.resolveDecision = resolveDecision;
window.selectDeck = selectDeck;
window.exportDeck = exportDeck;
window.editDeck = editDeck;
window.deleteDeck = deleteDeck;
window.setDeckCover = setDeckCover;
window.decrementSlot = decrementSlot;
window.deleteSlot = deleteSlot;
window.moveSlotZone = moveSlotZone;
window.showCardPreview = showCardPreview;
window.moveCardPreview = moveCardPreview;
window.hideCardPreview = hideCardPreview;
window.toggleCardTag = toggleCardTag;

init().catch((error) => toast(error.message));
