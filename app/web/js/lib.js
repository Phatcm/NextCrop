// Pure helpers (no DOM, no network): grid maths, province lookup, cell selection. Tested with `node --test`.

export const STEP = 1 / 12;                                   // 5 arc-minutes, the GAEZ cell
export const GRID = { west: 102, east: 110, south: 8, north: 24 };

export const CLASSES = [
  { min: 8000, key: "c80", label: "Rất phù hợp" },
  { min: 6000, key: "c60", label: "Phù hợp" },
  { min: 4000, key: "c40", label: "Trung bình" },
  { min: 2000, key: "c20", label: "Biên" },
  { min: 0, key: "c0", label: "Rất biên" },
];
export const classOf = (v) => CLASSES.find((c) => v >= c.min) ?? CLASSES[CLASSES.length - 1];

const round4 = (x) => Math.round(x * 1e4) / 1e4;

// ---- point in polygon (GeoJSON rings are [lon, lat])
export function inRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
export function inPolygon(x, y, polygon) {                    // polygon = [outer, ...holes]
  if (!inRing(x, y, polygon[0])) return false;
  for (let k = 1; k < polygon.length; k++) if (inRing(x, y, polygon[k])) return false;
  return true;
}
export function polygonsOf(feature) {
  const g = feature.geometry;
  return g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
}
export const nameOf = (feature) => String(feature.properties?.shapeName ?? "").trim();

/** Name of the province that contains the point, or null (outside Vietnam, or at sea). */
export function findProvince(lon, lat, features) {
  for (const f of features) for (const p of polygonsOf(f)) if (inPolygon(lon, lat, p)) return nameOf(f);
  return null;
}
export const polygonsNamed = (features, name) => features.filter((f) => nameOf(f) === name).flatMap(polygonsOf);

export function provinceBounds(features, name) {              // [[west, south], [east, north]] or null
  const polys = polygonsNamed(features, name);
  if (!polys.length) return null;
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const p of polys) for (const [x, y] of p[0]) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
  return [[w, s], [e, n]];
}
export function expandBounds(b, d) {                          // grow by d degrees, stay inside the data grid
  return [[Math.max(GRID.west, b[0][0] - d), Math.max(GRID.south, b[0][1] - d)],
          [Math.min(GRID.east, b[1][0] + d), Math.min(GRID.north, b[1][1] + d)]];
}

export function provinceCentroid(features, name) {            // centroid of the largest ring: {lat, lon} or null
  const polys = polygonsNamed(features, name);
  if (!polys.length) return null;
  const ring = polys.map((p) => p[0]).sort((a, b) => b.length - a.length)[0];
  let a = 0, cx = 0, cy = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const k = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    a += k; cx += (ring[j][0] + ring[i][0]) * k; cy += (ring[j][1] + ring[i][1]) * k;
  }
  if (a === 0) return { lon: ring[0][0], lat: ring[0][1] };
  return { lon: cx / (3 * a), lat: cy / (3 * a) };
}

// ---- grid (same convention as the pipeline: centre = 24 - (i + 0.5)/12, 102 + (j + 0.5)/12, 4 decimals)
export const cellOf = (lat, lon) => ({ i: Math.floor((GRID.north - lat) / STEP), j: Math.floor((lon - GRID.west) / STEP) });
export const cellCentre = (i, j) => ({ lat: round4(GRID.north - (i + 0.5) * STEP), lon: round4(GRID.west + (j + 0.5) * STEP) });
export function cellRing(lat, lon) {
  const h = STEP / 2;
  return [[lon - h, lat + h], [lon + h, lat + h], [lon + h, lat - h], [lon - h, lat - h], [lon - h, lat + h]];
}

/** Cells of one province plus a buffer of `margin` cells around it. Input: [{lat, lon, index}] from /api/cells
 *  (land cells only: the API has no row for the sea). Output adds i, j and `inside`. */
export function selectCells(cells, features, name, margin = 2) {
  const polys = polygonsNamed(features, name);
  const all = cells.map((c) => ({ ...c, ...cellOf(c.lat, c.lon), inside: polys.some((p) => inPolygon(c.lon, c.lat, p)) }));
  const inside = new Set(all.filter((c) => c.inside).map((c) => `${c.i},${c.j}`));
  const near = (c) => {
    for (let di = -margin; di <= margin; di++) for (let dj = -margin; dj <= margin; dj++) if (inside.has(`${c.i + di},${c.j + dj}`)) return true;
    return false;
  };
  return all.filter((c) => c.inside || near(c));
}

export function nearestInside(cells, lat, lon) {
  let best = null, bestD = Infinity;
  for (const c of cells) {
    if (!c.inside) continue;
    const d = (c.lat - lat) ** 2 + (c.lon - lon) ** 2;
    if (d < bestD) { best = c; bestD = d; }
  }
  return best;
}

export function countByClass(cells) {                         // inside cells only: {c80: n, ...}
  const out = {};
  for (const c of cells) if (c.inside) out[classOf(c.index).key] = (out[classOf(c.index).key] ?? 0) + 1;
  return out;
}

/** Words for the difference in mean index between an option and "keep as is". */
export function tradeoff(delta) {
  const d = Math.round(delta);
  if (Math.abs(d) < 300) return { dir: "same", text: "Mức phù hợp tương đương giữ nguyên", delta: d };
  if (d > 0) return { dir: "up", text: "Mức phù hợp cao hơn giữ nguyên", delta: d };
  return { dir: "down", text: `Mức phù hợp ${d > -1000 ? "hơi " : ""}thấp hơn giữ nguyên${d > -1000 ? "" : " rõ"}`, delta: d };
}

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
