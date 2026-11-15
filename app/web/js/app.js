// NextCrop UI: form on the left, satellite map with the 5 arc-minute data cells, results from /api.
// Vietnamese and English: interface text in i18n.js, the generator's sentences come from the API (`lang`).
import * as api from "./api.js";
import {
  CLASSES, STEP, classOf, findProvince, provinceBounds, provinceCentroid, expandBounds, cellOf, cellRing,
  selectCells, nearestInside, countByClass, tradeoff, nameOf, esc, niceRange, linePath, bandPath, peakMonth,
} from "./lib.js";
import { LANGS, detectLang, getLang, setLangState, t } from "./i18n.js";

const $ = (id) => document.getElementById(id);
const MODE = "hrlm";                                           // rain-fed, high inputs (the API default)
const BUFFER_CELLS = 2;
const HEX = { c80: "#2e7d4f", c60: "#7fb069", c40: "#e3c04a", c20: "#e08a3c", c0: "#c8553d" };
const EXAMPLE = { shape: "An Giang", lat: 10.45, lon: 105.35, crop: "RCW", n: null };

const st = {
  ...EXAMPLE, lang: "vi", move: null, hide: new Set(), tab: "res", confirmed: false, outside: false,
  crops: [], features: null, result: null, error: null, loading: false, cells: [],
  cardTab: "sum", nasa: null, nasaState: "idle", nasaKey: null, nasaErr: null,   // right card: summary | nasa
  layerState: "idle",                                          // idle | loading | ready | empty | error (the cell layer)
  navSeq: 0,                                                   // a newer navigation cancels an older, slower one
};
let map, mapReady = false, pin;
let optSeq = 0, layerSeq = 0, langSeq = 0, optCtl = null, layerCtl = null;

// ---- browser memory (can be blocked: always wrapped)
const mem = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const save = () => {
  if (!st.confirmed) return;
  mem.set("fs.profile", JSON.stringify({ shape: st.shape, lat: st.lat, lon: st.lon, crop: st.crop, n: st.n }));
};
function loadProfile() {
  try {
    const p = JSON.parse(mem.get("fs.profile") || "null");
    if (p && st.crops.some((c) => c.crop_code === p.crop) && [null, 1, 2, 3].includes(p.n) && Number.isFinite(p.lat) && Number.isFinite(p.lon)) {
      Object.assign(st, { shape: p.shape ?? null, lat: p.lat, lon: p.lon, crop: p.crop, n: p.n, confirmed: true, outside: !p.shape });
      return true;
    }
  } catch { /* ignore */ }
  return false;
}

// ---- small helpers
const debounce = (fn, ms) => { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; };
const cropOf = (code) => st.crops.find((c) => c.crop_code === code);
const cropName = (code) => cropOf(code)?.name ?? cropOf(code)?.name_vi ?? code;
const note = (html, cls = "") => `<p class="note ${cls}">${html}</p>`;
const numOrNull = (el) => (el.value === "" ? null : Number(el.value));
const priorities = () => ["nitrogen", "pest_cycle", "yield"].filter((p) => $(`p-${p}`).checked);
const dot = (key) => `<i class="dot" style="background:var(--${key})"></i>`;
const rawNames = (name) => (st.features ?? []).filter((f) => nameOf(f) === name).map((f) => f.properties.shapeName);
const cls = (key) => t(`class.${key}`);
const prioName = (k) => { const x = t(`prio.name.${k}`); return x.startsWith("prio.name.") ? k : x; };

/** Put the interface language into the static HTML: text, aria-labels, titles, <html lang>, the meta description. */
function applyStatic() {
  document.documentElement.lang = getLang();
  const meta = document.querySelector('meta[name="description"]');
  if (meta) meta.content = t("page.desc");
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-attr]")) {
    for (const pair of el.dataset.i18nAttr.split(";")) { const [attr, key] = pair.split(":"); el.setAttribute(attr, t(key)); }
  }
}
function setStaticPops() {
  setPop("prio", `<h4>${t("pop.prioTitle")}</h4><p>${t("pop.prioBody1")}</p><p>${t("pop.prioBody2")}</p>`);
  setPop("disc", `<h4>${t("pop.discTitle")}</h4><p>${t("pop.discBody1")}</p><p>${t("pop.discBody2")}</p><p><button type="button" class="link" data-goto="as">${t("pop.seeAssump")}</button></p>`);
}

// ---- map
function selFilter() {
  const names = st.outside || !st.shape ? ["__none__"] : rawNames(st.shape);
  return ["in", ["get", "shapeName"], ["literal", names]];
}
function initMap() {
  map = new maplibregl.Map({
    container: "map", center: [106, 16], zoom: 5, attributionControl: { compact: true },
    style: {
      version: 8,
      sources: { sat: { type: "raster", tileSize: 256, maxzoom: 18, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"] } },
      layers: [{ id: "sat", type: "raster", source: "sat", paint: { "raster-saturation": -0.25, "raster-brightness-max": 0.82, "raster-contrast": 0.1 } }],
    },
  });
  map.on("load", () => {
    const empty = { type: "FeatureCollection", features: [] };
    map.addSource("cells", { type: "geojson", data: empty });
    map.addLayer({ id: "fill", type: "fill", source: "cells", paint: { "fill-color": ["get", "color"],
      "fill-opacity": ["case", ["==", ["get", "centre"], 1], 0.78, ["==", ["get", "inside"], 1], 0.55, 0.25] } });
    map.addLayer({ id: "line", type: "line", source: "cells", paint: { "line-color": "#ffffff", "line-opacity": 0.35, "line-width": 1 } });
    map.addLayer({ id: "sel", type: "line", source: "cells", filter: ["==", ["get", "centre"], 1], paint: { "line-color": "#ffffff", "line-width": 3 } });
    map.addSource("prov", { type: "geojson", data: st.features ? { type: "FeatureCollection", features: st.features } : empty });
    map.addLayer({ id: "prov-line", type: "line", source: "prov", paint: { "line-color": "#ffffff", "line-opacity": 0.75, "line-width": 1.2, "line-dasharray": [3, 2] } });
    map.addLayer({ id: "prov-sel", type: "line", source: "prov", filter: selFilter(), paint: { "line-color": "#ffd84d", "line-width": 3.5 } });
    pin = new maplibregl.Marker({ color: "#e8803a" }).setLngLat([st.lon, st.lat]).addTo(map);
    map.getCanvas().style.cursor = "crosshair";
    map.on("click", (e) => {
      if (swallowMapClick) { swallowMapClick = false; return; }  // this click only closed a popover
      pickPoint(e.lngLat.lat, e.lngLat.lng, "ease");
    });
    mapReady = true;
    drawCells();
    moveMap();
  });
}
function drawCells() {
  if (!mapReady) return;
  const centre = cellOf(st.lat, st.lon);
  const isCentre = (c) => c.i === centre.i && c.j === centre.j;
  const features = st.cells
    .filter((c) => isCentre(c) || !st.hide.has(classOf(c.index).key))
    .map((c) => ({ type: "Feature", properties: { color: HEX[classOf(c.index).key], centre: isCentre(c) ? 1 : 0, inside: c.inside ? 1 : 0 },
      geometry: { type: "Polygon", coordinates: [cellRing(c.lat, c.lon)] } }));
  map.getSource("cells").setData({ type: "FeatureCollection", features });
  map.getSource("prov").setData({ type: "FeatureCollection", features: st.features ?? [] });
  map.setFilter("prov-sel", selFilter());
  pin.setLngLat([st.lon, st.lat]);
}
function setCollapsed(side, on, { remember = true } = {}) {
  document.body.classList.toggle(`${side}-collapsed`, on);
  const b = $(`tgl-${side}`), cap = side === "left" ? "Left" : "Right";
  b.setAttribute("aria-expanded", String(!on));
  b.setAttribute("aria-label", t(`tgl.${on ? "show" : "hide"}${cap}`));
  b.title = t(`tgl.tip${cap}`);
  b.firstElementChild.textContent = (side === "left") === on ? "›" : "‹";
  if (remember) mem.set(`fs.${side}`, on ? "1" : "0");
}
function moveMap() {
  if (!mapReady || !st.move) return;                           // keep the request until the map is ready
  const how = st.move;
  st.move = null;
  if (how === "ease") { map.easeTo({ center: [st.lon, st.lat], duration: 600 }); return; }
  const b = st.features && st.shape ? provinceBounds(st.features, st.shape) : null;
  const pad = window.innerWidth > 760 && !document.body.classList.contains("left-collapsed") ? Math.min(440, window.innerWidth * 0.4) : 30;
  if (b) map.fitBounds(b, { padding: { top: 50, bottom: 70, left: pad, right: 60 }, maxZoom: 11, duration: how === "fit" ? 0 : 1600 });
  else map.flyTo({ center: [st.lon, st.lat], zoom: 9.5, duration: 1600 });
}

// ---- data loading
const params = () => ({
  lat: st.lat, lon: st.lon, crop: st.crop, mode: MODE, seasons: st.n, priorities: priorities(),
  min_index: $("minidx").value, gap_rice: numOrNull($("gr")), gap_other: numOrNull($("go")), lang: st.lang,
});

let nasaCtl = null;
function ensureNasa(force = false) {
  if (st.cardTab !== "nasa" || st.outside) return;
  const c = cellOf(st.lat, st.lon), key = `${c.i},${c.j}`;
  if (!force && st.nasaKey === key) return;
  st.nasaKey = key; st.nasaState = "loading"; st.nasaErr = null;
  renderCard();
  nasaCtl?.abort(); nasaCtl = new AbortController();
  api.nasa({ lat: st.lat, lon: st.lon }, nasaCtl.signal)
    .then((d) => { if (st.nasaKey === key) { st.nasa = d; st.nasaState = "ready"; renderCard(); } })
    .catch((e) => { if (e.name !== "AbortError" && st.nasaKey === key) { st.nasa = null; st.nasaErr = e; st.nasaState = "error"; renderCard(); } });
}

async function loadOptions() {
  const seq = ++optSeq;
  optCtl?.abort();
  optCtl = new AbortController();
  if (st.outside) { st.result = null; st.error = null; st.loading = false; renderAll(); return; }
  st.loading = true;
  renderResults();
  ensureNasa();
  try {
    const r = await api.options(params(), optCtl.signal);
    if (seq !== optSeq) return;
    st.result = r; st.error = null;
  } catch (e) {
    if (e.name === "AbortError" || seq !== optSeq) return;
    st.result = null; st.error = e;
  }
  st.loading = false;
  renderAll();
}
const loadOptionsSoon = debounce(loadOptions, 250);

async function loadLayer() {
  const seq = ++layerSeq;
  layerCtl?.abort();
  layerCtl = new AbortController();
  const b = st.features && st.shape && !st.outside ? provinceBounds(st.features, st.shape) : null;
  if (!b) { st.cells = []; st.layerState = "idle"; drawCells(); renderCard(); return; }
  const [[west, south], [east, north]] = expandBounds(b, BUFFER_CELLS * STEP + 0.02);
  st.layerState = "loading";
  renderCard();
  try {
    const r = await api.cells({ west, south, east, north, crop: st.crop, mode: MODE, limit: 6000 }, layerCtl.signal);
    if (seq !== layerSeq) return;
    st.cells = selectCells(r.cells, st.features, st.shape, BUFFER_CELLS);
    st.layerState = st.cells.length ? "ready" : "empty";
  } catch (e) {
    if (e.name === "AbortError" || seq !== layerSeq) return;
    st.cells = []; st.layerState = "error";                     // the map layer is optional: results still work
  }
  drawCells();
  renderCard();
}

/** A point chosen on the map or by geolocation. Province comes from the boundary file; outside Vietnam is refused (DATA-14). */
function pickPoint(lat, lon, move, { confirm = true } = {}) {
  if (!st.features) { st.error = { code: "no_boundaries" }; renderResults(); return; }
  const name = findProvince(lon, lat, st.features);
  const changed = name !== st.shape;
  st.navSeq++;                                                  // cancels a province change still waiting for its cells
  Object.assign(st, { lat, lon, shape: name, outside: !name, move, confirmed: st.confirmed || confirm });
  $("prov").value = name ?? "";
  if (changed) { st.cells = []; st.hide.clear(); loadLayer(); } else drawCells();
  moveMap();
  loadOptions();
  save();
  renderAll();
}

/** A province chosen from the list: the point becomes the data cell inside it that is nearest to its centroid. */
async function goToProvince(name) {
  const mine = ++st.navSeq;
  Object.assign(st, { shape: name, outside: false, cells: [], move: "fly", confirmed: true });
  st.hide.clear();
  $("prov").value = name;
  await loadLayer();
  if (mine !== st.navSeq) return;                               // the user chose something else meanwhile
  const c0 = provinceCentroid(st.features, name);
  const hit = c0 ? nearestInside(st.cells, c0.lat, c0.lon) : null;
  if (hit) Object.assign(st, { lat: hit.lat, lon: hit.lon });
  else if (c0) Object.assign(st, { lat: c0.lat, lon: c0.lon });
  drawCells();
  moveMap();
  loadOptions();
  save();
  renderAll();
}

function setCrop(code) {
  st.crop = code; st.confirmed = true;
  st.hide.clear();                                              // another crop has another spread of classes
  loadLayer();
  loadOptions();
  save();
  renderChips();
}

// ---- rendering
function renderAll() { renderChips(); renderResults(); renderCrops(); renderCard(); renderLegend(); renderPlace(); renderAssumptions(); }

function renderPlace() {
  const area = st.result?.location?.cell_area_km2;
  const where = st.shape ?? t("place.outside");
  $("place").innerHTML = `${esc(where)} · <span class="dtl">${st.lat.toFixed(3)}°N ${st.lon.toFixed(3)}°E · </span>${esc(t("place.cell", { area: area ?? "80–85" }))}`;
}
function renderChips() {
  $("mc-loc").textContent = st.outside ? t("chip.noLoc") : st.shape ?? "…";
  $("mc-crop").textContent = cropName(st.crop);
  $("mc-n").textContent = st.n ? t("chip.seasonsN", { n: st.n })
    : st.result ? t("chip.seasonsAutoN", { n: st.result.seasons }) : t("chip.seasonsAuto");
}

function errorHtml(e) {
  const retry = ` <button type="button" class="small" data-retry>${t("retry")}</button>`;
  if (e.code === "no_data") return note(t("err.noData"));
  if (e.code === "outside_grid") return note(t("err.outsideGrid"));
  if (e.code === "no_boundaries") return note(t("err.noBoundaries"));
  if (["network", "db_unavailable", "db_not_configured"].includes(e.code) || e.status >= 500) return note(`${t("err.server")}${retry}`, "err");
  return note(`${t("err.generic")} (${esc(e.code ?? "")})`, "err");
}
const chipHtml = (e) => {
  const c = classOf(e.gaez_index);
  return `<span class="chip" title="${esc(e.gaez_class)}">${dot(c.key)}${esc(e.name ?? e.name_vi)} <small>${cls(c.key)}<span class="dtl"> · ${e.gaez_index}</span></small></span>`;
};

// ---- "i" popovers: extra information stays out of the way until asked for (click, so it works on a phone too)
const pops = {};
const setPop = (key, html) => { pops[key] = html; };
const infoBtn = (key, tone = "") => `<button type="button" class="info ${tone}" data-pop="${key}" aria-label="${esc(t("info.more"))}" aria-haspopup="dialog">i</button>`;
let popKey = null, swallowMapClick = false;
function closePop() {
  $("pop").hidden = true; popKey = null;
  document.querySelectorAll("[data-pop][aria-expanded]").forEach((b) => b.removeAttribute("aria-expanded"));
}
function openPop(btn) {
  const key = btn.dataset.pop;
  if (!pops[key]) return;
  if (popKey === key && !$("pop").hidden) { closePop(); return; }
  closePop();
  popKey = key;
  $("pop-body").innerHTML = pops[key];
  const el = $("pop");
  el.hidden = false;
  const r = btn.getBoundingClientRect(), w = el.offsetWidth, hgt = el.offsetHeight;
  const panel = btn.closest(".panel");
  let left, top;
  if (panel && window.innerWidth > 760) {                       // beside the panel, so the text being read stays visible
    left = panel.getBoundingClientRect().right + 12;
    top = Math.min(Math.max(12, r.top - 8), Math.max(12, window.innerHeight - hgt - 12));
  } else {
    left = Math.min(Math.max(12, r.left - 8), Math.max(12, window.innerWidth - w - 12));
    top = r.bottom + 8;
    if (top + hgt > window.innerHeight - 12) top = Math.max(12, r.top - hgt - 8);
  }
  el.style.left = `${left}px`; el.style.top = `${top}px`;
  btn.setAttribute("aria-expanded", "true");
}
const waterWord = (w) => (w === "wetland" ? t("ev.wetland") : w === "upland" ? t("ev.upland") : "");
function evidenceTable(o) {
  const seen = new Set();
  const rows = o.evidence.filter((e) => !seen.has(e.crop_code) && seen.add(e.crop_code)).map((e) => {
    const c = classOf(e.gaez_index);
    return `<tr><td>${esc(e.name ?? e.name_vi)}<span class="src">${esc(e.family)}${e.is_legume ? t("ev.legume") : ""}; ${esc(waterWord(e.water_regime))}</span></td><td>${dot(c.key)} ${cls(c.key)} (${esc(e.gaez_index)})</td><td>${esc(t("ev.days", { n: e.cycle_days_min }))}</td></tr>`;
  }).join("");
  return `<table><tr><th>${t("ev.crop")}</th><th>${t("ev.suit")}</th><th>${t("ev.cycle")}</th></tr>${rows}</table>`;
}
const list = (cl, items) => `<ul class="${cl}">${items.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`;
function optionPop(o) {
  const c = o.components;
  const cycle = t(c.fits_year ? "pt.cycleFits" : "pt.cycleNoFit", { days: c.cycle_days_total, buf: c.days_with_buffer, slack: c.slack_days, mean: c.gaez_mean });
  return `<h4>${esc(o.label)}</h4>
    ${o.benefits.length ? `<div class="pt">${t("pt.benefits")}</div>${list("bn", o.benefits)}` : ""}
    ${o.risks.length ? `<div class="pt">${t("pt.risks")}</div>${list("rk", o.risks)}` : ""}
    <div class="pt">${t("pt.perCrop")}</div>${evidenceTable(o)}
    <p class="hint">${esc(cycle)}</p>
    <p class="hint">${esc(t("pt.source", { src: o.evidence_source }))}</p>`;
}

function renderResults() {
  const box = $("res-body"), title = $("res-title");
  box.classList.toggle("busy", st.loading && !!st.result);
  closePop();
  $("res-info").innerHTML = "";
  const plain = () => { title.textContent = t("res.titleDefault"); $("tab-res").textContent = t("tab.res"); };
  if (st.outside) { plain(); box.innerHTML = note(t("res.outside")); return; }
  if (st.error) { plain(); box.innerHTML = errorHtml(st.error); return; }
  const r = st.result;
  if (!r) { title.textContent = t("res.titleDefault"); box.innerHTML = `<p class="hint">${t("res.computing")}</p>`; return; }
  if (r.message) {
    title.textContent = cropName(st.crop); $("tab-res").textContent = t("tab.res");
    box.innerHTML = note(esc(r.message)) + `<p class="hint">${t("res.perennialHint")}</p>`;
    return;
  }
  const keep = r.options[0], fh = r.floor_hint;
  $("tab-res").textContent = t("res.tabN", { n: r.options.length });
  title.textContent = t("res.title", { n: r.options.length, crop: cropName(st.crop).toLowerCase(), prov: st.shape });

  // one popover for how the options are made (and the ones that could not be made)
  setPop("title", `<h4>${t("pop.aboutTitle")}</h4><p>${esc(r.note)}</p>`
    + (r.ranked_by.length ? `<p>${esc(t("pop.rankedBy", { what: r.ranked_by.map((p) => p.meaning).join("; ") }))}</p>` : "")
    + `<p>${esc(r.principle)}</p>`
    + (r.skipped.length ? `<div class="pt">${t("pop.skipped")}</div>${list("assump", r.skipped.map((q) => q.reason))}` : ""));
  $("res-info").innerHTML = infoBtn("title");

  // alerts: one short line in compact mode, the full text in the popover
  const unsupported = r.unsupported_priorities.map((u) => t("pop.unsupported", { p: prioName(u.priority), reason: u.reason }));
  const alerts = [...r.warnings, ...unsupported, ...(fh ? [fh.message] : [])];
  let h = "";
  if (alerts.length) {
    setPop("alerts", `<h4>${t("pop.notes")}</h4>${list("assump", alerts)}`);
    const floorBtn = fh?.min_index != null ? ` <button type="button" class="small" data-floor="${esc(fh.min_index)}">${esc(t("btn.useFloor", { v: fh.min_index }))}</button>` : "";
    const short = fh ? t("alert.few", { n: r.options.length }) : t("alert.note");
    h += `<div class="note" data-pop="alerts" role="button" tabindex="0" aria-haspopup="dialog">${esc(short)}${floorBtn}</div>`;
  }

  h += r.options.map((o) => {
    const cmp = o.components, tr = o.id === "keep" ? null : tradeoff(cmp.gaez_mean - keep.components.gaez_mean);
    const arrow = { up: "▲", down: "▼", same: "＝" };
    const key = `opt-${o.id}`;
    setPop(key, optionPop(o));
    const bad = o.evidence.some((e) => e.gaez_index < 4000);
    const tone = bad ? "bad" : o.risks.length ? "warn" : o.benefits.length ? "ok" : "";
    const badges = [
      o.benefits.length ? `<button type="button" class="bd ok" data-pop="${key}">${esc(t("badge.benefits", { n: o.benefits.length }))}</button>` : "",
      bad ? `<button type="button" class="bd bad" data-pop="${key}">${esc(t("badge.bad"))}</button>`
        : (o.risks.length ? `<button type="button" class="bd warn" data-pop="${key}">${esc(t("badge.risks", { n: o.risks.length }))}</button>` : ""),
    ].join("");
    return `<div class="opt ${o.id === "keep" ? "keep" : ""} t-${tone || "none"}" data-pop="${key}" role="button" tabindex="0" aria-haspopup="dialog" aria-label="${esc(t("opt.aria", { label: o.label }))}">
      <h3>${esc(o.label)}${o.id === "keep" ? `<span class="tag">${t("opt.current")}</span>` : ""}</h3>
      <div class="seasons">${o.evidence.map(chipHtml).join("")}</div>
      ${tr ? `<p class="trade ${tr.dir}">${arrow[tr.dir]} ${esc(t(tr.key))}<span class="dtl"> (${tr.delta > 0 ? "+" : ""}${tr.delta})</span></p>` : `<p class="trade same">${t("opt.baseline")}</p>`}
      ${badges ? `<div class="badges">${badges}</div>` : ""}
    </div>`;
  }).join("");

  box.innerHTML = h;
}

function renderCrops() {
  const idx = st.result?.cell_indices ?? {};
  const level = (code) => {
    const v = idx[code];
    if (v == null) return `<span class="hint">${t("crops.none")}</span>`;
    const c = classOf(v);
    return `${dot(c.key)}<span>${cls(c.key)}</span><span class="dtl">${v}</span>`;
  };
  const label = (c) => c.name ?? c.name_vi;
  const row = (c) => `<button type="button" role="radio" aria-checked="${c.crop_code === st.crop}" data-c="${esc(c.crop_code)}">${esc(label(c))}${c.name_verified ? "" : '<span class="dtl"> *</span>'}<span class="v">${level(c.crop_code)}</span></button>`;
  const byIdx = (a, b) => (idx[b.crop_code] ?? -1) - (idx[a.crop_code] ?? -1) || label(a).localeCompare(label(b), getLang());
  const annual = st.crops.filter((c) => c.rotatable).sort(byIdx), perennial = st.crops.filter((c) => !c.rotatable).sort(byIdx);
  $("crops").innerHTML = `<div class="grp">${t("sel.annual")}</div>${annual.map(row).join("")}`
    + `<div class="grp">${t("sel.perennial")}</div>${perennial.map(row).join("")}`;
}

// ---- right card: "Summary" (cells by level) and "NASA" (climate and greenness of the place), one card, two tabs
const cardTabs = () => {
  const tab = (k, key) => `<button type="button" role="tab" data-ctab="${k}" aria-selected="${st.cardTab === k}">${t(key)}</button>`;
  return `<div class="ctabs" role="tablist">${tab("sum", "card.tabSum")}${tab("nasa", "card.tabNasa")}</div>`;
};
const monthName = (m) => new Intl.DateTimeFormat(getLang(), { month: "long" }).format(new Date(2021, m - 1, 1));

/** One small chart of 12 months: a line with a min-max band, or bars. Values per month number (1-12), null if missing. */
function chartSvg({ mean, lo, hi, bars, color, aria, zero = false, digits = 0 }) {
  const W = 380, H = 136, L = 38, R = 8, TOP = 8, BOT = 20;
  const all = [...Object.values(bars ?? mean), ...Object.values(lo ?? {}), ...Object.values(hi ?? {})].filter(Number.isFinite);
  const ax = niceRange(Math.min(...all), Math.max(...all), 5, zero);
  const slot = (W - L - R) / 12;
  const x = (m) => L + slot * (m - 0.5), y = (v) => TOP + (1 - (v - ax.min) / (ax.max - ax.min)) * (H - TOP - BOT);
  const pts = (obj) => Array.from({ length: 12 }, (_, i) => (Number.isFinite(obj?.[i + 1]) ? { x: x(i + 1), y: y(obj[i + 1]) } : null));
  const grid = ax.ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="gl"/><text x="${L - 5}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${v.toFixed(digits)}</text>`).join("");
  const xs = Array.from({ length: 12 }, (_, i) => `<text x="${x(i + 1).toFixed(1)}" y="${H - 5}" text-anchor="middle">${i + 1}</text>`).join("");
  let body = "";
  if (bars) {
    body = Object.entries(bars).map(([m, v]) => `<rect x="${(x(+m) - slot * 0.34).toFixed(1)}" y="${y(v).toFixed(1)}" width="${(slot * 0.68).toFixed(1)}" height="${(y(ax.min) - y(v)).toFixed(1)}" fill="${color}"><title>${monthName(+m)}: ${v}</title></rect>`).join("");
  } else {
    const band = lo && hi ? bandPath(pts(hi), pts(lo)) : "";
    body = (band ? `<path d="${band}" fill="${color}" opacity=".18"/>` : "")
      + `<path d="${linePath(pts(mean))}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round"/>`
      + pts(mean).map((p, i) => (p ? `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.6" fill="${color}"><title>${monthName(i + 1)}: ${mean[i + 1]}</title></circle>` : "")).join("");
  }
  return `<svg class="nchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}">${grid}${body}${xs}</svg>`;
}
const byMonth = (rows, field) => Object.fromEntries(rows.map((r) => [r.m, r[field]]));

function nasaHtml() {
  if (st.outside) return `<div class="hint">${t("card.outside")}</div>`;
  if (st.nasaState === "idle" || st.nasaState === "loading") return `<div class="hint loading">${t("nasa.loading")}</div>`;
  if (st.nasaState === "error") {
    return st.nasaErr?.code === "no_data" ? `<div class="hint">${t("nasa.noData")}</div>`
      : `<div class="hint">${t("nasa.error")} <button type="button" class="small" data-retry-nasa>${t("retry")}</button></div>`;
  }
  const d = st.nasa, T = d.temperature, A = d.demo_area, years = T.years ?? ["?", "?"];
  const sec = (title, note, svg, line) => `<div class="nsec"><h5>${esc(title)}</h5>${svg}<p class="hint">${esc(note)}</p>${line ? `<p class="nline">${esc(line)}</p>` : ""}</div>`;
  const tMean = byMonth(T.months, "mean"), warm = peakMonth(tMean);
  let h = `<p class="hint nintro">${esc(t("nasa.intro", { y0: years[0], y1: years[1] }))}</p>`;
  h += sec(t("nasa.tempTitle"), t("nasa.tempNote"),
    chartSvg({ mean: tMean, lo: byMonth(T.months, "min"), hi: byMonth(T.months, "max"), color: "#c8553d", aria: t("nasa.tempTitle"), digits: 0 }),
    warm ? t("nasa.warmest", { month: monthName(warm.m), v: warm.v }) : "");
  if (A) {
    h += `<p class="hint">${esc(t("nasa.area", { name: A.name, km: A.distance_km }))}</p>`;
    const rain = byMonth(A.rain.months, "mm"), wet = peakMonth(rain);
    if (A.rain.months.length) h += sec(t("nasa.rainTitle"), t("nasa.rainNote"), chartSvg({ bars: rain, color: "#2f6fa3", aria: t("nasa.rainTitle"), zero: true }),
      wet ? t("nasa.wettest", { month: monthName(wet.m), v: wet.v }) : "");
    const nd = byMonth(A.ndvi.months, "mean"), green = peakMonth(nd);
    if (A.ndvi.months.length) h += sec(t("nasa.ndviTitle"), t("nasa.ndviNote"),
      chartSvg({ mean: nd, lo: byMonth(A.ndvi.months, "min"), hi: byMonth(A.ndvi.months, "max"), color: "#2e7d4f", aria: t("nasa.ndviTitle"), digits: 1 }),
      green ? t("nasa.greenest", { month: monthName(green.m), v: green.v }) : "");
  } else {
    h += `<p class="note">${esc(t("nasa.noArea"))}</p>`;
  }
  h += `<div class="nsrc"><h5>${t("nasa.srcTitle")}</h5><ul>`
    + `<li>${esc(t("nasa.srcTemp", { lat: T.grid_cell.lat, lon: T.grid_cell.lon }))}</li>`
    + (A ? `<li>${esc(t("nasa.srcRain"))}</li><li>${esc(t("nasa.srcNdvi"))}</li>` : "") + "</ul></div>";
  return h;
}

function renderCard() {
  document.body.classList.toggle("card-wide", st.cardTab === "nasa");
  const head = cardTabs();
  if (st.cardTab === "nasa") { $("card").innerHTML = head + nasaHtml(); return; }
  if (st.outside) { $("card").innerHTML = `${head}<div class="hint">${t("card.outside")}</div>`; return; }
  if (st.layerState === "loading") { $("card").innerHTML = `${head}<div class="hint loading">${t("card.loading")}</div>`; return; }
  if (st.layerState === "error") { $("card").innerHTML = `${head}<div class="hint">${t("card.error")} <button type="button" class="small" data-retry-layer>${t("retry")}</button></div>`; return; }
  if (!st.cells.length) { $("card").innerHTML = `${head}<div class="hint">${t("card.empty")}</div>`; return; }
  const counts = countByClass(st.cells);
  const allHidden = Object.keys(counts).every((k) => st.hide.has(k));
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const bar = CLASSES.map((c) => `<i style="flex:${counts[c.key] ?? 0};background:var(--${c.key})"></i>`).join("");
  const checks = CLASSES.filter((c) => counts[c.key]).map((c) => `<label><input type="checkbox" data-k="${c.key}" ${st.hide.has(c.key) ? "" : "checked"}>${dot(c.key)}${cls(c.key)}: <b>${counts[c.key]}</b></label>`).join("");
  const idx = st.result?.cell_indices ?? {};
  const top = st.crops.filter((c) => c.rotatable && idx[c.crop_code] != null).sort((a, b) => idx[b.crop_code] - idx[a.crop_code]).slice(0, 4);
  const rows = top.map((c) => `<div class="bar"><span>${esc(c.name ?? c.name_vi)}</span><span><i style="width:${idx[c.crop_code] / 100}%;background:var(--${classOf(idx[c.crop_code]).key})"></i></span><span>${idx[c.crop_code]}</span></div>`).join("");
  $("card").innerHTML = `${head}
    <div class="sumblock"><div class="sumtitle">${esc(t("card.sumTitle", { crop: cropName(st.crop) }))}</div>
      <div class="hint" style="margin:-2px 0 8px">${t("card.hint")}</div>
      <div class="segbar">${bar}</div><div class="sumchecks">${checks}</div>
      ${allHidden ? `<div class="note">${t("card.allHidden")}</div>` : ""}
      ${st.hide.size ? `<button type="button" class="small" data-showall>${t("card.showAll")}</button>` : ""}
      <div class="hint">${esc(t("card.counts", { total, buffer: BUFFER_CELLS }))}</div></div>
    ${rows ? `<div class="sumblock"><div class="sumtitle">${t("card.best")}</div>${rows}</div>` : ""}`;
}

function renderLegend() {
  $("legend").innerHTML = `<b>${esc(t("legend.title", { crop: cropName(st.crop).toLowerCase() }))}</b>`
    + CLASSES.map((c) => `<span>${dot(c.key)}${cls(c.key)}<span class="dtl"> ${c.min ? c.min + "+" : "&lt;2000"}</span></span>`).join("")
    + `<span><i class="dot" style="background:#ffd84d;border-radius:2px"></i>${t("legend.selected")}</span><span>${t("legend.buffer")}</span>`;
}

function renderAssumptions() {
  const r = st.result;
  if (!r) { $("assump").innerHTML = `<p class="hint">${t("as.none")}</p>`; return; }
  const a = r.assumptions, custom = (x) => (x.custom ? t("as.custom") : "");
  const rows = r.index_classes.map((c) => `<tr><td>${dot(classOf(c.min_index).key)} ${esc(c.class)}</td><td>${esc(c.min_index)}–${esc(c.max_index)}</td><td>${esc(c.fao_yield_pct)}%</td></tr>`).join("");
  $("assump").innerHTML = `<ul class="assump">
    <li>${esc(a.season_order)}</li>
    <li>${esc(a.cycle_days)}</li>
    <li>${esc(a.gaez)}</li>
    <li>${t("as.gapRice")}: <b>${esc(t("as.days", { n: a.gap_rice.days }))}</b>${custom(a.gap_rice)}<span class="src">${esc(a.gap_rice.source)}</span></li>
    <li>${t("as.gapOther")}: <b>${esc(t("as.days", { n: a.gap_other.days }))}</b>${custom(a.gap_other)}<span class="src">${esc(a.gap_other.source)}</span></li>
    <li>${t("as.min")}: <b>${esc(a.min_index.value)}</b>${custom(a.min_index)}<span class="src">${esc(a.min_index.source)}</span></li>
  </ul>
  <h2 class="t2">${t("as.missing")}</h2>
  <ul class="assump">${r.missing.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
  <h2 class="t2">${t("as.read")}</h2>
  <table><tr><th>${t("as.thLevel")}</th><th>${t("as.thIndex")}</th><th>${t("as.thYield")}</th></tr>${rows}</table>
  <h2 class="t2">${t("as.source")}</h2>
  <p class="hint">${esc(r.options[0]?.evidence_source ?? "")}</p>
  <p class="hint">${esc(t("as.cell", { area: r.location.cell_area_km2 }))}</p>`;
}

function minLabel() {
  const v = Number($("minidx").value);
  $("minword").textContent = cls(classOf(v).key);
  $("minval").textContent = v;
  $("minclass").textContent = v >= 4000 ? t("adv.minOk") : t("adv.minLow");
}
function setTab(tab) {
  st.tab = tab;
  for (const k of ["res", "in", "as"]) { $(`v-${k}`).hidden = k !== tab; $(`tab-${k}`).setAttribute("aria-selected", k === tab); }
  document.querySelector(".pbody").scrollTop = 0;
}
function syncControls() {
  [...$("seas").children].forEach((b) => b.setAttribute("aria-pressed", (b.dataset.n === "" ? null : Number(b.dataset.n)) === st.n));
}

// ---- first-visit question (asked once, editable any time)
function provinceNames() {
  return [...new Set((st.features ?? []).map(nameOf))].sort((a, b) => a.localeCompare(b, "vi"));
}
function fillSelects() {
  const opts = provinceNames().map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  $("prov").innerHTML = `<option value="" hidden>${esc(t("sel.prov"))}</option>${opts}`;
  $("o-prov").innerHTML = `<option value="" hidden>${esc(t("sel.provShort"))}</option>${opts}`;
  const group = (label, items) => `<optgroup label="${esc(label)}">${items.map((c) => `<option value="${esc(c.crop_code)}">${esc(c.name ?? c.name_vi)}</option>`).join("")}</optgroup>`;
  $("o-crop").innerHTML = group(t("sel.annual"), st.crops.filter((c) => c.rotatable)) + group(t("sel.perennial"), st.crops.filter((c) => !c.rotatable));
  $("prov").value = st.shape ?? "";
  $("o-prov").value = st.shape ?? "";
  $("o-crop").value = st.crop;
}
function openOnb() { $("o-prov").value = st.shape ?? ""; $("o-crop").value = st.crop; $("o-geomsg").textContent = t("onb.geoHint"); $("onb").hidden = false; $("o-prov").focus(); }
const closeOnb = () => { $("onb").hidden = true; };

async function resetAll() {
  mem.del("fs.profile"); mem.del("fs.seen");
  Object.assign(st, EXAMPLE, { confirmed: false, hide: new Set() });
  $("minidx").value = 4000; $("gr").value = 7; $("go").value = 15;
  $("p-nitrogen").checked = true; $("p-pest_cycle").checked = false; $("p-yield").checked = false;
  minLabel(); syncControls();
  pickPoint(EXAMPLE.lat, EXAMPLE.lon, "fly", { confirm: false });
}

// ---- language: the interface text, the crop names and the generator's sentences all switch together
async function setLang(lang, { remember = true } = {}) {
  if (!LANGS.includes(lang)) return;
  const seq = ++langSeq;
  setLangState(lang); st.lang = lang;
  if (remember) mem.set("fs.lang", lang);
  document.querySelectorAll("#langsw button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  applyStatic(); setStaticPops();
  setCollapsed("left", document.body.classList.contains("left-collapsed"), { remember: false });
  setCollapsed("right", document.body.classList.contains("right-collapsed"), { remember: false });
  minLabel(); closePop();
  if (st.crops.length) {
    try { st.crops = await api.crops(lang); } catch { /* keep the names we already have */ }
    if (seq !== langSeq) return;
    fillSelects();
    loadOptions();                                               // new sentences from the generator
  }
  renderAll();
}

// ---- events
function bindEvents() {
  $("prov").onchange = (e) => e.target.value && goToProvince(e.target.value);
  $("crops").onclick = (e) => { const b = e.target.closest("button[data-c]"); if (b) { setCrop(b.dataset.c); renderCrops(); } };
  $("seas").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    st.n = b.dataset.n === "" ? null : Number(b.dataset.n); st.confirmed = true; syncControls(); save(); loadOptions();
  };
  for (const id of ["minidx", "gr", "go", "p-nitrogen", "p-pest_cycle", "p-yield"]) {
    $(id).addEventListener("input", () => { minLabel(); loadOptionsSoon(); });
  }
  $("tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) setTab(b.dataset.tab); };
  $("langsw").onclick = (e) => { const b = e.target.closest("button[data-lang]"); if (b && b.dataset.lang !== st.lang) setLang(b.dataset.lang); };
  document.addEventListener("mousedown", (e) => {               // a click outside closes the popover and does nothing else
    if ($("pop").hidden || e.target.closest("#pop") || e.target.closest("[data-pop]")) return;
    closePop();
    swallowMapClick = true;
    setTimeout(() => { swallowMapClick = false; }, 400);
  }, true);
  document.addEventListener("click", (e) => {                   // "i" popovers
    if (e.target.closest("[data-floor]")) return;
    const b = e.target.closest("[data-pop]");
    if (b) { openPop(b); return; }
    const g = e.target.closest("#pop [data-goto]");
    if (g) { closePop(); setTab(g.dataset.goto); return; }
    if (e.target.closest("#pop .x") || !e.target.closest("#pop")) closePop();
  });
  $("edit").onclick = $("mc-loc").onclick = $("mc-crop").onclick = $("newplan").onclick = openOnb;
  $("mc-n").onclick = () => setTab("in");
  $("card").addEventListener("change", (e) => {
    const k = e.target.dataset.k; if (!k) return;
    if (e.target.checked) st.hide.delete(k); else st.hide.add(k);
    drawCells(); renderCard();
  });
  $("card").addEventListener("click", (e) => {
    const tab = e.target.closest("[data-ctab]");
    if (tab) { st.cardTab = tab.dataset.ctab; mem.set("fs.ctab", st.cardTab); renderCard(); ensureNasa(); return; }
    if (e.target.closest("[data-showall]")) { st.hide.clear(); drawCells(); renderCard(); }
    else if (e.target.closest("[data-retry-layer]")) loadLayer();
    else if (e.target.closest("[data-retry-nasa]")) ensureNasa(true);
  });
  $("res-body").addEventListener("click", (e) => {
    if (e.target.closest("[data-retry]")) { loadOptions(); loadLayer(); return; }
    const f = e.target.closest("[data-floor]");
    if (f) { $("minidx").value = f.dataset.floor; minLabel(); loadOptions(); }
  });
  $("tgl-left").onclick = () => setCollapsed("left", !document.body.classList.contains("left-collapsed"));
  $("tgl-right").onclick = () => setCollapsed("right", !document.body.classList.contains("right-collapsed"));
  $("zin").onclick = () => map?.zoomIn();
  $("zout").onclick = () => map?.zoomOut();
  $("detail").onclick = (e) => {
    const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
    e.currentTarget.setAttribute("aria-pressed", String(on));
    document.body.classList.toggle("detail", on);
    mem.set("fs.detail", on ? "1" : "0");
  };

  $("o-ok").onclick = async () => {
    const name = $("o-prov").value, crop = $("o-crop").value;
    st.crop = crop; st.confirmed = true; mem.set("fs.seen", "1");
    closeOnb(); setTab("res");
    if (name && name !== st.shape) await goToProvince(name); else { loadLayer(); loadOptions(); save(); renderChips(); }
  };
  $("o-example").onclick = () => { mem.set("fs.seen", "1"); closeOnb(); };
  $("o-reset").onclick = () => { resetAll(); $("o-crop").value = EXAMPLE.crop; $("o-prov").value = EXAMPLE.shape; };
  $("o-geo").onclick = () => {
    if (!navigator.geolocation) { $("o-geomsg").textContent = t("onb.geoUnsupported"); return; }
    $("o-geomsg").textContent = t("onb.geoLoading");
    navigator.geolocation.getCurrentPosition((p) => {
      const name = findProvince(p.coords.longitude, p.coords.latitude, st.features);
      if (name) { pickPoint(p.coords.latitude, p.coords.longitude, "fly"); $("o-prov").value = name; $("o-geomsg").textContent = t("onb.geoDone", { name }); }
      else $("o-geomsg").textContent = t("onb.geoOutside");
    }, () => { $("o-geomsg").textContent = t("onb.geoDenied"); }, { timeout: 8000 });
  };
  $("onb").addEventListener("click", (e) => { if (e.target === $("onb")) closeOnb(); });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches?.('[data-pop][role="button"]')) { e.preventDefault(); openPop(e.target); return; }
    if (e.key !== "Escape") return;
    closePop();
    if (!$("onb").hidden) closeOnb();
  });
}

// ---- start
async function boot() {
  bindEvents();
  const lang = detectLang(mem.get("fs.lang"), navigator.language);   // saved choice, else the browser's language
  setLangState(lang); st.lang = lang;
  document.querySelectorAll("#langsw button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  applyStatic(); setStaticPops();
  st.cardTab = mem.get("fs.ctab") === "nasa" ? "nasa" : "sum";
  const savedDetail = mem.get("fs.detail");                      // detail view is the default; a saved choice wins
  if (savedDetail === null || savedDetail === "1") { $("detail").setAttribute("aria-pressed", "true"); document.body.classList.add("detail"); }
  setCollapsed("left", mem.get("fs.left") === "1", { remember: false });
  setCollapsed("right", (mem.get("fs.right") ?? (window.innerWidth < 1100 ? "1" : "0")) === "1", { remember: false });
  minLabel(); setTab("res"); initMap();
  $("res-body").innerHTML = `<p class="hint">${t("boot.loading")}</p>`;
  try {
    const [crops, geo] = await Promise.all([
      api.crops(lang),
      fetch("data/provinces.geojson").then((r) => { if (!r.ok) throw new Error("provinces"); return r.json(); }),
    ]);
    st.crops = crops; st.features = geo.features;
  } catch (e) {
    $("res-body").innerHTML = note(`${esc(t("boot.failed", { msg: e.message }))} <button type="button" class="small" data-retry-boot>${t("retry")}</button>`, "err");
    $("res-body").querySelector("[data-retry-boot]").onclick = () => location.reload();
    return;
  }
  const had = loadProfile();
  if (!st.crops.some((c) => c.crop_code === st.crop)) st.crop = st.crops.find((c) => c.rotatable)?.crop_code ?? st.crops[0].crop_code;
  fillSelects(); syncControls();
  st.move = "fit";
  const firstLayer = loadLayer();
  loadOptions();
  await firstLayer;
  moveMap();
  renderAll();
  if (!had && mem.get("fs.seen") !== "1") openOnb();
}
boot();
