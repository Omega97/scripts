const $ = (sel) => document.querySelector(sel);

let activeQuery = "";
let sort = "date";
let order = "desc";
let randomSeed = "";
let tagsCache = [];

let rows = 3;
let columns = 4;
let fitMode = "center";

let currentPage = 1;
let total = 0;
let pages = 0;
let selectedHash = null;
let selectedEntry = null;
let currentResults = [];
const pageCache = new Map();

let selectedHashes = new Set();
let orderedHashes = [];
let rangeAnchor = null;

const ac = { prefix: "", matches: [], idx: 0, active: false };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function clampInt(v, min, max) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return min;
  return Math.max(min, Math.min(max, n));
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function extractKeywords(text) {
  const tokens = (text || "").toUpperCase().match(/\(|\)|AND|OR|NOT|[A-Z0-9_-]+/g) || [];
  const seen = [];
  const out = [];
  for (const t of tokens) {
    if (t === "(" || t === ")" || t === "AND" || t === "OR" || t === "NOT") continue;
    const term = t.toLowerCase();
    if (!seen.includes(term)) { seen.push(term); out.push(term); }
  }
  return out;
}

function currentPartial() {
  const el = $("#search-input");
  const before = el.value.slice(0, el.selectionStart ?? el.value.length);
  const m = before.match(/[^\s()]+$/);
  return m ? m[0] : "";
}

function matchingTags(partial) {
  const p = (partial || "").toLowerCase();
  if (!p) return [];
  return tagsCache.filter((t) => t.startsWith(p)).slice(0, 20);
}

function replacePartial(replacement) {
  const el = $("#search-input");
  const pos = el.selectionStart ?? el.value.length;
  const before = el.value.slice(0, pos);
  const after = el.value.slice(pos);
  const m = before.match(/[^\s()]+$/);
  const start = m ? before.length - m[0].length : before.length;
  const newBefore = before.slice(0, start) + replacement;
  el.value = newBefore + after;
  const caret = newBefore.length;
  el.setSelectionRange(caret, caret);
  el.focus();
}

function renderAutocomplete() {
  const box = $("#autocomplete");
  const partial = currentPartial();
  const matches = matchingTags(partial);
  if (!partial || !matches.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = "";
  const highlight = ac.active ? ac.idx % matches.length : 0;
  matches.forEach((t, i) => {
    const item = document.createElement("div");
    item.className = "ac-item" + (i === highlight ? " active" : "");
    item.textContent = t;
    item.addEventListener("mousedown", (e) => {
      e.preventDefault();
      replacePartial(t);
      box.classList.add("hidden");
      doSearch($("#search-input").value.trim());
    });
    box.appendChild(item);
  });
}

function renderTags(container, tags, hash) {
  container.innerHTML = "";
  for (const t of tags) {
    const span = document.createElement("span");
    span.className = "tag";
    span.textContent = t;
    span.title = "left-click: add to search — right-click: remove";
    span.addEventListener("click", () => addKeyword(t));
    span.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      removeTagFromImage(hash, t);
    });
    container.appendChild(span);
  }
}

/* ---------- pagination ---------- */

function pageSize() { return rows * columns; }

function buildSearchURL(page, focus) {
  let url = `/api/search?q=${encodeURIComponent(activeQuery)}&sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}&page=${page}&page_size=${pageSize()}`;
  if (sort === "random" && randomSeed) url += `&seed=${encodeURIComponent(randomSeed)}`;
  if (focus) url += `&focus=${encodeURIComponent(focus)}`;
  return url;
}

async function fetchPage(page) {
  if (pageCache.has(page)) return pageCache.get(page);
  const data = await api(buildSearchURL(page));
  pageCache.set(page, data);
  return data;
}

function prefetchPage(page) {
  if (page >= 1 && page <= pages && !pageCache.has(page)) {
    fetchPage(page).catch(() => {});
  }
}

function applyGrid() {
  const grid = $("#results");
  grid.style.gridTemplateColumns = `repeat(${columns}, 1fr)`;
  grid.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
}

function applyFit() {
  const grid = $("#results");
  grid.classList.remove("fit-center", "fit-top", "fit-contain");
  grid.classList.add("fit-" + fitMode);
}

function renderTiles(results) {
  currentResults = results || [];
  const box = $("#results");
  box.innerHTML = "";
  if (!currentResults.length) {
    box.innerHTML = '<p class="muted empty">No results.</p>';
    return;
  }
  for (const r of currentResults) {
    const tile = document.createElement("div");
    tile.className = "tile"
      + (selectedHashes.has(r.hash) ? " selected" : "")
      + (r.hash === selectedHash ? " main" : "");
    tile.dataset.hash = r.hash;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = r.primary_path || "";
    if (r.preview_url) img.src = r.preview_url;
    tile.appendChild(img);
    tile.addEventListener("click", (e) => selectAsset(r, e.ctrlKey || e.metaKey));
    box.appendChild(tile);
  }
}

function selectAsset(r, additive = false) {
  if (additive) {
    if (selectedHashes.has(r.hash)) {
      selectedHashes.delete(r.hash);
      if (selectedHash === r.hash) {
        selectedHash = null;
        const rest = [...selectedHashes];
        if (rest.length) {
          selectedHash = rest[rest.length - 1];
          const main = currentResults.find((x) => x.hash === selectedHash);
          if (main) showDetail(main);
          else { selectedEntry = null; clearDetailVisuals(); }
        } else {
          hideDetail();
        }
      }
    } else {
      selectedHashes.add(r.hash);
      selectedHash = r.hash;
      showDetail(r);
    }
  } else {
    selectedHashes = new Set([r.hash]);
    selectedHash = r.hash;
    showDetail(r);
  }
  rangeAnchor = null;
  afterSelectionChange();
}

function syncTileSelection() {
  document.querySelectorAll(".tile").forEach((t) => {
    t.classList.toggle("selected", selectedHashes.has(t.dataset.hash));
    t.classList.toggle("main", t.dataset.hash === selectedHash);
  });
}

function afterSelectionChange() {
  syncTileSelection();
  updateSelectionInfo();
  updateCumulativeTags();
}

function showDetail(r) {
  selectedEntry = r;
  $("#detail-thumb").src = r.preview_url || "";
  $("#detail-thumb").classList.remove("hidden");
  $("#detail-placeholder").classList.add("hidden");
  $("#detail-name").textContent = r.primary_path || r.name || "";
  const extra = (r.paths || []).slice(1);
  $("#detail-paths").textContent = extra.join("\n");
  renderTags($("#detail-tags"), r.visible_tags, r.hash);
}

function clearDetailVisuals() {
  $("#detail-thumb").classList.add("hidden");
  $("#detail-placeholder").classList.remove("hidden");
  $("#detail-name").textContent = "";
  $("#detail-paths").textContent = "";
  renderTags($("#detail-tags"), [], null);
  $("#selection-info").classList.add("hidden");
  $("#selection-tags").classList.add("hidden");
  $("#selection-tags").innerHTML = "";
}

function clearSelection() {
  selectedHashes = new Set();
  selectedHash = null;
  selectedEntry = null;
  rangeAnchor = null;
  clearDetailVisuals();
}

function hideDetail() {
  clearSelection();
}

function updateSelectionInfo() {
  const el = $("#selection-info");
  const n = selectedHashes.size;
  if (n > 1) {
    el.textContent = `${n} images selected`;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

async function updateCumulativeTags() {
  const box = $("#selection-tags");
  if (!selectedHashes.size) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  try {
    const data = await api("/api/assets/tags-union", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hashes: [...selectedHashes] }),
    });
    box.innerHTML = "";
    if (!data.tags.length) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    for (const t of data.tags) {
      const span = document.createElement("span");
      span.className = "tag sel-tag";
      span.title = "click to add to search";
      span.innerHTML = t.count > 1
        ? `${esc(t.tag)}<span class="sel-count">${t.count}</span>`
        : esc(t.tag);
      span.addEventListener("click", () => addKeyword(t.tag));
      box.appendChild(span);
    }
  } catch (_) {
    box.classList.add("hidden");
    box.innerHTML = "";
  }
}

function updatePager() {
  $("#prev-btn").disabled = currentPage <= 1;
  $("#next-btn").disabled = pages === 0 || currentPage >= pages;
  $("#page-indicator").textContent = pages ? `${currentPage} / ${pages}` : "0 / 0";
}

async function renderPage(page) {
  const data = await fetchPage(page);
  renderPageData(data);
}

function renderPageData(data) {
  pageCache.set(data.page, data);
  currentPage = data.page;
  total = data.total;
  pages = data.pages;
  if (Array.isArray(data.hashes)) orderedHashes = data.hashes;
  renderTiles(data.results);
  updatePager();
  const selected = data.results.find((r) => r.hash === selectedHash);
  if (selected) {
    showDetail(selected);
  } else if (!selectedHash) {
    hideDetail();
  } else if (selectedEntry && selectedEntry.hash === selectedHash) {
    showDetail(selectedEntry);
  }
  prefetchPage(currentPage - 1);
  prefetchPage(currentPage + 1);
}

function goToPage(page) {
  if (page < 1 || (pages && page > pages)) return;
  renderPage(page).catch((e) => alert(e.message));
}

async function navigate(dir) {
  if (!currentResults.length) return;
  let localIndex = currentResults.findIndex((r) => r.hash === selectedHash);
  if (localIndex === -1) {
    const r = currentResults[dir < 0 ? currentResults.length - 1 : 0];
    if (r) selectAsset(r);
    return;
  }
  localIndex += dir;
  const size = rows * columns;
  const globalIndex = (currentPage - 1) * size + localIndex;
  const clamped = Math.max(0, Math.min(total - 1, globalIndex));
  const targetPage = Math.floor(clamped / size) + 1;
  const targetLocal = clamped % size;
  if (targetPage !== currentPage) {
    await renderPage(targetPage);
  }
  const r = currentResults[targetLocal];
  if (r) selectAsset(r);
}

async function rangeSelect(dir) {
  if (!orderedHashes.length) return;
  if (rangeAnchor === null) {
    rangeAnchor = orderedHashes.indexOf(selectedHash);
    if (rangeAnchor < 0) rangeAnchor = 0;
  }
  let cur = orderedHashes.indexOf(selectedHash);
  if (cur < 0) cur = rangeAnchor;
  const next = Math.max(0, Math.min(orderedHashes.length - 1, cur + dir));
  const lo = Math.min(rangeAnchor, next);
  const hi = Math.max(rangeAnchor, next);
  selectedHashes = new Set(orderedHashes.slice(lo, hi + 1));
  selectedHash = orderedHashes[next];

  const size = pageSize();
  const targetPage = Math.floor(next / size) + 1;
  if (targetPage !== currentPage) {
    try {
      await renderPage(targetPage);
    } catch (e) {
      alert(e.message);
    }
  }
  const main = currentResults.find((r) => r.hash === selectedHash);
  if (main) showDetail(main);
  afterSelectionChange();
}

/* ---------- tag edits ---------- */

async function addTagToImages(hashes, tag) {
  return api(`/api/assets/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hashes, tags: [tag], op: "add" }),
  });
}

async function removeTagFromImage(hash, tag) {
  try {
    await api(`/api/assets/${encodeURIComponent(hash)}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: [tag], op: "remove" }),
    });
  } catch (e) {
    alert(e.message);
  }
  refreshCurrent();
}

function addKeyword(term) {
  const el = $("#search-input");
  const terms = extractKeywords(el.value);
  if (terms.includes(term)) return;
  el.value = (el.value.trim() ? el.value.trim() + " " : "") + term;
  doSearch(el.value.trim());
}

/* ---------- data loading ---------- */

async function loadTags() {
  const data = await api("/api/tags");
  tagsCache = data.tags.map((t) => t.tag);
  const list = $("#tag-list");
  list.innerHTML = "";
  if (!data.tags.length) {
    list.innerHTML = '<p class="muted">No tags yet.</p>';
    return;
  }
  for (const t of data.tags) {
    const item = document.createElement("button");
    item.className = "tag-item" + (t.visible ? "" : " dim");
    item.type = "button";
    item.innerHTML = `<span>${esc(t.tag)}</span><span class="count">${t.count}</span>`;
    item.addEventListener("click", () => {
      $("#search-input").value = t.tag;
      doSearch(t.tag);
    });
    list.appendChild(item);
  }
}

async function doSearch(q) {
  activeQuery = q || "";
  pageCache.clear();
  const focus = selectedHash;
  let data;
  if (focus) {
    data = await api(buildSearchURL(1, focus));
  } else {
    data = await fetchPage(1);
  }
  if (focus && data.focus_found === false) {
    clearSelection();
    afterSelectionChange();
  }
  renderPageData(data);
}

async function refreshCurrent() {
  pageCache.clear();
  await loadTags();
  await renderPage(currentPage);
}

async function refreshAll() {
  await loadTags();
  await doSearch(activeQuery);
}

function defaultOrder(s) { return s === "date" ? "desc" : "asc"; }

function updateSortLabel() {
  $("#sort-btn").innerHTML = `Sort: ${sort} &#9662;`;
  $("#reverse-btn").title = order === "desc" ? "descending (click to reverse)" : "ascending (click to reverse)";
}

/* ---------- settings ---------- */

async function loadSettings() {
  const s = await api("/api/settings");
  $("#min-matches").value = s.min_tag_matches;
  $("#grid-rows").value = rows;
  $("#grid-cols").value = columns;
  $("#fit-mode").value = fitMode;
}

async function saveMinMatches() {
  const v = clampInt($("#min-matches").value, 1, 1000000);
  if (v < 1) return;
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ min_tag_matches: v }),
  });
  refreshAll();
}

function saveGrid() {
  rows = clampInt($("#grid-rows").value, 1, 50) || 3;
  columns = clampInt($("#grid-cols").value, 1, 50) || 4;
  localStorage.setItem("ts.rows", rows);
  localStorage.setItem("ts.columns", columns);
  $("#grid-rows").value = rows;
  $("#grid-cols").value = columns;
  applyGrid();
  pageCache.clear();
  renderPage(1).catch((e) => alert(e.message));
}

function saveFit() {
  fitMode = $("#fit-mode").value || "center";
  localStorage.setItem("ts.fit", fitMode);
  applyFit();
}

/* ---------- scan ---------- */

function showScanStatus(on) {
  $("#scan-status").classList.toggle("hidden", !on);
  $("#scan-db").disabled = on;
  $("#force-recompute").disabled = on;
  $("#scan-cancel").disabled = !on;
}

function setProgress(pct, label) {
  $("#progress-fill").style.width = pct + "%";
  $("#progress-label").textContent = label || "";
}

async function startScan() {
  showScanStatus(true);
  setProgress(0, "preparing…");
  try {
    await api("/api/scan", { method: "POST" });
  } catch (e) {
    $("#progress-label").textContent = e.message;
    return;
  }
  pollScan();
}

async function startRecomputeScan() {
  showScanStatus(true);
  setProgress(0, "preparing…");
  try {
    await api("/api/scan/recompute", { method: "POST" });
  } catch (e) {
    $("#progress-label").textContent = e.message;
    return;
  }
  pollScan();
}

async function pollScan() {
  const data = await api("/api/scan/status");
  if (data.running) {
    const pct = data.total ? Math.round((data.done / data.total) * 100) : 0;
    setProgress(pct, `${data.done} / ${data.total}`);
    setTimeout(pollScan, 400);
    return;
  }
  setProgress(100, "");
  const s = data.summary || {};
  if (s.error) {
    $("#progress-label").textContent = "error: " + s.error;
  } else if (s.cancelled) {
    $("#progress-label").textContent = "cancelled";
  } else {
    $("#progress-label").textContent = `done: ${s.assets ?? 0} assets, ${s.tags_total ?? 0} tags`;
  }
  showScanStatus(false);
  refreshAll();
}

async function cancelScan() {
  await api("/api/scan/cancel", { method: "POST" });
}

async function openSynonyms() {
  $("#settings-menu").classList.add("hidden");
  try {
    await api("/api/synonyms/open", { method: "POST" });
  } catch (e) {
    alert(e.message);
  }
}

/* ---------- wiring ---------- */

function toggleMenu(menu, force) {
  const show = force !== undefined ? force : menu.classList.contains("hidden");
  menu.classList.toggle("hidden", !show);
}

function closeMenus(except) {
  for (const m of [$("#settings-menu"), $("#sort-menu")]) {
    if (m !== except) m.classList.add("hidden");
  }
}

$("#search-btn").addEventListener("click", () => doSearch($("#search-input").value.trim()));
$("#search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    $("#autocomplete").classList.add("hidden");
    doSearch($("#search-input").value.trim());
  } else if (e.key === "Tab") {
    const partial = currentPartial();
    if (!partial) return;
    if (ac.active && ac.prefix && partial === ac.matches[ac.idx]) {
      ac.idx = (ac.idx + 1) % ac.matches.length;
    } else {
      ac.matches = matchingTags(partial);
      if (!ac.matches.length) return;
      ac.prefix = partial;
      ac.idx = 0;
      ac.active = true;
    }
    e.preventDefault();
    replacePartial(ac.matches[ac.idx]);
    renderAutocomplete();
  }
});
$("#search-input").addEventListener("input", () => {
  ac.active = false;
  renderAutocomplete();
});
$("#search-input").addEventListener("blur", () => {
  setTimeout(() => $("#autocomplete").classList.add("hidden"), 150);
});

$("#prev-btn").addEventListener("click", () => goToPage(currentPage - 1));
$("#next-btn").addEventListener("click", () => goToPage(currentPage + 1));

$("#detail-tag-input").addEventListener("keydown", (e) => { if (e.key === "Enter") addDetailTag(); });
$("#detail-delete").addEventListener("click", deleteSelected);
$("#detail-reveal").addEventListener("click", revealSelected);
$("#detail-rename").addEventListener("click", renameSelected);

async function addDetailTag() {
  const v = $("#detail-tag-input").value.trim();
  if (!v || !selectedHashes.size) return;
  const targets = [...selectedHashes];
  try {
    await addTagToImages(targets, v);
    $("#detail-tag-input").value = "";
    await refreshCurrent();
  } catch (e) {
    alert(e.message);
  }
}

async function renameSelected() {
  if (!selectedHash || !selectedEntry) return;
  const primary = selectedEntry.primary_path || "";
  const name = primary ? primary.split("/").pop() : "";
  const currentStem = name ? name.replace(/\.[^.]+$/, "") : "";
  const newStem = (window.prompt("Rename file (stem):", currentStem) || "").trim();
  if (!newStem || newStem === currentStem) return;
  try {
    await api(`/api/assets/${encodeURIComponent(selectedHash)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newStem }),
    });
    await refreshCurrent();
  } catch (e) {
    alert(e.message);
  }
}

function nextHashAfterDelete(targets) {
  if (!orderedHashes.length) return null;
  const deleteSet = new Set(targets);
  const firstIdx = orderedHashes.findIndex((h) => deleteSet.has(h));
  const anchorIdx = firstIdx >= 0 ? firstIdx : 0;
  const remaining = orderedHashes.filter((h) => !deleteSet.has(h));
  if (!remaining.length) return null;
  return remaining[Math.min(anchorIdx, remaining.length - 1)];
}

async function deleteSelected() {
  if (!selectedHashes.size) return;
  const targets = [...selectedHashes];
  const n = targets.length;
  if (!window.confirm(`Delete ${n} image${n > 1 ? "s" : ""}?`)) return;
  const nextHash = nextHashAfterDelete(targets);
  try {
    const result = await api("/api/assets/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hashes: targets }),
    });
    if (result.errors && result.errors.length) {
      alert(`Some files could not be deleted:\n${result.errors.join("\n")}`);
    }
    if (nextHash) {
      selectedHashes = new Set([nextHash]);
      selectedHash = nextHash;
      selectedEntry = null;
    } else {
      clearSelection();
    }
    await refreshAll();
  } catch (e) {
    alert(e.message);
  }
}

async function revealSelected() {
  if (!selectedHash) return;
  try {
    await api(`/api/assets/${encodeURIComponent(selectedHash)}/reveal`, {
      method: "POST",
    });
  } catch (e) {
    alert(e.message);
  }
}

$("#settings-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  closeMenus($("#settings-menu"));
  toggleMenu($("#settings-menu"));
  if (!$("#settings-menu").classList.contains("hidden")) loadSettings();
});
$("#sort-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  closeMenus($("#sort-menu"));
  toggleMenu($("#sort-menu"));
});
$("#reverse-btn").addEventListener("click", () => {
  order = order === "asc" ? "desc" : "asc";
  updateSortLabel();
  doSearch(activeQuery);
});
$("#scan-db").addEventListener("click", startScan);
$("#scan-cancel").addEventListener("click", cancelScan);
$("#force-recompute").addEventListener("click", startRecomputeScan);
$("#open-synonyms").addEventListener("click", openSynonyms);
$("#min-matches").addEventListener("change", saveMinMatches);
$("#grid-rows").addEventListener("change", saveGrid);
$("#grid-cols").addEventListener("change", saveGrid);
$("#fit-mode").addEventListener("change", saveFit);

document.querySelectorAll(".sort-option").forEach((btn) => {
  btn.addEventListener("click", () => {
    sort = btn.dataset.sort;
    order = defaultOrder(sort);
    if (sort === "random") randomSeed = Math.random().toString(36).slice(2);
    updateSortLabel();
    $("#sort-menu").classList.add("hidden");
    doSearch(activeQuery);
  });
});

document.addEventListener("click", () => closeMenus());
$("#settings-menu").addEventListener("click", (e) => e.stopPropagation());
$("#sort-menu").addEventListener("click", (e) => e.stopPropagation());

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (selectedHashes.size) {
      clearSelection();
      afterSelectionChange();
    }
    return;
  }
  if (e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      goToPage(currentPage - 1);
      return;
    }
    if (e.key === "ArrowRight") {
      e.preventDefault();
      goToPage(currentPage + 1);
      return;
    }
  }
  if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    let dir = 0;
    if (e.key === "ArrowLeft") dir = -1;
    else if (e.key === "ArrowRight") dir = 1;
    else if (e.key === "ArrowUp") dir = -columns;
    else if (e.key === "ArrowDown") dir = columns;
    if (dir !== 0) {
      e.preventDefault();
      rangeSelect(dir);
      return;
    }
  }
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  let dir = 0;
  if (e.key === "ArrowLeft") dir = -1;
  else if (e.key === "ArrowRight") dir = 1;
  else if (e.key === "ArrowUp") dir = -columns;
  else if (e.key === "ArrowDown") dir = columns;
  if (dir !== 0) {
    e.preventDefault();
    navigate(dir);
  }
});

document.addEventListener("keyup", (e) => {
  if (e.key === "Control" || e.key === "Meta") rangeAnchor = null;
});

/* ---------- resizable panels ---------- */

function initResizer(resizer, panel, dir, minW, maxW, key) {
  resizer.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = panel.getBoundingClientRect().width;
    resizer.classList.add("dragging");
    document.body.style.userSelect = "none";
    function onMove(ev) {
      const w = Math.max(minW, Math.min(maxW, startW + (ev.clientX - startX) * dir));
      panel.style.width = w + "px";
      localStorage.setItem(key, String(Math.round(w)));
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      resizer.classList.remove("dragging");
      document.body.style.userSelect = "";
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

function restoreWidths() {
  const rightMax = Math.floor(window.innerWidth * 0.7);
  const left = clampInt(localStorage.getItem("ts.leftW"), 120, 600);
  if (left) $("#tags-sidebar").style.width = left + "px";
  const right = clampInt(localStorage.getItem("ts.rightW"), 160, rightMax);
  if (right) $("#detail").style.width = right + "px";
}

initResizer($("#resizer-left"), $("#tags-sidebar"), 1, 120, 600, "ts.leftW");
initResizer($("#resizer-right"), $("#detail"), -1, 160, Math.floor(window.innerWidth * 0.7), "ts.rightW");

/* ---------- init ---------- */

rows = clampInt(localStorage.getItem("ts.rows"), 1, 50) || 3;
columns = clampInt(localStorage.getItem("ts.columns"), 1, 50) || 4;
fitMode = localStorage.getItem("ts.fit") || "center";
restoreWidths();
applyGrid();
applyFit();
updateSortLabel();
refreshAll()
  .then(() => {
    if (!selectedHash && currentResults.length) {
      selectAsset(currentResults[0]);
    }
  })
  .catch((e) => { $("#results").innerHTML = `<p class="error">${esc(e.message)}</p>`; });
