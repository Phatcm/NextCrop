// NextCrop UI: form on the left, satellite map with the 5 arc-minute data cells, results from /api.
import * as api from "./api.js";
import {
  CLASSES, STEP, classOf, findProvince, provinceBounds, provinceCentroid, expandBounds, cellOf, cellRing,
  selectCells, nearestInside, countByClass, tradeoff, nameOf, esc,
} from "./lib.js";

const $ = (id) => document.getElementById(id);
const MODE = "hrlm";                                           // rain-fed, high inputs (the API default)
const BUFFER_CELLS = 2;
const HEX = { c80: "#2e7d4f", c60: "#7fb069", c40: "#e3c04a", c20: "#e08a3c", c0: "#c8553d" };
const EXAMPLE = { shape: "An Giang", lat: 10.45, lon: 105.35, crop: "RCW", n: null };

const st = {
  ...EXAMPLE, move: null, hide: new Set(), tab: "res", confirmed: false, outside: false,
  crops: [], features: null, result: null, error: null, loading: false, cells: [],
  layerState: "idle",                                          // idle | loading | ready | empty | error (the cell layer)
  navSeq: 0,                                                   // a newer navigation cancels an older, slower one
};
let map, mapReady = false, pin;
let optSeq = 0, layerSeq = 0, optCtl = null, layerCtl = null;

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
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const cropOf = (code) => st.crops.find((c) => c.crop_code === code);
const cropName = (code) => cropOf(code)?.name_vi ?? code;
const note = (html, cls = "") => `<p class="note ${cls}">${html}</p>`;
const numOrNull = (el) => (el.value === "" ? null : Number(el.value));
const priorities = () => ["nitrogen", "pest_cycle", "yield"].filter((p) => $(`p-${p}`).checked);
const dot = (key) => `<i class="dot" style="background:var(--${key})"></i>`;
const rawNames = (name) => (st.features ?? []).filter((f) => nameOf(f) === name).map((f) => f.properties.shapeName);

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
const SIDE = { left: ["bảng điều khiển", "panel"], right: ["bảng tóm tắt", "card"] };
function setCollapsed(side, on, { remember = true } = {}) {
  document.body.classList.toggle(`${side}-collapsed`, on);
  const b = $(`tgl-${side}`);
  b.setAttribute("aria-expanded", String(!on));
  b.setAttribute("aria-label", `${on ? "Hiện" : "Ẩn"} ${SIDE[side][0]}`);
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
  min_index: $("minidx").value, gap_rice: numOrNull($("gr")), gap_other: numOrNull($("go")),
});

async function loadOptions() {
  const seq = ++optSeq;
  optCtl?.abort();
  optCtl = new AbortController();
  if (st.outside) { st.result = null; st.error = null; st.loading = false; renderAll(); return; }
  st.loading = true;
  renderResults();
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
  if (!st.features) { st.error = { code: "no_boundaries", message: "Chưa tải được ranh giới tỉnh nên chưa chọn được điểm." }; renderResults(); return; }
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
  const where = st.shape ?? "Ngoài ranh giới tỉnh";
  $("place").innerHTML = `${esc(where)} · <span class="dtl">${st.lat.toFixed(3)}°N ${st.lon.toFixed(3)}°E · </span>ô dữ liệu ≈ ${area ? esc(area) : "80–85"} km²`;
}
function renderChips() {
  $("mc-loc").textContent = st.outside ? "Chưa chọn vị trí hợp lệ" : st.shape ?? "…";
  $("mc-crop").textContent = cropName(st.crop);
  $("mc-n").textContent = st.n ? `${st.n} vụ` : `Số vụ tự động${st.result ? ` (${st.result.seasons})` : ""}`;
}

function errorHtml(e) {
  const retry = ` <button type="button" class="small" data-retry>Thử lại</button>`;
  if (e.code === "no_data") return note("Ô này không có dữ liệu GAEZ (biển, hoặc không có đất canh tác). Bấm vào một ô khác trên đất liền.");
  if (e.code === "outside_grid") return note("Điểm này nằm ngoài vùng dữ liệu của công cụ (102–110°E, 8–24°N).");
  if (e.code === "no_boundaries") return note(esc(e.message));
  if (["network", "db_unavailable", "db_not_configured"].includes(e.code) || e.status >= 500)
    return note(`Không đọc được dữ liệu từ máy chủ. ${esc(e.message)}${retry}`, "err");
  return note(esc(e.message ?? "Có lỗi."), "err");
}
const chipHtml = (e) => {
  const c = classOf(e.gaez_index);
  return `<span class="chip" title="${esc(e.gaez_class)}">${dot(c.key)}${esc(e.name_vi)} <small>${c.label}<span class="dtl"> · ${e.gaez_index}</span></small></span>`;
};

// ---- "i" popovers: extra information stays out of the way until asked for (click, so it works on a phone too)
const pops = {};
const setPop = (key, html) => { pops[key] = html; };
const infoBtn = (key, tone = "") => `<button type="button" class="info ${tone}" data-pop="${key}" aria-label="Thông tin thêm" aria-haspopup="dialog">i</button>`;
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
const WATER = { wetland: "ngập nước", upland: "cạn" };
function evidenceTable(o) {
  const seen = new Set();
  const rows = o.evidence.filter((e) => !seen.has(e.crop_code) && seen.add(e.crop_code)).map((e) => {
    const c = classOf(e.gaez_index);
    return `<tr><td>${esc(e.name_vi)}<span class="src">${esc(e.family)}${e.is_legume ? ", họ đậu" : ""}; ${esc(WATER[e.water_regime] ?? "")}</span></td><td>${dot(c.key)} ${c.label} (${esc(e.gaez_index)})</td><td>${esc(e.cycle_days_min)} ngày</td></tr>`;
  }).join("");
  return `<table><tr><th>Cây</th><th>Mức phù hợp</th><th>Vụ ngắn nhất</th></tr>${rows}</table>`;
}
const list = (cls, items) => `<ul class="${cls}">${items.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`;
function optionPop(o) {
  const c = o.components;
  return `<h4>${esc(o.label)}</h4>
    ${o.benefits.length ? `<div class="pt">Lợi ích</div>${list("bn", o.benefits)}` : ""}
    ${o.risks.length ? `<div class="pt">Rủi ro</div>${list("rk", o.risks)}` : ""}
    <div class="pt">Từng cây</div>${evidenceTable(o)}
    <p class="hint">Cần khoảng ${esc(c.cycle_days_total)} ngày, tính cả nghỉ giữa vụ ${esc(c.days_with_buffer)} ngày${c.fits_year ? `, dư ${esc(c.slack_days)} ngày` : " (không vừa một năm)"}. Chỉ số trung bình ${esc(c.gaez_mean)}.</p>
    <p class="hint">Nguồn: ${esc(o.evidence_source)}</p>`;
}

function renderResults() {
  const box = $("res-body"), title = $("res-title");
  box.classList.toggle("busy", st.loading && !!st.result);
  closePop();
  $("res-info").innerHTML = "";
  if (st.outside) {
    title.textContent = "Phương án"; $("tab-res").textContent = "Gợi ý";
    box.innerHTML = note("Điểm này nằm ngoài ranh giới các tỉnh Việt Nam (hoặc ngoài khơi), nên công cụ không đưa ra gợi ý. Bấm vào một điểm trên đất liền Việt Nam.");
    return;
  }
  if (st.error) { title.textContent = "Phương án"; $("tab-res").textContent = "Gợi ý"; box.innerHTML = errorHtml(st.error); return; }
  const r = st.result;
  if (!r) { title.textContent = "Phương án"; box.innerHTML = '<p class="hint">Đang tính…</p>'; return; }
  if (r.message) {
    title.textContent = cropName(st.crop); $("tab-res").textContent = "Gợi ý";
    box.innerHTML = note(esc(r.message)) + '<p class="hint">Chọn một cây một năm trong tab Tuỳ chỉnh để xem phương án luân canh.</p>';
    return;
  }
  const keep = r.options[0], fh = r.floor_hint;
  $("tab-res").textContent = `Gợi ý (${r.options.length})`;
  title.textContent = `${r.options.length} phương án cho ${cropName(st.crop).toLowerCase()} ở ${st.shape}`;

  // one popover for how the options are made (and the ones that could not be made)
  setPop("title", `<h4>Về các phương án này</h4><p>${esc(r.note)}</p>`
    + (r.ranked_by.length ? `<p>Xếp theo: ${esc(r.ranked_by.map((p) => p.meaning).join("; "))}.</p>` : "")
    + `<p>${esc(r.principle)}</p>`
    + (r.skipped.length ? `<div class="pt">Phương án không tạo được</div>${list("assump", r.skipped.map((q) => q.reason))}` : ""));
  $("res-info").innerHTML = infoBtn("title");

  // alerts: one short line in compact mode, the full text in detail mode and in the popover
  const unsupported = r.unsupported_priorities.map((u) => `Chưa hỗ trợ ưu tiên “${u.priority}”: ${u.reason}.`);
  const alerts = [...r.warnings, ...unsupported, ...(fh ? [fh.message] : [])];
  let h = "";
  if (alerts.length) {
    setPop("alerts", `<h4>Lưu ý</h4>${list("assump", alerts)}`);
    const floorBtn = fh?.min_index != null ? ` <button type="button" class="small" data-floor="${esc(fh.min_index)}">Dùng ngưỡng ${esc(fh.min_index)}</button>` : "";
    const short = fh ? `Chỉ có ${r.options.length} phương án ở mức tối thiểu hiện tại.` : "Có lưu ý về mức phù hợp của cây.";
    h += `<div class="note" data-pop="alerts" role="button" tabindex="0" aria-haspopup="dialog">${esc(short)}${floorBtn}</div>`;
  }

  h += r.options.map((o) => {
    const cmp = o.components, t = o.id === "keep" ? null : tradeoff(cmp.gaez_mean - keep.components.gaez_mean);
    const arrow = { up: "▲", down: "▼", same: "＝" };
    const key = `opt-${o.id}`;
    setPop(key, optionPop(o));
    const bad = o.evidence.some((e) => e.gaez_index < 4000);
    const tone = bad ? "bad" : o.risks.length ? "warn" : o.benefits.length ? "ok" : "";
    const badges = [
      o.benefits.length ? `<button type="button" class="bd ok" data-pop="${key}">✓ ${o.benefits.length} lợi ích</button>` : "",
      bad ? `<button type="button" class="bd bad" data-pop="${key}">! Có cây dưới mức khả thi</button>`
        : (o.risks.length ? `<button type="button" class="bd warn" data-pop="${key}">! ${o.risks.length} rủi ro</button>` : ""),
    ].join("");
    return `<div class="opt ${o.id === "keep" ? "keep" : ""} t-${tone || "none"}" data-pop="${key}" role="button" tabindex="0" aria-haspopup="dialog" aria-label="Xem chi tiết: ${esc(o.label)}">
      <h3>${esc(o.label)}${o.id === "keep" ? '<span class="tag">Hiện tại</span>' : ""}</h3>
      <div class="seasons">${o.evidence.map(chipHtml).join("")}</div>
      ${t ? `<p class="trade ${t.dir}">${arrow[t.dir]} ${esc(t.text)}<span class="dtl"> (${t.delta > 0 ? "+" : ""}${t.delta})</span></p>` : '<p class="trade same">Mốc so sánh cho các phương án còn lại.</p>'}
      ${badges ? `<div class="badges">${badges}</div>` : ""}
    </div>`;
  }).join("");

  box.innerHTML = h;
}

function renderCrops() {
  const idx = st.result?.cell_indices ?? {};
  const level = (code) => {
    const v = idx[code];
    if (v == null) return '<span class="hint">chưa có</span>';
    const c = classOf(v);
    return `${dot(c.key)}<span>${c.label}</span><span class="dtl">${v}</span>`;
  };
  const row = (c) => `<button type="button" role="radio" aria-checked="${c.crop_code === st.crop}" data-c="${esc(c.crop_code)}">${esc(c.name_vi)}${c.name_verified ? "" : '<span class="dtl"> *</span>'}<span class="v">${level(c.crop_code)}</span></button>`;
  const byIdx = (a, b) => (idx[b.crop_code] ?? -1) - (idx[a.crop_code] ?? -1) || a.name_vi.localeCompare(b.name_vi, "vi");
  const annual = st.crops.filter((c) => c.rotatable).sort(byIdx), perennial = st.crops.filter((c) => !c.rotatable).sort(byIdx);
  $("crops").innerHTML = `<div class="grp">Cây một năm (có gợi ý luân canh)</div>${annual.map(row).join("")}`
    + `<div class="grp">Cây lâu năm (chưa có gợi ý luân canh)</div>${perennial.map(row).join("")}`;
}

function renderCard() {
  const head = "<h4>Tóm tắt khu vực</h4>";
  if (st.outside) { $("card").innerHTML = `${head}<div class="hint">Điểm đang chọn nằm ngoài ranh giới tỉnh, nên không có ô nào.</div>`; return; }
  if (st.layerState === "loading") { $("card").innerHTML = `${head}<div class="hint">Đang tải các ô dữ liệu…</div>`; return; }
  if (st.layerState === "error") { $("card").innerHTML = `${head}<div class="hint">Không tải được các ô dữ liệu. <button type="button" class="small" data-retry-layer>Thử lại</button></div>`; return; }
  if (!st.cells.length) { $("card").innerHTML = `${head}<div class="hint">Tỉnh này không có ô dữ liệu cho cây đang chọn.</div>`; return; }
  const counts = countByClass(st.cells);
  const allHidden = Object.keys(counts).every((k) => st.hide.has(k));
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const bar = CLASSES.map((c) => `<i style="flex:${counts[c.key] ?? 0};background:var(--${c.key})"></i>`).join("");
  const checks = CLASSES.filter((c) => counts[c.key]).map((c) => `<label><input type="checkbox" data-k="${c.key}" ${st.hide.has(c.key) ? "" : "checked"}>${dot(c.key)}${c.label}: <b>${counts[c.key]}</b></label>`).join("");
  const idx = st.result?.cell_indices ?? {};
  const top = st.crops.filter((c) => c.rotatable && idx[c.crop_code] != null).sort((a, b) => idx[b.crop_code] - idx[a.crop_code]).slice(0, 4);
  const rows = top.map((c) => `<div class="bar"><span>${esc(c.name_vi)}</span><span><i style="width:${idx[c.crop_code] / 100}%;background:var(--${classOf(idx[c.crop_code]).key})"></i></span><span>${idx[c.crop_code]}</span></div>`).join("");
  $("card").innerHTML = `<h4>Tóm tắt khu vực</h4>
    <div class="sumblock"><div class="sumtitle">Ô theo mức phù hợp · ${esc(cropName(st.crop))}</div>
      <div class="hint" style="margin:-2px 0 8px">Bấm vào ô vuông để ẩn hoặc hiện từng mức.</div>
      <div class="segbar">${bar}</div><div class="sumchecks">${checks}</div>
      ${allHidden ? '<div class="note">Đang ẩn tất cả các mức nên bản đồ không còn ô nào.</div>' : ""}
      ${st.hide.size ? '<button type="button" class="small" data-showall>Hiện tất cả</button>' : ""}
      <div class="hint">${total} ô nằm trong tỉnh; ô mờ ngoài biên là vùng đệm ${BUFFER_CELLS} ô.</div></div>
    ${rows ? `<div class="sumblock"><div class="sumtitle">Cây một năm hợp nhất ở ô đã chọn</div>${rows}</div>` : ""}`;
}

function renderLegend() {
  $("legend").innerHTML = `<b>Màu ô = mức phù hợp của ${esc(cropName(st.crop).toLowerCase())}</b>`
    + CLASSES.map((c) => `<span>${dot(c.key)}${c.label}<span class="dtl"> ${c.min ? c.min + "+" : "&lt;2000"}</span></span>`).join("")
    + '<span><i class="dot" style="background:#ffd84d;border-radius:2px"></i>Tỉnh đang chọn</span><span>Ô mờ: vùng đệm ngoài biên</span>';
}

function renderAssumptions() {
  const r = st.result;
  if (!r) { $("assump").innerHTML = '<p class="hint">Chưa có kết quả để hiện giả định.</p>'; return; }
  const a = r.assumptions, custom = (x) => (x.custom ? " (đã chỉnh)" : "");
  const cls = r.index_classes.map((c) => `<tr><td>${dot(classOf(c.min_index).key)} ${esc(c.class)}</td><td>${esc(c.min_index)}–${esc(c.max_index)}</td><td>${esc(c.fao_yield_pct)}%</td></tr>`).join("");
  $("assump").innerHTML = `<ul class="assump">
    <li>${esc(a.season_order)}</li>
    <li>${esc(a.cycle_days)}</li>
    <li>${esc(a.gaez)}</li>
    <li>Nghỉ giữa hai vụ lúa: <b>${esc(a.gap_rice.days)} ngày</b>${custom(a.gap_rice)}<span class="src">${esc(a.gap_rice.source)}</span></li>
    <li>Nghỉ giữa các vụ khác: <b>${esc(a.gap_other.days)} ngày</b>${custom(a.gap_other)}<span class="src">${esc(a.gap_other.source)}</span></li>
    <li>Mức phù hợp tối thiểu: <b>${esc(a.min_index.value)}</b>${custom(a.min_index)}<span class="src">${esc(a.min_index.source)}</span></li>
  </ul>
  <h2 class="t2">Chưa xét</h2>
  <ul class="assump">${r.missing.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
  <h2 class="t2">Cách đọc mức phù hợp</h2>
  <table><tr><th>Mức</th><th>Chỉ số</th><th>% năng suất tối đa</th></tr>${cls}</table>
  <h2 class="t2">Nguồn dữ liệu</h2>
  <p class="hint">${esc(r.options[0]?.evidence_source ?? "")}</p>
  <p class="hint">Ô dữ liệu của điểm đã chọn rộng khoảng ${esc(r.location.cell_area_km2)} km². Ranh giới tỉnh: geoBoundaries (miền công cộng), phiên bản năm 2008 nên có thể không khớp tên và ranh giới hiện hành.</p>`;
}

function minLabel() {
  const v = Number($("minidx").value);
  $("minword").textContent = classOf(v).label;
  $("minval").textContent = v;
  $("minclass").textContent = v >= 4000 ? "Cây thấp hơn mức này sẽ bị loại khỏi gợi ý." : "Cho phép cả cây khó khả thi, có cảnh báo rủi ro.";
}
function setTab(t) {
  st.tab = t;
  for (const k of ["res", "in", "as"]) { $(`v-${k}`).hidden = k !== t; $(`tab-${k}`).setAttribute("aria-selected", k === t); }
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
  $("prov").innerHTML = `<option value="" hidden>Chọn tỉnh hoặc bấm vào bản đồ</option>${opts}`;
  $("o-prov").innerHTML = `<option value="" hidden>Chọn tỉnh</option>${opts}`;
  const group = (label, list) => `<optgroup label="${label}">${list.map((c) => `<option value="${esc(c.crop_code)}">${esc(c.name_vi)}</option>`).join("")}</optgroup>`;
  $("o-crop").innerHTML = group("Cây một năm (có gợi ý luân canh)", st.crops.filter((c) => c.rotatable))
    + group("Cây lâu năm (chưa có gợi ý luân canh)", st.crops.filter((c) => !c.rotatable));
  $("prov").value = st.shape ?? "";
}
function openOnb() { $("o-prov").value = st.shape ?? ""; $("o-crop").value = st.crop; $("o-geomsg").textContent = " hoặc đóng hộp này rồi bấm vào bản đồ."; $("onb").hidden = false; $("o-prov").focus(); }
const closeOnb = () => { $("onb").hidden = true; };

async function resetAll() {
  mem.del("fs.profile"); mem.del("fs.seen");
  Object.assign(st, EXAMPLE, { confirmed: false, hide: new Set() });
  $("minidx").value = 4000; $("gr").value = 7; $("go").value = 15;
  $("p-nitrogen").checked = true; $("p-pest_cycle").checked = false; $("p-yield").checked = false;
  minLabel(); syncControls();
  pickPoint(EXAMPLE.lat, EXAMPLE.lon, "fly", { confirm: false });
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
    if (e.target.closest("[data-showall]")) { st.hide.clear(); drawCells(); renderCard(); }
    else if (e.target.closest("[data-retry-layer]")) loadLayer();
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
    if (!navigator.geolocation) { $("o-geomsg").textContent = " Trình duyệt không hỗ trợ lấy vị trí."; return; }
    $("o-geomsg").textContent = " Đang lấy vị trí…";
    navigator.geolocation.getCurrentPosition((p) => {
      const name = findProvince(p.coords.longitude, p.coords.latitude, st.features);
      if (name) { pickPoint(p.coords.latitude, p.coords.longitude, "fly"); $("o-prov").value = name; $("o-geomsg").textContent = ` Đã lấy vị trí: ${name}.`; }
      else $("o-geomsg").textContent = " Vị trí của bạn không nằm trong ranh giới tỉnh nào của Việt Nam. Hãy chọn tỉnh thủ công.";
    }, () => { $("o-geomsg").textContent = " Không lấy được vị trí. Hãy chọn tỉnh hoặc bấm vào bản đồ."; }, { timeout: 8000 });
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
  const savedDetail = mem.get("fs.detail");                      // detail view is the default; a saved choice wins
  if (savedDetail === null || savedDetail === "1") { $("detail").setAttribute("aria-pressed", "true"); document.body.classList.add("detail"); }
  setPop("prio", "<h4>Ưu tiên</h4><p>Đang hỗ trợ: cải tạo đất (cây họ đậu trước), giảm sâu bệnh (ít vụ liền nhau cùng họ), mức phù hợp cao.</p><p>Chưa có dữ liệu cho ưu tiên về nước, xói mòn, thu nhập và đất (xem tab Giả định).</p>");
  setPop("disc", '<h4>Về công cụ này</h4><p>Công cụ chỉ hỗ trợ ra quyết định, không thay thế phán đoán của nông dân hay chuyên gia địa phương.</p><p>Dữ liệu theo ô khoảng 80–85 km², là mức trung bình cho cả vùng chứ không phải cho một thửa ruộng.</p><p><button type="button" class="link" data-goto="as">Xem giả định</button></p>');
  setCollapsed("left", mem.get("fs.left") === "1", { remember: false });
  setCollapsed("right", (mem.get("fs.right") ?? (window.innerWidth < 1100 ? "1" : "0")) === "1", { remember: false });
  minLabel(); setTab("res"); initMap();
  $("res-body").innerHTML = '<p class="hint">Đang tải dữ liệu…</p>';
  try {
    const [crops, geo] = await Promise.all([
      api.crops(),
      fetch("data/provinces.geojson").then((r) => { if (!r.ok) throw new Error("provinces"); return r.json(); }),
    ]);
    st.crops = crops; st.features = geo.features;
  } catch (e) {
    $("res-body").innerHTML = note(`Không tải được dữ liệu ban đầu (${esc(e.message)}). <button type="button" class="small" data-retry-boot>Thử lại</button>`, "err");
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
